
import os
import copy
import logging
from typing import List, Dict, Optional, Tuple
from bisect import bisect_left, bisect_right
import numpy as np
from scipy.signal import correlate, find_peaks

from backend.utils import VideoSegment, _format_time
from funscript import DualAxisFunscript
from config import constants
from config.constants import ChapterSource
from backend.classes import UndoRedoManager

class AppFunscriptProcessor:
    def __init__(self, funscript: DualAxisFunscript, undo_manager_t1: UndoRedoManager, undo_manager_t2: UndoRedoManager, logger: logging.Logger):
        self.funscript = funscript
        self.undo_manager_t1 = undo_manager_t1
        self.undo_manager_t2 = undo_manager_t2
        self.logger = logger

        # Chapters and Scripting Range
        self.video_chapters: List[VideoSegment] = []
        self.chapter_bar_height = 20

        # These would be managed and potentially loaded by ProjectManager
        self.selected_chapter_for_scripting: Optional[VideoSegment] = None
        self.scripting_range_active: bool = False
        self.scripting_start_frame: int = 0
        self.scripting_end_frame: int = 0

        # Funscript Attributes (stats are per timeline)
        self.funscript_stats_t1: Dict = self._get_default_funscript_stats()
        self.funscript_stats_t2: Dict = self._get_default_funscript_stats()

        # Selection state for operations (indices for the currently active_axis_for_processing)
        self.current_selection_indices: List[int] = []

        # Funscript Operations Parameters
        self.selected_axis_for_processing: str = 'primary'  # 'primary' or 'secondary'
        self.operation_target_mode: str = 'apply_to_scripting_range'  # or 'apply_to_selected_points'
        self.sg_window_length_input: int = 5
        self.sg_polyorder_input: int = 2
        self.rdp_epsilon_input: float = 8.0
        self.amplify_factor_input: float = 1.1
        self.amplify_center_input: int = 50

        # Clipboard
        self.clipboard_actions_data: List[Dict] = []

    def compare_funscript_signals(self, actions_ref: List[Dict], actions_target: List[Dict],
                                  prominence: int = 5) -> Dict:
        """
        Compares a target funscript (e.g., Stage 3) to a reference (e.g., Stage 2).

        This method uses cross-correlation on detected signal peaks to find the optimal
        time offset and gathers key comparative statistics.

        Args:
            actions_ref (List[Dict]): The reference signal with correct timing (e.g., Stage 2).
            actions_target (List[Dict]): The signal to compare and align (e.g., Stage 3).
            prominence (int): The prominence used for peak/valley detection. A higher value
                              detects only more significant strokes.

        Returns:
            Dict: A dictionary of comparison statistics, including the calculated time offset.
        """
        stats = {
            "calculated_offset_ms": 0,
            "ref_stroke_count": 0,
            "target_stroke_count": 0,
            "error": None
        }

        if not actions_ref or not actions_target:
            stats["error"] = "One or both action lists are empty."
            self.logger.warning(stats["error"])
            return stats

        # --- 1. Feature Extraction: Get Peaks and Valleys Timestamps ---
        def get_extrema_times(actions: List[Dict]) -> np.ndarray:
            if len(actions) < 3:
                return np.array([], dtype=int)

            positions = np.array([a['pos'] for a in actions])

            # Find peaks (maxima)
            peaks, _ = find_peaks(positions, prominence=prominence)

            # Find valleys (minima) by inverting the signal
            valleys, _ = find_peaks(-positions, prominence=prominence)

            # Combine, sort, and get the timestamps
            extrema_indices = np.unique(np.concatenate((peaks, valleys)))

            if len(extrema_indices) == 0:
                return np.array([], dtype=int)

            return np.array([actions[i]['at'] for i in extrema_indices], dtype=int)

        ref_extrema_times = get_extrema_times(actions_ref)
        target_extrema_times = get_extrema_times(actions_target)

        stats["ref_stroke_count"] = len(ref_extrema_times)
        stats["target_stroke_count"] = len(target_extrema_times)

        if len(ref_extrema_times) < 5 or len(target_extrema_times) < 5:
            stats["error"] = "Not enough significant peaks/valleys found to perform a reliable correlation."
            self.logger.warning(stats["error"])
            return stats

        # --- 2. Offset Calculation using Cross-Correlation ---
        # Determine the total duration for the binary signals
        duration = max(actions_ref[-1]['at'], actions_target[-1]['at']) + 1

        # Create binary event signals where '1' marks a peak/valley
        ref_signal = np.zeros(duration)
        target_signal = np.zeros(duration)
        ref_signal[ref_extrema_times] = 1
        target_signal[target_extrema_times] = 1

        # Compute the cross-correlation
        correlation = correlate(target_signal, ref_signal, mode='full', method='fft')

        # The lag is the offset from the center of the correlation array where the peak occurs
        delay_array_index = np.argmax(correlation)
        # The center of the 'full' correlation result corresponds to a lag of 0
        center_index = len(ref_signal) - 1
        lag = delay_array_index - center_index

        stats["calculated_offset_ms"] = int(lag)
        self.logger.info( f"Signal comparison complete. Calculated offset: {lag} ms. Ref strokes: {stats['ref_stroke_count']}, Target strokes: {stats['target_stroke_count']}.")

        return stats

    def get_chapter_at_frame(self, frame_index: int) -> Optional[VideoSegment]:
        """
        Efficiently finds the chapter that contains the given frame index.
        Returns None if the frame is not within any chapter (i.e., in a gap).
        Assumes chapters are sorted by start_frame_id.
        """
        # This is a simple linear scan. For a huge number of chapters,
        # a binary search (bisect_right) would be more efficient.
        # For typical use cases, this is fast enough and simpler.
        for chapter in self.video_chapters:
            if chapter.start_frame_id <= frame_index <= chapter.end_frame_id:
                return chapter
        return None

    def _sync_chapters_to_funscript(self, fps):
        """Sync app-level chapters to funscript object chapters."""
        try:
            if not self.funscript:
                self.logger.debug("No funscript object available for chapter sync")
                return

            if not hasattr(self.funscript, 'clear_chapters') or not hasattr(self.funscript, 'add_chapter'):
                self.logger.warning("Funscript object missing chapter methods")
                return

            self.funscript.clear_chapters()
            if fps <= 0:
                self.logger.warning("Invalid FPS for chapter sync, using default 30.0")
                fps = 30.0

            for segment in self.video_chapters:
                if hasattr(segment, 'start_frame_id') and hasattr(segment, 'end_frame_id'):
                    start_time_ms = int((segment.start_frame_id / fps) * 1000)
                    end_time_ms = int((segment.end_frame_id / fps) * 1000)
                    self.funscript.add_chapter(
                        start_time_ms,
                        end_time_ms,
                        getattr(segment, 'position_long_name', segment.class_name),
                        getattr(segment, 'position_short_name', ''),
                        getattr(segment, 'position_long_name', '')
                    )
            self.logger.debug(f"Synced {len(self.video_chapters)} chapters to funscript object")
        except Exception as e:
            self.logger.error(f"Error syncing chapters to funscript: {e}", exc_info=True)

    def _sync_chapters_from_funscript(self, fps):
        """Sync funscript object chapters to app-level chapters."""
        try:
            if not self.funscript:
                self.logger.debug("No funscript object available for chapter sync")
                return

            if not hasattr(self.funscript, 'chapters'):
                self.logger.debug("Funscript object has no chapters attribute")
                return

            if not self.funscript.chapters:
                self.logger.debug("Funscript object has empty chapters list")
                return

            if fps <= 0:
                self.logger.warning("Invalid FPS for chapter sync, using default 30.0")
                fps = 30.0

            self.video_chapters = []
            for chapter in self.funscript.chapters:
                try:
                    # Convert timestamps back to frame IDs
                    start_frame_id = int((chapter.get('start', 0) / 1000) * fps)
                    end_frame_id = int((chapter.get('end', 0) / 1000) * fps)
                    segment = VideoSegment(
                        start_frame_id=start_frame_id,
                        end_frame_id=end_frame_id,
                        class_id=None,
                        class_name=chapter.get('name', 'Unknown'),
                        segment_type='SexAct',
                        position_short_name=chapter.get('position_short', ''),
                        position_long_name=chapter.get('position_long', chapter.get('name', ''))
                    )
                    self.video_chapters.append(segment)
                except Exception as chapter_e:
                    self.logger.warning(f"Error converting chapter to VideoSegment: {chapter_e}")

            self.video_chapters.sort(key=lambda c: c.start_frame_id)
            self.logger.debug(f"Synced {len(self.video_chapters)} chapters from funscript object")
        except Exception as e:
            self.logger.error(f"Error syncing chapters from funscript: {e}", exc_info=True)

    def get_actions(self, axis: str) -> List[dict]:
        if self.funscript:
            if axis == 'primary':
                return self.funscript.primary_actions
            elif axis == 'secondary':
                return self.funscript.secondary_actions
        return []

    def _get_default_funscript_stats(self) -> Dict:
        return {
            "source_type": "N/A", "path": "N/A", "num_points": 0,
            "duration_scripted_s": 0.0, "avg_speed_pos_per_s": 0.0,
            "avg_intensity_percent": 0.0, "min_pos": -1, "max_pos": -1,
            "avg_interval_ms": 0.0, "min_interval_ms": -1, "max_interval_ms": -1,
            "total_travel_dist": 0, "num_strokes": 0
        }

    def _get_target_funscript_object_and_axis(self, timeline_num: int) -> Tuple[Optional[object], Optional[str]]:
        """Returns the funscript object and axis name ('primary' or 'secondary')."""
        if self.funscript:
            if timeline_num == 1:
                return self.funscript, 'primary'
            elif timeline_num == 2:
                return self.funscript, 'secondary'
        return None, None

    def _get_undo_manager(self, timeline_num: int) -> Optional[object]:  # Actually UndoRedoManager
        if timeline_num == 1: return self.undo_manager_t1
        if timeline_num == 2: return self.undo_manager_t2
        self.logger.warning(f"Requested undo manager for invalid timeline_num: {timeline_num}")
        return None

    def _check_chapter_overlap(self, start_frame: int, end_frame: int,
                               existing_chapter_id: Optional[str] = None) -> bool:
        """Checks if the given frame range overlaps with any existing chapters.
           Overlap is defined as sharing one or more frames. [s,e] includes s and e.
        """
        for chapter in self.video_chapters:
            if existing_chapter_id and chapter.unique_id == existing_chapter_id:
                continue  # Skip self when checking for an update

            # Overlap if max(start_frame, chapter.start_frame_id) <= min(end_frame, chapter.end_frame_id)
            if max(start_frame, chapter.start_frame_id) <= min(end_frame, chapter.end_frame_id):
                self.logger.warning(
                    f"Overlap detected: Proposed [{start_frame}-{end_frame}] with existing '{chapter.unique_id}' [{chapter.start_frame_id}-{chapter.end_frame_id}]")
                return True
        return False

    def _repair_overlapping_chapters(self):
        """Repair overlapping chapters from old projects before exclusive endTime fix.

        Adjusts adjacent chapters to have proper boundaries:
        - Chapter N end_frame_id should be < Chapter N+1 start_frame_id
        - Or they should be adjacent (end + 1 = start)
        """
        if len(self.video_chapters) <= 1:
            return  # Nothing to repair

        # Sort chapters by start frame
        self.video_chapters.sort(key=lambda ch: ch.start_frame_id)

        repaired_count = 0
        for i in range(len(self.video_chapters) - 1):
            curr_chapter = self.video_chapters[i]
            next_chapter = self.video_chapters[i + 1]

            # Check if chapters overlap (share frames)
            if curr_chapter.end_frame_id >= next_chapter.start_frame_id:
                # Fix: Make them adjacent by adjusting current chapter's end
                old_end = curr_chapter.end_frame_id
                curr_chapter.end_frame_id = next_chapter.start_frame_id - 1
                repaired_count += 1
                self.logger.info(
                    f"Repaired overlapping chapters: '{curr_chapter.position_short_name}' "
                    f"end adjusted from {old_end} to {curr_chapter.end_frame_id}"
                )

        if repaired_count > 0:
            self.logger.info(f"Repaired {repaired_count} overlapping chapter(s) from project load")

    def _auto_adjust_chapter_range(self, start_frame: int, end_frame: int) -> tuple[int, int]:
        """Auto-adjust chapter range to avoid overlaps, keeping as close as possible to original location."""
        if not self.video_chapters:
            return start_frame, end_frame
        
        chapters_sorted = sorted(self.video_chapters, key=lambda c: c.start_frame_id)
        original_duration = end_frame - start_frame
        
        # Find overlapping chapters
        overlapping_chapters = []
        for chapter in chapters_sorted:
            if max(start_frame, chapter.start_frame_id) <= min(end_frame, chapter.end_frame_id):
                overlapping_chapters.append(chapter)
        
        if not overlapping_chapters:
            return start_frame, end_frame  # No overlaps, keep original
        
        # Strategy 1: Try to fit right before the first overlapping chapter
        first_overlapping = min(overlapping_chapters, key=lambda c: c.start_frame_id)
        if first_overlapping.start_frame_id >= original_duration:
            adjusted_end = first_overlapping.start_frame_id - 1
            adjusted_start = adjusted_end - original_duration + 1
            if adjusted_start >= 0:
                return adjusted_start, adjusted_end
        
        # Strategy 2: Try to fit right after the last overlapping chapter  
        last_overlapping = max(overlapping_chapters, key=lambda c: c.end_frame_id)
        adjusted_start = last_overlapping.end_frame_id + 1
        adjusted_end = adjusted_start + original_duration - 1
        
        # Check if this position conflicts with any other chapters
        conflicts = False
        for chapter in chapters_sorted:
            if chapter in overlapping_chapters:
                continue  # Skip the chapters we're trying to avoid
            if max(adjusted_start, chapter.start_frame_id) <= min(adjusted_end, chapter.end_frame_id):
                conflicts = True
                break
        
        if not conflicts:
            return adjusted_start, adjusted_end
        
        # Strategy 3: Find the first available gap that can fit our duration
        for i in range(len(chapters_sorted) - 1):
            current_chapter = chapters_sorted[i]
            next_chapter = chapters_sorted[i + 1]
            
            gap_start = current_chapter.end_frame_id + 1
            gap_end = next_chapter.start_frame_id - 1
            gap_size = gap_end - gap_start + 1
            
            if gap_size >= original_duration:
                return gap_start, gap_start + original_duration - 1
        
        # Strategy 4: Place after the last chapter
        last_chapter = chapters_sorted[-1]
        final_start = last_chapter.end_frame_id + 1
        return final_start, final_start + original_duration - 1

    def _add_chapter_if_unique(self, chapter: 'VideoSegment') -> bool:
        """Add a chapter only if it doesn't duplicate an existing one. Returns True if added."""
        for existing_chapter in self.video_chapters:
            if (existing_chapter.start_frame_id == chapter.start_frame_id and 
                existing_chapter.end_frame_id == chapter.end_frame_id and
                existing_chapter.position_short_name == chapter.position_short_name):
                self.logger.debug(f"Skipping duplicate chapter at frames {chapter.start_frame_id}-{chapter.end_frame_id} ({chapter.position_short_name})")
                return False
        
        self.video_chapters.append(chapter)
        return True
