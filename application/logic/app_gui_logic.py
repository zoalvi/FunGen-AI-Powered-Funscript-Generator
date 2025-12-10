import imgui
import time

class AppGuiLogic:
    def __init__(self, app_logic, gui):
        self.app = app_logic
        self.gui = gui

    def render_funscript_timeline_preview(self, total_duration_s: float, graph_height: int):
        app_state = self.app.app_state_ui
        colors = self.gui.colors
        style = imgui.get_style()

        current_bar_width_float = imgui.get_content_region_available()[0]
        current_bar_width_int = int(round(current_bar_width_float))

        if current_bar_width_int <= 0 or graph_height <= 0 or not self.gui.funscript_preview_texture_id:
            imgui.dummy(current_bar_width_float if current_bar_width_float > 0 else 1, graph_height + 5)
            return

        current_action_count = len(self.app.funscript_processor.get_actions('primary'))
        is_live_tracking = self.app.processor and self.app.processor.tracker and self.app.processor.tracker.tracking_active

        full_redraw_needed = (app_state.funscript_preview_dirty
            or current_bar_width_int != app_state.last_funscript_preview_bar_width
            or abs(total_duration_s - app_state.last_funscript_preview_duration_s) > 0.01)

        incremental_update_needed = current_action_count != self.gui.last_submitted_action_count_timeline

        needs_regen = (full_redraw_needed
            or (incremental_update_needed
            and (not is_live_tracking
            or (time.time() - self.gui.last_preview_update_time_timeline >= self.gui.preview_update_interval_seconds))))

        if needs_regen:
            actions_copy = self.app.funscript_processor.get_actions('primary').copy()
            task = {
                'type': 'timeline',
                'target_width': current_bar_width_int,
                'target_height': graph_height,
                'total_duration_s': total_duration_s,
                'actions': actions_copy
            }
            try:
                self.gui.preview_task_queue.put_nowait(task)
            except queue.Full:
                pass

            app_state.funscript_preview_dirty = False
            app_state.last_funscript_preview_bar_width = current_bar_width_int
            app_state.last_funscript_preview_duration_s = total_duration_s
            self.gui.last_submitted_action_count_timeline = current_action_count
            if is_live_tracking and incremental_update_needed:
                self.gui.last_preview_update_time_timeline = time.time()

        imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + 20)
        canvas_p1_x = imgui.get_cursor_screen_pos()[0]
        canvas_p1_y_offset = imgui.get_cursor_screen_pos()[1]

        imgui.image(self.gui.funscript_preview_texture_id, current_bar_width_float, graph_height, uv0=(0, 0), uv1=(1, 1))

        if imgui.is_item_hovered():
            mouse_x = imgui.get_mouse_pos()[0] - canvas_p1_x
            normalized_pos = np.clip(mouse_x / current_bar_width_float, 0.0, 1.0)
            if self.app.processor and self.app.processor.video_info:
                total_frames = self.app.processor.video_info.get('total_frames', 0)
                if total_frames > 0:
                    if (imgui.is_mouse_dragging(0) or imgui.is_mouse_down(0)):
                        click_time_s = normalized_pos * total_duration_s
                        fps = self.app.processor.fps if self.app.processor and self.app.processor.fps > 0 else 30.0
                        seek_frame = int(round(click_time_s * fps))
                        seek_frame = max(0, min(seek_frame, total_frames - 1))
                        self.app.event_handlers.handle_seek_bar_drag(seek_frame)
                    else:
                        total_duration = total_duration_s
                        if total_duration > 0:
                            hover_time_s = normalized_pos * total_duration
                            fps = self.app.processor.fps if self.app.processor and self.app.processor.fps > 0 else 30.0
                            hover_frame = int(round(hover_time_s * fps))
                            hover_frame = max(0, min(hover_frame, total_frames - 1))
                            if not hasattr(self.gui, '_preview_hover_start_time'):
                                self.gui._preview_hover_start_time = None
                                self.gui._preview_hover_pos = None
                                self.gui._preview_cached_tooltip_data = None
                                self.gui._preview_cached_pos = None
                            position_tolerance = 0.0001
                            position_changed = (self.gui._preview_hover_pos is None or abs(self.gui._preview_hover_pos - normalized_pos) > position_tolerance)
                            if position_changed:
                                self.gui._preview_hover_pos = normalized_pos
                                self.gui._preview_hover_start_time = time.time()
                                self.gui._preview_cached_tooltip_data = None
                                self.gui._preview_cached_pos = None
                            hover_duration = time.time() - self.gui._preview_hover_start_time if self.gui._preview_hover_start_time else 0
                            enhanced_preview_enabled = self.app.app_settings.get("enable_enhanced_funscript_preview", True)
                            if enhanced_preview_enabled:
                                show_video_frame = hover_duration > 0.3
                                if (self.gui._preview_cached_tooltip_data is not None and self.gui._preview_cached_pos is not None and abs(self.gui._preview_cached_pos - normalized_pos) <= position_tolerance):
                                    cached_frame_data = self.gui._preview_cached_tooltip_data.get('frame_data')
                                    if show_video_frame and (cached_frame_data is None or cached_frame_data.size == 0):
                                        if not hasattr(self.gui, '_preview_frame_fetch_pending'):
                                            self.gui._preview_frame_fetch_pending = False
                                        if not self.gui._preview_frame_fetch_pending:
                                            self.gui._preview_frame_fetch_pending = True
                                            self.gui._preview_cached_tooltip_data['frame_loading'] = True
                                            cached_hover_frame = self.gui._preview_cached_tooltip_data.get('hover_frame', hover_frame)
                                            def fetch_frame_async():
                                                try:
                                                    frame_data, actual_frame = self.gui._get_frame_direct_cv2(cached_hover_frame)
                                                    if frame_data is not None and frame_data.size > 0:
                                                        self.gui._preview_cached_tooltip_data['frame_data'] = frame_data
                                                        self.gui._preview_cached_tooltip_data['actual_frame'] = actual_frame
                                                        self.gui._preview_cached_tooltip_data['frame_loading'] = False
                                                except Exception:
                                                    self.gui._preview_cached_tooltip_data['frame_loading'] = False
                                                finally:
                                                    self.gui._preview_frame_fetch_pending = False
                                            import threading
                                            threading.Thread(target=fetch_frame_async, daemon=True).start()
                                    self.gui._render_instant_enhanced_tooltip(self.gui._preview_cached_tooltip_data, show_video_frame)
                                else:
                                    try:
                                        tooltip_data = self.gui._generate_instant_tooltip_data(hover_time_s, hover_frame, total_duration, normalized_pos, show_video_frame)
                                        self.gui._preview_cached_tooltip_data = tooltip_data
                                        self.gui._preview_cached_pos = normalized_pos
                                        if show_video_frame and tooltip_data.get('frame_loading', False):
                                            if not hasattr(self.gui, '_preview_frame_fetch_pending'):
                                                self.gui._preview_frame_fetch_pending = False
                                            if not self.gui._preview_frame_fetch_pending:
                                                self.gui._preview_frame_fetch_pending = True
                                                def fetch_frame_async():
                                                    try:
                                                        frame_data, actual_frame = self.gui._get_frame_direct_cv2(hover_frame)
                                                        if frame_data is not None and frame_data.size > 0:
                                                            self.gui._preview_cached_tooltip_data['frame_data'] = frame_data
                                                            self.gui._preview_cached_tooltip_data['actual_frame'] = actual_frame
                                                            self.gui._preview_cached_tooltip_data['frame_loading'] = False
                                                    except Exception:
                                                        self.gui._preview_cached_tooltip_data['frame_loading'] = False
                                                    finally:
                                                        self.gui._preview_frame_fetch_pending = False
                                                import threading
                                                threading.Thread(target=fetch_frame_async, daemon=True).start()
                                        self.gui._render_instant_enhanced_tooltip(tooltip_data, show_video_frame)
                                    except Exception as e:
                                        imgui.set_tooltip(f"{self.gui._format_time(self.app, hover_time_s)} / {self.gui._format_time(self.app, total_duration)}")
                            else:
                                imgui.set_tooltip(f"{self.gui._format_time(self.app, hover_time_s)} / {self.gui._format_time(self.app, total_duration)}")
        else:
            if hasattr(self.gui, '_preview_hover_start_time'):
                self.gui._preview_hover_start_time = None
                self.gui._preview_hover_pos = None
                self.gui._preview_frame_fetch_pending = False

        if self.app.file_manager.video_path and self.app.processor and self.app.processor.video_info and self.app.processor.current_frame_index >= 0:
            total_frames = self.app.processor.video_info.get('total_frames', 0)
            if total_frames > 0:
                fps = self.app.processor.fps if self.app.processor.fps > 0 else 30.0
                current_time_s = self.app.processor.current_frame_index / fps
                normalized_pos = current_time_s / total_duration_s if total_duration_s > 0 else 0
                marker_x = (canvas_p1_x + style.frame_padding[0]) + (normalized_pos * (current_bar_width_float - style.frame_padding[0] * 2))
                marker_color = imgui.get_color_u32_rgba(*colors.MARKER)
                draw_list_marker = imgui.get_window_draw_list()
                triangle_p1 = (marker_x - 5, canvas_p1_y_offset)
                triangle_p2 = (marker_x + 5, canvas_p1_y_offset)
                triangle_p3 = (marker_x, canvas_p1_y_offset + 5)
                draw_list_marker.add_triangle_filled(triangle_p1[0], triangle_p1[1], triangle_p2[0], triangle_p2[1], triangle_p3[0], triangle_p3[1], marker_color)
                draw_list_marker.add_line(marker_x, canvas_p1_y_offset, marker_x, canvas_p1_y_offset + graph_height, marker_color, 1.0)
                current_frame = self.app.processor.current_frame_index
                current_time_s = self.app.processor.current_frame_index / self.app.processor.video_info.get('fps', 30.0)
                text = f"{self.gui._format_time(self.app, current_time_s)} ({current_frame})"
                text_size = imgui.calc_text_size(text)
                text_pos_x = marker_x - text_size[0] / 2
                if text_pos_x < canvas_p1_x:
                    text_pos_x = canvas_p1_x
                if text_pos_x + text_size[0] > canvas_p1_x + current_bar_width_float:
                    text_pos_x = canvas_p1_x + current_bar_width_float - text_size[0]
                text_pos = (text_pos_x, canvas_p1_y_offset - text_size[1] - 2)
                draw_list_marker.add_text(text_pos[0], text_pos[1], imgui.get_color_u32_rgba(*colors.WHITE), text)

    def render_funscript_heatmap_preview(self, total_video_duration_s: float, bar_width_float: float, bar_height_float: float):
        app_state = self.app.app_state_ui
        current_bar_width_int = int(round(bar_width_float))
        if current_bar_width_int <= 0 or app_state.heatmap_texture_fixed_height <= 0 or not self.gui.heatmap_texture_id:
            imgui.dummy(bar_width_float, bar_height_float)
            return

        current_action_count = len(self.app.funscript_processor.get_actions('primary'))
        is_live_tracking = self.app.processor and self.app.processor.tracker and self.app.processor.tracker.tracking_active

        full_redraw_needed = (
            app_state.heatmap_dirty
            or current_bar_width_int != app_state.last_heatmap_bar_width
            or abs(total_video_duration_s - app_state.last_heatmap_video_duration_s) > 0.01)

        incremental_update_needed = current_action_count != self.gui.last_submitted_action_count_heatmap

        needs_regen = full_redraw_needed or (incremental_update_needed and (not is_live_tracking or (time.time() - self.gui.last_preview_update_time_heatmap >= self.gui.preview_update_interval_seconds)))

        if needs_regen:
            actions_copy = self.app.funscript_processor.get_actions('primary').copy()
            task = {
                'type': 'heatmap',
                'target_width': current_bar_width_int,
                'target_height': app_state.heatmap_texture_fixed_height,
                'total_duration_s': total_video_duration_s,
                'actions': actions_copy
            }
            try:
                self.gui.preview_task_queue.put_nowait(task)
            except queue.Full:
                pass

            app_state.heatmap_dirty = False
            app_state.last_heatmap_bar_width = current_bar_width_int
            app_state.last_heatmap_video_duration_s = total_video_duration_s
            self.gui.last_submitted_action_count_heatmap = current_action_count
            if is_live_tracking and incremental_update_needed:
                self.gui.last_preview_update_time_heatmap = time.time()

        imgui.image(self.gui.heatmap_texture_id, bar_width_float, bar_height_float, uv0=(0, 0), uv1=(1, 1))

    def _handle_global_shortcuts(self):
        if not self.app.shortcut_manager.should_handle_shortcuts():
            return

        io = imgui.get_io()
        app_state = self.app.app_state_ui

        current_shortcuts = self.app.app_settings.get("funscript_editor_shortcuts", {})
        fs_proc = self.app.funscript_processor
        video_loaded = self.app.processor and self.app.processor.video_info and self.app.processor.total_frames > 0

        def check_and_run_shortcut(shortcut_name, action_func, *action_args):
            shortcut_str = current_shortcuts.get(shortcut_name)
            if not shortcut_str:
                return False

            map_result = self.app._map_shortcut_to_glfw_key(shortcut_str)
            if not map_result:
                return False

            mapped_key, mapped_mods_from_string = map_result
            key_pressed = imgui.is_key_pressed(mapped_key)

            if key_pressed:
                mods_match = (mapped_mods_from_string['ctrl'] == io.key_ctrl
                    and mapped_mods_from_string['alt'] == io.key_alt
                    and mapped_mods_from_string['shift'] == io.key_shift
                    and mapped_mods_from_string['super'] == io.key_super)
                if mods_match:
                    action_func(*action_args)
                    return True
            return False

        def check_key_held(shortcut_name):
            shortcut_str = current_shortcuts.get(shortcut_name)
            if not shortcut_str:
                return False
            map_result = self.app._map_shortcut_to_glfw_key(shortcut_str)
            if not map_result:
                return False
            mapped_key, mapped_mods_from_string = map_result
            return (imgui.is_key_down(mapped_key) and
                   mapped_mods_from_string['ctrl'] == io.key_ctrl and
                   mapped_mods_from_string['alt'] == io.key_alt and
                   mapped_mods_from_string['shift'] == io.key_shift and
                   mapped_mods_from_string['super'] == io.key_super)

        f1_map = self.app._map_shortcut_to_glfw_key("F1")
        if f1_map:
            f1_key, f1_mods = f1_map
            if (imgui.is_key_pressed(f1_key) and
                not io.key_ctrl and not io.key_alt and not io.key_shift and not io.key_super):
                self.gui.keyboard_shortcuts_dialog.toggle()
                return

        if check_and_run_shortcut("save_project", self.gui._handle_save_project_shortcut):
            pass
        elif check_and_run_shortcut("open_project", self.gui._handle_open_project_shortcut):
            pass
        elif check_and_run_shortcut("undo_timeline1", fs_proc.perform_undo_redo, 1, 'undo'):
            pass
        elif check_and_run_shortcut("redo_timeline1", fs_proc.perform_undo_redo, 1, 'redo'):
            pass
        elif self.app.app_state_ui.show_funscript_interactive_timeline2 and (
            check_and_run_shortcut("undo_timeline2", fs_proc.perform_undo_redo, 2, 'undo')
            or check_and_run_shortcut("redo_timeline2", fs_proc.perform_undo_redo, 2, 'redo')
        ): pass
        elif check_and_run_shortcut("toggle_playback", self.app.event_handlers.handle_playback_control, "play_pause"):
            pass
        elif check_and_run_shortcut("jump_to_next_point", self.app.event_handlers.handle_jump_to_point, 'next'):
            pass
        elif check_and_run_shortcut("jump_to_next_point_alt", self.app.event_handlers.handle_jump_to_point, 'next'):
            pass
        elif check_and_run_shortcut("jump_to_prev_point", self.app.event_handlers.handle_jump_to_point, 'prev'):
            pass
        elif check_and_run_shortcut("jump_to_prev_point_alt", self.app.event_handlers.handle_jump_to_point, 'prev'):
            pass
        elif video_loaded and check_and_run_shortcut("jump_to_start", self.gui._handle_jump_to_start_shortcut):
            pass
        elif video_loaded and check_and_run_shortcut("jump_to_end", self.gui._handle_jump_to_end_shortcut):
            pass
        elif check_and_run_shortcut("zoom_in_timeline", self.gui._handle_zoom_in_timeline_shortcut):
            pass
        elif check_and_run_shortcut("zoom_out_timeline", self.gui._handle_zoom_out_timeline_shortcut):
            pass
        elif check_and_run_shortcut("toggle_video_display", self.gui._handle_toggle_video_display_shortcut):
            pass
        elif check_and_run_shortcut("toggle_timeline2", self.gui._handle_toggle_timeline2_shortcut):
            pass
        elif check_and_run_shortcut("toggle_gauge_window", self.gui._handle_toggle_gauge_window_shortcut):
            pass
        elif check_and_run_shortcut("toggle_3d_simulator", self.gui._handle_toggle_3d_simulator_shortcut):
            pass
        elif check_and_run_shortcut("toggle_movement_bar", self.gui._handle_toggle_movement_bar_shortcut):
            pass
        elif check_and_run_shortcut("toggle_chapter_list", self.gui._handle_toggle_chapter_list_shortcut):
            pass
        elif check_and_run_shortcut("toggle_heatmap", self.gui._handle_toggle_heatmap_shortcut):
            pass
        elif check_and_run_shortcut("toggle_funscript_preview", self.gui._handle_toggle_funscript_preview_shortcut):
            pass
        elif check_and_run_shortcut("toggle_video_feed", self.gui._handle_toggle_video_feed_shortcut):
            pass
        elif check_and_run_shortcut("toggle_waveform", self.gui._handle_toggle_waveform_shortcut):
            pass
        elif check_and_run_shortcut("reset_timeline_view", self.gui._handle_reset_timeline_view_shortcut):
            pass
        elif check_and_run_shortcut("set_chapter_start", self.gui._handle_set_chapter_start_shortcut):
            pass
        elif check_and_run_shortcut("set_chapter_end", self.gui._handle_set_chapter_end_shortcut):
            pass
        elif video_loaded and check_and_run_shortcut("add_point_0", self.gui._handle_add_point_at_value, 0):
            pass
        elif video_loaded and check_and_run_shortcut("add_point_10", self.gui._handle_add_point_at_value, 10):
            pass
        elif video_loaded and check_and_run_shortcut("add_point_20", self.gui._handle_add_point_at_value, 20):
            pass
        elif video_loaded and check_and_run_shortcut("add_point_30", self.gui._handle_add_point_at_value, 30):
            pass
        elif video_loaded and check_and_run_shortcut("add_point_40", self.gui._handle_add_point_at_value, 40):
            pass
        elif video_loaded and check_and_run_shortcut("add_point_50", self.gui._handle_add_point_at_value, 50):
            pass
        elif video_loaded and check_and_run_shortcut("add_point_60", self.gui._handle_add_point_at_value, 60):
            pass
        elif video_loaded and check_and_run_shortcut("add_point_70", self.gui._handle_add_point_at_value, 70):
            pass
        elif video_loaded and check_and_run_shortcut("add_point_80", self.gui._handle_add_point_at_value, 80):
            pass
        elif video_loaded and check_and_run_shortcut("add_point_90", self.gui._handle_add_point_at_value, 90):
            pass
        elif video_loaded and check_and_run_shortcut("add_point_100", self.gui._handle_add_point_at_value, 100):
            pass

        if video_loaded:
            self.gui._handle_arrow_navigation()