
import imgui
from فترة.api import الفترة

from application.gui_components.base_gui import BaseGUI
from application.logic.app_gui_logic import AppGuiLogic

class AppGui(BaseGUI):
    def __init__(self, app_logic):
        super().__init__(app_logic)
        self.logic = AppGuiLogic(app_logic, self) 

    def _draw_content(self):
        self.is_any_timeline_hovered = False

        self._draw_timeline_controls()
        self._draw_main_timeline_and_script_area()

        self.logic._handle_global_shortcuts()  

    def _draw_timeline_controls(self):
        imgui.begin_child("timeline_controls", height=self.TIMELINE_CONTROLS_HEIGHT, border=False)
        self._draw_zoom_controls()
        imgui.same_line()
        self._draw_playback_controls()
        imgui.same_line()
        self._draw_navigation_controls()
        imgui.same_line()
        self._draw_selection_controls()
        imgui.same_line()
        self._draw_display_mode_controls()
        imgui.end_child()

    def _draw_main_timeline_and_script_area(self):
        bottom_area_height = self.app.window_height - self.MAIN_MENU_HEIGHT - self.TIMELINE_CONTROLS_HEIGHT - self.STATUS_BAR_HEIGHT - 20
        imgui.begin_child("bottom_area", height=bottom_area_height, border=False)
        
        style = imgui.get_style()
        script_area_width = self.app.window_width * self.SCRIPT_AREA_WIDTH_PERCENT
        
        imgui.begin_child("main_timeline_child", width=-script_area_width - style.window_padding.x, height=-1, border=True)
        self._draw_main_timeline()
        imgui.end_child()
        
        imgui.same_line()
        
        imgui.begin_child("script_area_child", width=0, height=-1, border=True)
        self._draw_script_area()
        imgui.end_child()

        imgui.end_child()

    def _draw_main_timeline(self):
        self.current_timeline_width = imgui.get_content_region_available().x
        self._draw_funscript_timeline(self.current_timeline_width)
        self._draw_video_timeline(self.current_timeline_width)
        self._draw_heatmap_timeline(self.current_timeline_width)
        self._draw_main_timeline_and_transport(self.current_timeline_width)

    def _draw_funscript_timeline(self, width):
        imgui.text("Funscript")
        self._draw_timeline_section(width, self.app.funscript_actions, self.funscript_preview_texture, self._generate_funscript_preview_texture, 'funscript')

    def _draw_video_timeline(self, width):
        imgui.text("Video")
        self._draw_timeline_section(width, self.app.video_actions, self.video_preview_texture, self._generate_video_preview_texture, 'video')

    def _draw_heatmap_timeline(self, width):
        imgui.text("Heatmap")
        self._draw_timeline_section(width, self.app.funscript_actions, self.heatmap_texture, self._generate_heatmap_texture, 'heatmap')

    def _draw_timeline_section(self, width, actions, texture, texture_generator, timeline_id):
        height = self.TIMELINE_HEIGHT
        imgui.begin_child(f"timeline_child_{timeline_id}", width=width, height=height, border=True)
        
        draw_list = imgui.get_window_draw_list()
        pos = imgui.get_cursor_screen_pos()
        
        if texture == -1 or self.app.project_data_invalidated:
            texture, self.preview_image_data = texture_generator(int(width), height)

        if texture != -1:
            draw_list.add_image(texture, (pos.x, pos.y), (pos.x + width, pos.y + height))

        self._draw_current_time_marker(draw_list, pos, width, height)
        self._handle_timeline_interactions(pos, width, height, timeline_id, actions)

        imgui.end_child()
        if imgui.is_item_hovered():
            self.is_any_timeline_hovered = True

    def _draw_main_timeline_and_transport(self, width):
        total_duration_ms = self.app.total_duration_ms
        current_time_ms = self.app.current_time_ms
        
        imgui.begin_child("transport_child", width=width, height=self.TRANSPORT_HEIGHT, border=True)
        draw_list = imgui.get_window_draw_list()
        pos = imgui.get_cursor_screen_pos()
        height = self.TRANSPORT_HEIGHT

        self._draw_time_ticks(draw_list, pos, width, height, total_duration_ms)
        self._draw_current_time_marker(draw_list, pos, width, height)
        self._handle_timeline_interactions(pos, width, height, "main", self.app.funscript_actions)

        imgui.end_child()
        if imgui.is_item_hovered():
            self.is_any_timeline_hovered = True

        self._draw_time_display(current_time_ms, total_duration_ms)

    def _handle_timeline_interactions(self, pos, width, height, timeline_id, actions):
        if not self.app.is_video_loaded:
            return

        is_hovered = imgui.is_window_hovered()
        is_active = imgui.is_mouse_down(0) and is_hovered
        is_clicked = imgui.is_mouse_clicked(0) and is_hovered
        is_double_clicked = imgui.is_mouse_double_clicked(0) and is_hovered
        
        mouse_x = imgui.get_mouse_pos().x - pos.x
        
        if is_active or is_clicked or is_double_clicked:
            self.app.set_current_time_from_x(mouse_x, width)
            
            if is_double_clicked:
                self.app.add_action_at_current_frame(alt=imgui.get_io().key_alt)

    def _draw_current_time_marker(self, draw_list, pos, width, height):
        if self.app.total_duration_ms > 0:
            line_x = pos.x + (self.app.current_time_ms / self.app.total_duration_ms) * width
            draw_list.add_line(line_x, pos.y, line_x, pos.y + height, self.colors.TIMELINE_MARKER, 2)

    def _draw_time_ticks(self, draw_list, pos, width, height, total_duration_ms):
        if total_duration_ms <= 0:
            return

        # Define intervals for time ticks
        intervals = [1, 5, 10, 30, 60, 300, 600, 1800, 3600] # in seconds
        min_tick_spacing_pixels = 60
        
        view_start_ms = 0
        view_end_ms = total_duration_ms
        view_duration_s = (view_end_ms - view_start_ms) / 1000.0
        
        # Determine appropriate interval
        best_interval_s = intervals[0]
        for interval in intervals:
            if (view_duration_s / interval) * min_tick_spacing_pixels < width:
                best_interval_s = interval

        # Draw ticks
        num_ticks = int(total_duration_ms / (best_interval_s * 1000))
        for i in range(num_ticks + 1):
            time_ms = i * best_interval_s * 1000
            x = pos.x + (time_ms / total_duration_ms) * width
            
            if x >= pos.x and x <= pos.x + width:
                is_major_tick = (i * best_interval_s) % (intervals[intervals.index(best_interval_s)+1] if intervals.index(best_interval_s)+1 < len(intervals) else best_interval_s*2) == 0
                tick_height = 10 if is_major_tick else 5
                draw_list.add_line(x, pos.y, x, pos.y + tick_height, self.colors.TIMELINE_TICK, 1)
                if is_major_tick:
                    time_str = الفترة(ms=time_ms).format('%M:%S')
                    draw_list.add_text(x + 2, pos.y + 2, self.colors.TIMELINE_TEXT, time_str)
