import imgui
import time
import numpy as np
import cv2
import queue

class AppGuiLogic:
    def __init__(self, app_logic, gui):
        self.app = app_logic
        self.gui = gui

    def _generate_funscript_preview_data(self, target_width, target_height, total_duration_s, actions):
        use_simplified_preview = self.app.app_settings.get("use_simplified_funscript_preview", False)

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
        colors = self.gui.colors
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


    def _handle_global_shortcuts(self):
        if not imgui.is_window_focused(imgui.FOCUS_ROOT_WINDOW) and not self.gui.is_any_timeline_hovered:
            return

        io = imgui.get_io()
        shift = io.key_shift
        ctrl = io.key_ctrl
        alt = io.key_alt

        if not self.gui.is_any_item_active():
            self._handle_save_project_shortcut(ctrl)
            self._handle_arrow_navigation(shift, ctrl)
            self._handle_zoom(ctrl)
            self._handle_misc_shortcuts(ctrl, shift)
            self._handle_funscript_generation()

        self._handle_playback_control(shift)
        self._handle_action_point_manipulation(shift, ctrl, alt)

    def _handle_save_project_shortcut(self, ctrl):
        if ctrl and imgui.is_key_pressed(imgui.KEY_S):
            self.app.queue_background_task(self.app.save_project)

    def _handle_arrow_navigation(self, shift, ctrl):
        if imgui.is_key_pressed(imgui.KEY_UP_ARROW):
            self._handle_up_down_arrows(shift, True)
        elif imgui.is_key_pressed(imgui.KEY_DOWN_ARROW):
            self._handle_up_down_arrows(shift, False)
        elif imgui.is_key_pressed(imgui.KEY_LEFT_ARROW):
            self._handle_left_right_arrows(shift, ctrl, False)
        elif imgui.is_key_pressed(imgui.KEY_RIGHT_ARROW):
            self._handle_left_right_arrows(shift, ctrl, True)

    def _handle_up_down_arrows(self, shift, is_up):
        delta = 10 if shift else 1
        if is_up:
            self.app.change_current_position(delta)
        else:
            self.app.change_current_position(-delta)

    def _handle_left_right_arrows(self, shift, ctrl, is_right):
        if is_right:
            if ctrl:
                self.app.go_to_next_action(shift)
            else:
                self.app.change_current_frame(1)
        else:
            if ctrl:
                self.app.go_to_previous_action(shift)
            else:
                self.app.change_current_frame(-1)

    def _handle_zoom(self, ctrl):
        if not ctrl:
            if imgui.is_key_pressed(imgui.KEY_PAGE_UP):
                self.app.zoom_in(0.5)
            elif imgui.is_key_pressed(imgui.KEY_PAGE_DOWN):
                self.app.zoom_out(0.5)

    def _handle_misc_shortcuts(self, ctrl, shift):
        if imgui.is_key_pressed(imgui.KEY_HOME):
            self.app.go_to_first_frame()
        elif imgui.is_key_pressed(imgui.KEY_END):
            self.app.go_to_last_frame()
        elif imgui.is_key_pressed(imgui.KEY_F) and not ctrl and not shift:
            self.app.toggle_funscript_points()
        elif imgui.is_key_pressed(imgui.KEY_V) and not ctrl and not shift:
            self.app.toggle_video_points()

    def _handle_funscript_generation(self):
        if imgui.is_key_pressed(imgui.KEY_G):
            self.app.generate_funscript()

    def _handle_playback_control(self, shift):
        if imgui.is_key_pressed(imgui.KEY_SPACE):
            if shift:
                self.app.toggle_playback_smooth()
            else:
                self.app.toggle_playback()

    def _handle_action_point_manipulation(self, shift, ctrl, alt):
        if imgui.is_key_pressed(imgui.KEY_ENTER):
            self._insert_or_delete_action_point(alt)
        elif imgui.is_key_pressed(imgui.KEY_DELETE):
            self.app.delete_action_at_current_frame()
        elif imgui.is_key_pressed(imgui.KEY_C):
            self.app.copy_points_in_selection()
        elif imgui.is_key_pressed(imgui.KEY_X):
            self.app.cut_points_in_selection()
        elif imgui.is_key_pressed(imgui.KEY_V) and ctrl:
            self.app.paste_points_at_current_frame()
        elif imgui.is_key_pressed(imgui.KEY_T):
            self.app.toggle_selection_mode()
        elif imgui.is_key_pressed(imgui.KEY_Q):
            self._move_action_point_position(shift, True)
        elif imgui.is_key_pressed(imgui.KEY_A):
            self._move_action_point_position(shift, False)
        elif imgui.is_key_pressed(imgui.KEY_W):
            self._move_action_point_time(shift, True)
        elif imgui.is_key_pressed(imgui.KEY_S) and not ctrl:
            self._move_action_point_time(shift, False)
        elif imgui.is_key_pressed(imgui.KEY_E):
            self._toggle_action_point_type()

    def _insert_or_delete_action_point(self, alt):
        if self.app.is_action_at_current_frame():
            self.app.delete_action_at_current_frame()
        else:
            self.app.add_action_at_current_frame(alt)

    def _move_action_point_position(self, shift, is_up):
        delta = 10 if shift else 1
        if is_up:
            self.app.move_action_position(delta)
        else:
            self.app.move_action_position(-delta)

    def _move_action_point_time(self, shift, is_forward):
        delta = 100 if shift else 10
        if is_forward:
            self.app.move_action_time(delta)
        else:
            self.app.move_action_time(-delta)

    def _toggle_action_point_type(self):
        self.app.toggle_action_type()
