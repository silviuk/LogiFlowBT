"""
Precision Screen Edge Detector for Windows and Linux.
Monitors cursor position and triggers a switch event when the cursor dwells at the configured screen edge.
"""

import sys
import time
import threading
from typing import Callable, Optional, Tuple, List, Dict

# Win32 ctypes definitions
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG)
        ]


class ScreenEdgeDetector:
    def __init__(self,
                 trigger_edge: str = "right",
                 active_edges: Optional[List[str]] = None,
                 hold_delay_ms: int = 250,
                 cooldown_ms: int = 2500,
                 on_trigger_callback: Optional[Callable[[str, int, int, float], None]] = None):
        """
        :param trigger_edge: 'right', 'left', 'top', or 'bottom'
        :param active_edges: List of edges to monitor, e.g. ['left', 'right']
        :param hold_delay_ms: ms cursor must dwell on border before triggering
        :param cooldown_ms: ms after trigger before next detection is accepted
        :param on_trigger_callback: func(edge, x, y, ratio) called when triggered
        """
        self.trigger_edge = trigger_edge.lower() if trigger_edge else "right"
        if active_edges:
            self.active_edges = [e.lower() for e in active_edges]
        else:
            self.active_edges = [self.trigger_edge]
        self.hold_delay_ms = hold_delay_ms
        self.cooldown_ms = cooldown_ms
        self.on_trigger_callback = on_trigger_callback

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._current_edge: Optional[str] = None
        self._hold_start_time: Optional[float] = None
        self._last_trigger_time: float = 0.0
        self._screen_bounds = self._get_screen_bounds()

    def _get_screen_bounds(self) -> Dict[str, int]:
        """
        Calculates the bounding rectangle across all displays.
        """
        bounds = {"left": 0, "top": 0, "right": 1920, "bottom": 1080}
        if sys.platform == "win32":
            try:
                # Use virtual screen metrics which cover multi-monitors
                SM_XVIRTUALSCREEN = 76
                SM_YVIRTUALSCREEN = 77
                SM_CXVIRTUALSCREEN = 78
                SM_CYVIRTUALSCREEN = 79

                vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
                vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
                vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
                vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

                if vw > 0 and vh > 0:
                    bounds = {
                        "left": vx,
                        "top": vy,
                        "right": vx + vw,
                        "bottom": vy + vh
                    }
            except Exception as e:
                print(f"[EdgeDetector] Error fetching Windows screen metrics: {e}")
        else:
            # Linux: try xlib, xrandr, or tkinter
            try:
                import subprocess
                res = subprocess.run(["xdotool", "getdisplaygeometry"], capture_output=True, text=True, timeout=1)
                if res.returncode == 0:
                    parts = res.stdout.strip().split()
                    bounds = {
                        "left": 0,
                        "top": 0,
                        "right": int(parts[0]),
                        "bottom": int(parts[1])
                    }
            except Exception:
                # Fallback: tkinter
                try:
                    import tkinter
                    root = tkinter.Tk()
                    root.withdraw()
                    bounds = {
                        "left": 0,
                        "top": 0,
                        "right": root.winfo_screenwidth(),
                        "bottom": root.winfo_screenheight()
                    }
                    root.destroy()
                except Exception:
                    pass

        return bounds

    def get_cursor_pos(self) -> Tuple[int, int]:
        """
        Returns (x, y) cursor coordinate.
        """
        if sys.platform == "win32":
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            return pt.x, pt.y
        else:
            # Linux: try pynput, xlib, or xdotool
            try:
                import subprocess
                res = subprocess.run(["xdotool", "getmouselocation", "--shell"], capture_output=True, text=True, timeout=1)
                if res.returncode == 0:
                    x, y = 0, 0
                    for line in res.stdout.splitlines():
                        if line.startswith("X="):
                            x = int(line[2:])
                        elif line.startswith("Y="):
                            y = int(line[2:])
                    return x, y
            except Exception:
                pass
            return 0, 0

    def refresh_screen_bounds(self) -> None:
        self._screen_bounds = self._get_screen_bounds()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.refresh_screen_bounds()
        self._thread = threading.Thread(target=self._loop, name="EdgeDetectorThread", daemon=True)
        self._thread.start()
        edges_str = ", ".join(self.active_edges)
        print(f"[EdgeDetector] Started monitoring edges [{edges_str}] on bounds {self._screen_bounds}")

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        print("[EdgeDetector] Stopped.")

    def _is_at_edge(self, x: int, y: int, edge: Optional[str] = None) -> bool:
        target = edge.lower() if edge else self.trigger_edge
        b = self._screen_bounds
        tol = 2  # pixel tolerance margin
        if target == "right":
            return x >= (b["right"] - tol)
        elif target == "left":
            return x <= (b["left"] + tol)
        elif target == "bottom":
            return y >= (b["bottom"] - tol)
        elif target == "top":
            return y <= (b["top"] + tol)
        return False

    def _get_triggered_edge(self, x: int, y: int) -> Optional[str]:
        for edge in self.active_edges:
            if self._is_at_edge(x, y, edge):
                return edge
        return None

    def _calculate_ratio(self, x: int, y: int, edge: Optional[str] = None) -> float:
        target = edge.lower() if edge else self.trigger_edge
        b = self._screen_bounds
        if target in ("left", "right"):
            h = max(1, b["bottom"] - b["top"])
            return max(0.0, min(1.0, (y - b["top"]) / h))
        else:
            w = max(1, b["right"] - b["left"])
            return max(0.0, min(1.0, (x - b["left"]) / w))

    def _loop(self) -> None:
        while self._running:
            now = time.time()
            # If in cooldown after a recent switch, wait
            if (now - self._last_trigger_time) * 1000 < self.cooldown_ms:
                self._hold_start_time = None
                self._current_edge = None
                time.sleep(0.05)
                continue

            x, y = self.get_cursor_pos()
            edge = self._get_triggered_edge(x, y)

            if edge:
                if self._current_edge != edge:
                    self._current_edge = edge
                    self._hold_start_time = now
                else:
                    elapsed_ms = (now - self._hold_start_time) * 1000
                    if elapsed_ms >= self.hold_delay_ms:
                        # Dwell time met! Fire trigger for this edge
                        ratio = self._calculate_ratio(x, y, edge)
                        print(f"[EdgeDetector] Edge '{edge}' triggered at ({x}, {y}) ratio={ratio:.2f}")
                        self._last_trigger_time = now
                        self._hold_start_time = None
                        self._current_edge = None

                        if self.on_trigger_callback:
                            try:
                                self.on_trigger_callback(edge, x, y, ratio)
                            except Exception as e:
                                print(f"[EdgeDetector] Callback error: {e}")
            else:
                self._current_edge = None
                self._hold_start_time = None

            time.sleep(0.015)  # ~65 Hz polling
