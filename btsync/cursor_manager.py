"""
Cross-Platform Cursor Manager for Windows and Linux.
Positions the mouse cursor smoothly upon entry from the partner host.
"""

import sys
from typing import Dict

if sys.platform == "win32":
    import ctypes
    user32 = ctypes.windll.user32


class CursorManager:
    def __init__(self):
        pass

    def set_cursor_pos(self, x: int, y: int) -> bool:
        """
        Positions the cursor at the specified screen coordinate.
        """
        if sys.platform == "win32":
            try:
                user32.SetCursorPos(int(x), int(y))
                return True
            except Exception as e:
                print(f"[CursorManager] Windows SetCursorPos error: {e}")
                return False
        else:
            # Linux: try xdotool
            try:
                import subprocess
                subprocess.run(["xdotool", "mousemove", str(int(x)), str(int(y))], timeout=1)
                return True
            except Exception:
                pass
            return False

    def position_cursor_at_entry(self, entry_edge: str, ratio: float, bounds: Dict[str, int]) -> None:
        """
        Places the cursor at the given entry edge at the relative ratio position.
        :param entry_edge: 'left', 'right', 'top', or 'bottom'
        :param ratio: 0.0 to 1.0 representing vertical/horizontal position
        :param bounds: dict with left, top, right, bottom
        """
        ratio = max(0.0, min(1.0, ratio))
        margin = 10  # pixels inside from edge to prevent bounce-back
        w = max(1, bounds["right"] - bounds["left"])
        h = max(1, bounds["bottom"] - bounds["top"])

        if entry_edge == "left":
            target_x = bounds["left"] + margin
            target_y = bounds["top"] + int(ratio * h)
        elif entry_edge == "right":
            target_x = bounds["right"] - margin
            target_y = bounds["top"] + int(ratio * h)
        elif entry_edge == "top":
            target_x = bounds["left"] + int(ratio * w)
            target_y = bounds["top"] + margin
        elif entry_edge == "bottom":
            target_x = bounds["left"] + int(ratio * w)
            target_y = bounds["bottom"] - margin
        else:
            target_x = bounds["left"] + int(w / 2)
            target_y = bounds["top"] + int(h / 2)

        self.set_cursor_pos(target_x, target_y)
        print(f"[CursorManager] Positioned cursor at entry '{entry_edge}' ({target_x}, {target_y})")
