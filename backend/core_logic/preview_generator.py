
import numpy as np
import cv2
import queue
import threading
import time

class PreviewGenerator:
    def __init__(self, app):
        self.app = app
        self.colors = self.app.app_state_ui.colors.AppGUIColors
        self.preview_task_queue = queue.Queue(maxsize=8)
        self.preview_results_queue = queue.Queue(maxsize=8)
        self.shutdown_event = threading.Event()
        self.preview_worker_threads = [
            threading.Thread(target=self._preview_generation_worker, daemon=True, name="PreviewWorker-1"),
            threading.Thread(target=self._preview_generation_worker, daemon=True, name="PreviewWorker-2")
        ]
        for t in self.preview_worker_threads:
            t.start()

    def _preview_generation_worker(self):
        """
        Runs in a background thread. Waits for tasks and processes them.
        """
        while not self.shutdown_event.is_set():
            try:
                task = self.preview_task_queue.get(timeout=0.1)
                task_type = task['type']

                if task_type == 'timeline':
                    image_data = self._generate_funscript_preview_data(
                        task['target_width'],
                        task['target_height'],
                        task['total_duration_s'],
                        task['actions']
                    )
                    self.preview_results_queue.put({'type': 'timeline', 'image_data': image_data})

                elif task_type == 'heatmap':
                    image_data = self._generate_heatmap_data(
                        task['target_width'],
                        task['target_height'],
                        task['total_duration_s'],
                        task['actions']
                    )
                    self.preview_results_queue.put({'type': 'heatmap', 'image_data': image_data})

                self.preview_task_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                self.app.logger.error(f"Error in preview generation worker: {e}", exc_info=True)

    def _generate_funscript_preview_data(self, target_width, target_height, total_duration_s, actions):
        """
        Performs the numpy/cv2 operations to create the timeline image.
        This is called by the worker thread.
        """
        use_simplified_preview = self.app.app_settings.get("use_simplified_funscript_preview", False)

        # Create background
        image_data = np.full((target_height, target_width, 4), (38, 31, 31, 255), dtype=np.uint8)
        center_y_px = target_height // 2
        cv2.line(image_data, (0, center_y_px), (target_width - 1, center_y_px), (77, 77, 77, 179), 1)

        if not actions or total_duration_s <= 0.001:
            return image_data

        if use_simplified_preview:
            if len(actions) < 2: return image_data

            min_vals = np.full(target_width, target_height, dtype=np.int32)
            max_vals = np.full(target_width, -1, dtype=np.int32)

            times_s = np.array([a['at'] for a in actions]) / 1000.0
            positions = np.array([a['pos'] for a in actions])
            x_coords = np.round((times_s / total_duration_s) * (target_width - 1)).astype(np.int32)
            y_coords = np.round((1.0 - positions / 100.0) * (target_height - 1)).astype(np.int32)

            for i in range(len(actions) - 1):
                x1, x2 = x_coords[i], x_coords[i+1]
                y1, y2 = y_coords[i], y_coords[i+1]

                if x1 == x2:
                    min_vals[x1] = min(min_vals[x1], y1, y2)
                    max_vals[x1] = max(max_vals[x1], y1, y2)
                else:
                    dx = x2 - x1
                    dy = y2 - y1
                    for x in range(x1, x2 + 1):
                        y = y1 + dy * (x - x1) / dx
                        y_int = int(round(y))
                        min_vals[x] = min(min_vals[x], y_int)
                        max_vals[x] = max(max_vals[x], y_int)

            min_points = []
            max_points_rev = []
            for x in range(target_width):
                if max_vals[x] != -1:
                    min_points.append([x, min_vals[x]])
                    max_points_rev.append([x, max_vals[x]])

            if not min_points: return image_data

            poly_points = np.array(min_points + max_points_rev[::-1], dtype=np.int32)

            overlay = image_data.copy()
            envelope_color_rgba = self.app.utility.get_speed_color_from_map(500)
            envelope_color_bgra = (int(envelope_color_rgba[2] * 255), int(envelope_color_rgba[1] * 255), int(envelope_color_rgba[0] * 255), 100)
            cv2.fillPoly(overlay, [poly_points], envelope_color_bgra)
            cv2.addWeighted(overlay, 0.5, image_data, 0.5, 0, image_data)

        else:
            if len(actions) > 1:
                ats = np.array([a['at'] for a in actions], dtype=np.float64) / 1000.0
                pos = np.array([a['pos'] for a in actions], dtype=np.float32) / 100.0
                x = np.clip(((ats / total_duration_s) * (target_width - 1)).astype(np.int32), 0, target_width - 1)
                y = np.clip(((1.0 - pos) * target_height).astype(np.int32), 0, target_height - 1)
                dt = np.diff(ats)
                dpos = np.abs(np.diff(pos * 100.0))
                speeds = np.divide(dpos, dt, out=np.zeros_like(dpos), where=dt > 1e-6)
                colors_u8 = self.app.utility.get_speed_colors_vectorized_u8(speeds)
                for i in range(len(speeds)):
                    if x[i] == x[i+1] and y[i] == y[i+1]:
                        continue
                    c = colors_u8[i]
                    cv2.line(image_data, (int(x[i]), int(y[i])), (int(x[i+1]), int(y[i+1])), (int(c[2]), int(c[1]), int(c[0]), int(c[3])), 1)

        return image_data

    def _generate_heatmap_data(self, target_width, target_height, total_duration_s, actions):
        """
        Performs the numpy/cv2 operations to create the heatmap image.
        This is called by the worker thread.
        """
        colors = self.colors
        image_data = np.full((target_height, target_width, 4), (colors.HEATMAP_BACKGROUND), dtype=np.uint8)

        if len(actions) > 1 and total_duration_s > 0.001:
            ats = np.array([a['at'] for a in actions], dtype=np.float64) / 1000.0
            poss = np.array([a['pos'] for a in actions], dtype=np.float32)
            x_coords = ((ats / total_duration_s) * (target_width - 1)).astype(np.int32)
            x_coords = np.clip(x_coords, 0, target_width - 1)
            dt = np.diff(ats)
            dpos = np.abs(np.diff(poss))
            speeds = np.divide(dpos, dt, out=np.zeros_like(dpos), where=dt > 1e-6)
            colors_u8 = self.app.utility.get_speed_colors_vectorized_u8(speeds)
            cols = np.arange(target_width, dtype=np.int32)
            seg_idx_for_col = np.searchsorted(x_coords, cols, side='right') - 1
            valid_mask = seg_idx_for_col >= 0
            seg_idx_for_col = np.clip(seg_idx_for_col, 0, len(speeds) - 1)
            col_colors = np.zeros((target_width, 4), dtype=np.uint8)
            if np.any(valid_mask):
                col_colors[valid_mask] = colors_u8[seg_idx_for_col[valid_mask]]
                col_colors[valid_mask, 3] = 255
            if np.any(~valid_mask):
                col_colors[~valid_mask, 3] = 0
            image_data[:] = col_colors[np.newaxis, :, :]

        return image_data

    def submit_timeline_task(self, target_width, target_height, total_duration_s, actions):
        task = {
            'type': 'timeline',
            'target_width': target_width,
            'target_height': target_height,
            'total_duration_s': total_duration_s,
            'actions': actions
        }
        try:
            self.preview_task_queue.put_nowait(task)
        except queue.Full:
            pass

    def submit_heatmap_task(self, target_width, target_height, total_duration_s, actions):
        task = {
            'type': 'heatmap',
            'target_width': target_width,
            'target_height': target_height,
            'total_duration_s': total_duration_s,
            'actions': actions
        }
        try:
            self.preview_task_queue.put_nowait(task)
        except queue.Full:
            pass

    def get_preview_results(self):
        results = []
        try:
            while not self.preview_results_queue.empty():
                results.append(self.preview_results_queue.get_nowait())
        except queue.Empty:
            pass
        return results

    def shutdown(self):
        self.shutdown_event.set()
        for t in self.preview_worker_threads:
            t.join()
