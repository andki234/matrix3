# interstate75.py (threadless Tk version)

import os, sys, time
import tkinter as tk

DISPLAY_INTERSTATE75_64X32 = {"width": 64, "height": 32}

def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v

class _SimulatorWindow:
    def __init__(self, width, height, scale=12, title="Interstate 75 Simulator"):
        self.width, self.height, self.scale = width, height, int(scale)
        self.root = tk.Tk()
        self.root.title(title)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Escape>", lambda e: self._on_close())
        self._drag_start = None

        self.canvas = tk.Canvas(
            self.root,
            width=self.width * self.scale,
            height=self.height * self.scale,
            highlightthickness=0
        )
        self.canvas.pack()

        # Allow dragging the window from anywhere on the canvas.
        self.root.bind("<ButtonPress-1>", self._on_drag_start)
        self.root.bind("<B1-Motion>", self._on_drag_motion)
        self.root.bind("<ButtonRelease-1>", self._on_drag_end)
        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)

        self._rects = []
        for y in range(self.height):
            row = []
            for x in range(self.width):
                x0 = x * self.scale; y0 = y * self.scale
                rect = self.canvas.create_rectangle(
                    x0, y0, x0 + self.scale, y0 + self.scale,
                    outline="", fill="#000000"
                )
                row.append(rect)
            self._rects.append(row)
        self._closed = False

    def _on_close(self):
        self._closed = True
        try:
            self.root.destroy()
        except Exception:
            pass

    def _on_drag_start(self, event):
        self._drag_start = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _on_drag_motion(self, event):
        if not self._drag_start:
            return
        start_x, start_y, win_x, win_y = self._drag_start
        dx = event.x_root - start_x
        dy = event.y_root - start_y
        self.root.geometry(f"+{win_x + dx}+{win_y + dy}")

    def _on_drag_end(self, event):
        self._drag_start = None

    def is_closed(self):
        return self._closed

    def set_pixel(self, x, y, r, g, b):
        if 0 <= x < self.width and 0 <= y < self.height:
            r = _clamp(int(r), 0, 255); g = _clamp(int(g), 0, 255); b = _clamp(int(b), 0, 255)
            self.canvas.itemconfig(self._rects[y][x], fill=f"#{r:02x}{g:02x}{b:02x}")

    def clear(self):
        black = "#000000"
        for y in range(self.height):
            for x in range(self.width):
                self.canvas.itemconfig(self._rects[y][x], fill=black)

# Font data from Pimoroni GitHub - bitmap8 font (8x5 characters)
FONT8_DATA = {
    'height': 8,
    'max_width': 5,
    'widths': [
        3, 1, 3, 5, 4, 4, 4, 1, 3, 3, 3, 3, 2, 3, 2, 4,
        4, 3, 4, 4, 4, 4, 4, 4, 4, 4, 1, 2, 3, 3, 3, 4,
        4, 4, 4, 4, 4, 4, 4, 4, 4, 3, 4, 4, 4, 5, 4, 4,
        4, 4, 4, 4, 5, 4, 4, 5, 4, 4, 4, 2, 4, 2, 3, 3,
        1, 4, 4, 4, 4, 4, 4, 4, 4, 3, 4, 4, 3, 5, 4, 4,
        4, 4, 4, 4, 4, 4, 4, 5, 4, 4, 4, 3, 1, 3, 4, 1,
        # Extra chars
        5, 4, 4, 5, 4, 4, 4, 4, 3
    ],
    'data': [
        [0x00,0x00,0x00,0x00,0x00], # space
        [0x5f,0x00,0x00,0x00,0x00], # !
        [0x03,0x00,0x03,0x00,0x00], # "
        [0x28,0x7c,0x28,0x7c,0x28], # #
        [0x24,0x7a,0x2f,0x12,0x00], # $
        [0x66,0x10,0x08,0x66,0x00], # %
        [0x36,0x49,0x49,0x7c,0x00], # &
        [0x03,0x00,0x00,0x00,0x00], # '
        [0x1c,0x22,0x41,0x00,0x00], # (
        [0x41,0x22,0x1c,0x00,0x00], # )
        [0x54,0x38,0x54,0x00,0x00], # *
        [0x10,0x38,0x10,0x00,0x00], # +
        [0x80,0x60,0x00,0x00,0x00], # ,
        [0x10,0x10,0x10,0x00,0x00], # -
        [0x60,0x60,0x00,0x00,0x00], # .
        [0x60,0x18,0x06,0x01,0x00], # /
        [0x3e,0x41,0x41,0x3e,0x00], # 0
        [0x42,0x7f,0x40,0x00,0x00], # 1
        [0x62,0x51,0x49,0x46,0x00], # 2
        [0x21,0x49,0x4d,0x33,0x00], # 3
        [0x18,0x16,0x11,0x7f,0x00], # 4
        [0x4f,0x49,0x49,0x31,0x00], # 5
        [0x3c,0x4a,0x49,0x30,0x00], # 6
        [0x01,0x61,0x19,0x07,0x00], # 7
        [0x36,0x49,0x49,0x36,0x00], # 8
        [0x06,0x49,0x29,0x1e,0x00], # 9
        [0x33,0x00,0x00,0x00,0x00], # :
        [0x80,0x6c,0x00,0x00,0x00], # ;
        [0x10,0x28,0x44,0x00,0x00], # <
        [0x28,0x28,0x28,0x00,0x00], # =
        [0x44,0x28,0x10,0x00,0x00], # >
        [0x02,0x51,0x09,0x06,0x00], # ?
        [0x3e,0x49,0x55,0x5e,0x00], # @
        [0x7e,0x09,0x09,0x7e,0x00], # A
        [0x7f,0x49,0x49,0x36,0x00], # B
        [0x3e,0x41,0x41,0x22,0x00], # C
        [0x7f,0x41,0x41,0x3e,0x00], # D
        [0x7f,0x49,0x49,0x41,0x00], # E
        [0x7f,0x09,0x09,0x01,0x00], # F
        [0x3e,0x41,0x49,0x79,0x00], # G
        [0x7f,0x08,0x08,0x7f,0x00], # H
        [0x41,0x7f,0x41,0x00,0x00], # I
        [0x30,0x40,0x40,0x3f,0x00], # J
        [0x7f,0x08,0x14,0x63,0x00], # K
        [0x7f,0x40,0x40,0x40,0x00], # L
        [0x7f,0x02,0x04,0x02,0x7f], # M
        [0x7f,0x02,0x04,0x7f,0x00], # N
        [0x3e,0x41,0x41,0x3e,0x00], # O
        [0x7f,0x09,0x09,0x06,0x00], # P
        [0x3e,0x41,0x21,0x5e,0x00], # Q
        [0x7f,0x09,0x19,0x66,0x00], # R
        [0x46,0x49,0x49,0x31,0x00], # S
        [0x01,0x01,0x7f,0x01,0x01], # T
        [0x3f,0x40,0x40,0x3f,0x00], # U
        [0x7f,0x40,0x20,0x1f,0x00], # V
        [0x3f,0x40,0x20,0x40,0x3f], # W
        [0x77,0x08,0x08,0x77,0x00], # X
        [0x47,0x48,0x48,0x3f,0x00], # Y
        [0x71,0x49,0x45,0x43,0x00], # Z
        [0x7f,0x41,0x00,0x00,0x00], # [
        [0x01,0x06,0x18,0x60,0x00], # \
        [0x41,0x7f,0x00,0x00,0x00], # ]
        [0x04,0x02,0x04,0x00,0x00], # ^
        [0x40,0x40,0x40,0x00,0x00], # _
        [0x01,0x01,0x00,0x00,0x00], # `
        [0x20,0x54,0x54,0x78,0x00], # a
        [0x7f,0x44,0x44,0x38,0x00], # b
        [0x38,0x44,0x44,0x28,0x00], # c
        [0x38,0x44,0x44,0x7f,0x00], # d
        [0x38,0x54,0x54,0x58,0x00], # e
        [0x7e,0x09,0x09,0x02,0x00], # f
        [0x18,0xa4,0xa4,0x7c,0x00], # g
        [0x7f,0x04,0x04,0x78,0x00], # h
        [0x04,0x7d,0x40,0x00,0x00], # i
        [0x60,0x80,0x80,0x7d,0x00], # j
        [0x7f,0x10,0x28,0x44,0x00], # k
        [0x01,0x7f,0x40,0x00,0x00], # l
        [0x7c,0x04,0x78,0x04,0x78], # m
        [0x7c,0x04,0x04,0x78,0x00], # n
        [0x38,0x44,0x44,0x38,0x00], # o
        [0xfc,0x24,0x24,0x18,0x00], # p
        [0x18,0x24,0x24,0xfc,0x00], # q
        [0x7c,0x08,0x04,0x04,0x00], # r
        [0x48,0x54,0x54,0x24,0x00], # s
        [0x3e,0x44,0x44,0x20,0x00], # t
        [0x3c,0x40,0x40,0x7c,0x00], # u
        [0x7c,0x40,0x20,0x1c,0x00], # v
        [0x3c,0x40,0x20,0x40,0x3c], # w
        [0x6c,0x10,0x10,0x6c,0x00], # x
        [0x1c,0xa0,0xa0,0x7c,0x00], # y
        [0x64,0x54,0x4c,0x00,0x00], # z
        [0x08,0x3e,0x41,0x00,0x00], # {
        [0x7f,0x00,0x00,0x00,0x00], # |
        [0x41,0x3e,0x08,0x00,0x00], # }
        [0x08,0x04,0x08,0x04,0x00], # ~
    ]
}

class MockGraphics:
    def __init__(self, i75):
        self.i75 = i75
        self.current_pen = (255, 255, 255)  # White by default
        self.pens = {}
        self.current_font = "bitmap8"  # Default font
        
    def create_pen(self, r, g, b):
        pen_id = len(self.pens)
        self.pens[pen_id] = (r, g, b)
        return pen_id
        
    def set_pen(self, pen_id):
        if pen_id in self.pens:
            self.current_pen = self.pens[pen_id]
    
    def set_font(self, font_name):
        # Support Interstate75 font names
        self.current_font = font_name
    
    def clear(self):
        self.i75.clear()
    
    def line(self, x1, y1, x2, y2):
        # Bresenham's line algorithm
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        x, y = x1, y1
        sx = 1 if x1 < x2 else -1
        sy = 1 if y1 < y2 else -1
        
        if dx > dy:
            err = dx / 2.0
            while x != x2:
                if 0 <= x < self.i75.width and 0 <= y < self.i75.height:
                    self.i75.set_pixel(x, y, *self.current_pen)
                err -= dy
                if err < 0:
                    y += sy
                    err += dx
                x += sx
        else:
            err = dy / 2.0
            while y != y2:
                if 0 <= x < self.i75.width and 0 <= y < self.i75.height:
                    self.i75.set_pixel(x, y, *self.current_pen)
                err -= dx
                if err < 0:
                    x += sx
                    err += dy
                y += sy
        if 0 <= x2 < self.i75.width and 0 <= y2 < self.i75.height:
            self.i75.set_pixel(x2, y2, *self.current_pen)
    
    def rectangle(self, x, y, w, h):
        # Fill a rectangle
        for py in range(y, min(y + h, self.i75.height)):
            for px in range(x, min(x + w, self.i75.width)):
                if 0 <= px < self.i75.width and 0 <= py < self.i75.height:
                    self.i75.set_pixel(px, py, *self.current_pen)
    
    def measure_text(self, text, scale=1, spacing=1):
        # Accurate text measurement based on font
        if not text:
            return 0
        
        total_width = 0
        for i, char in enumerate(text):
            char_index = ord(char) - 32  # ASCII offset
            if char_index < 0 or char_index >= len(FONT8_DATA['widths']):
                char_width = 4  # Default width for unknown chars
            else:
                char_width = FONT8_DATA['widths'][char_index]
            
            total_width += char_width * scale
            if i < len(text) - 1:  # Add spacing between characters
                total_width += spacing * scale
                
        return total_width
    
    def text(self, text, x, y, scale=1, spacing=1):
        # Text rendering using real Interstate75 font8 data
        self._render_font8_text(text, x, y, scale, spacing)
    
    def _render_font8_text(self, text, x, y, scale=1, spacing=1):
        # Render text using font8 data from Pimoroni
        current_x = x
        
        for char in text:
            char_index = ord(char) - 32  # ASCII offset
            if char_index < 0 or char_index >= len(FONT8_DATA['data']):
                # Skip unknown characters
                continue
                
            char_width = FONT8_DATA['widths'][char_index]
            char_data = FONT8_DATA['data'][char_index]
            
            # Draw the character
            for col in range(char_width):
                if col < len(char_data):
                    column_data = char_data[col]
                    
                    # Draw each pixel in the column
                    for row in range(8):  # Font height is 8
                        if column_data & (1 << row):
                            # Draw scaled pixels
                            for sy in range(scale):
                                for sx in range(scale):
                                    px = current_x + col * scale + sx
                                    py = y + row * scale + sy
                                    if 0 <= px < self.i75.width and 0 <= py < self.i75.height:
                                        self.i75.set_pixel(px, py, *self.current_pen)
            
            current_x += char_width * scale + spacing * scale

class Interstate75:
    def __init__(self, display=DISPLAY_INTERSTATE75_64X32, rotation=0, **kwargs):
        self.width  = int(display.get("width", 64))
        self.height = int(display.get("height", 32))
        self.rotation = int(rotation) % 360
        self._brightness = 1.0
        scale = int(os.environ.get("INTERSTATE75_SCALE", "12"))
        self._win = _SimulatorWindow(self._rot_w(), self._rot_h(), scale=scale)

        # Create mock display interface that matches real hardware
        self.display = MockGraphics(self)
        
        self._buffer = [[(0, 0, 0) for _ in range(self.width)] for _ in range(self.height)]
        self._last_frame_time = 0.0
        self._frame_interval = 1.0 / int(os.environ.get("INTERSTATE75_FPS", "60"))

    def set_brightness(self, value):
        self._brightness = _clamp(float(value), 0.0, 1.0)

    def clear(self):
        for y in range(self.height):
            for x in range(self.width):
                self._buffer[y][x] = (0, 0, 0)
        self._redraw()

    def set_pixel(self, x, y, r, g, b):
        x = int(x); y = int(y)
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        self._buffer[y][x] = (_clamp(int(r),0,255), _clamp(int(g),0,255), _clamp(int(b),0,255))

    def show(self):
        """Flush to window and pump Tk from the main thread."""
        if self._win.is_closed():
            print("Interstate 75 simulator window closed. Exiting.", file=sys.stderr)
            sys.exit(0)
        self._redraw()
        # Pump Tk here (main thread)
        self._win.root.update_idletasks()
        self._win.root.update()
        # FPS throttle
        now = time.perf_counter()
        dt = now - self._last_frame_time
        if dt < self._frame_interval:
            time.sleep(self._frame_interval - dt)
        self._last_frame_time = time.perf_counter()

    def update(self):
        """Alias for show() to match real hardware API"""
        self.show()

    # ----- helpers -----
    def _rot_w(self):
        return self.width if self.rotation % 180 == 0 else self.height

    def _rot_h(self):
        return self.height if self.rotation % 180 == 0 else self.width

    def _transform_coords(self, x, y):
        w, h = self.width, self.height
        if self.rotation == 0:   return x, y
        if self.rotation == 90:  return h - 1 - y, x
        if self.rotation == 180: return w - 1 - x, h - 1 - y
        if self.rotation == 270: return y, w - 1 - x
        return x, y

    def _redraw(self):
        for y in range(self.height):
            for x in range(self.width):
                r, g, b = self._buffer[y][x]
                if self._brightness < 1.0:
                    r = int(r * self._brightness); g = int(g * self._brightness); b = int(b * self._brightness)
                tx, ty = self._transform_coords(x, y)
                self._win.set_pixel(tx, ty, r, g, b)

# Export the constants and classes that match real hardware
PANEL_FM6126A = "FM6126A"

if __name__ == "__main__":
    import math
    i75 = Interstate75(display=DISPLAY_INTERSTATE75_64X32)
    i75.set_brightness(0.8)
    t = 0.0
    while True:
        for y in range(i75.height):
            for x in range(i75.width):
                v = (
                    128 + 127 * math.sin((x + t) * 0.15),
                    128 + 127 * math.sin((y + t) * 0.17),
                    128 + 127 * math.sin((x + y + t) * 0.11),
                )
                i75.set_pixel(x, y, *v)
        i75.show()
        t += 1.0
