"""
Screenshot capture + pynput action executor.
Merged from computer_action_executor.py + computer_use_util.py.
"""
import base64
import os
import platform
import subprocess
import time
import uuid
from typing import Any, Dict, Optional

import mss
import mss.tools
from pynput import mouse, keyboard
from pynput.keyboard import Key
from pynput.mouse import Button

from config import AUTOMATION_CONFIG


# ========== Utility Functions (from computer_use_util.py) ==========

def screenshot_to_bytes() -> bytes:
    """Capture primary screen and return PNG bytes."""
    with mss.mss() as sct:
        screenshot = sct.grab(sct.monitors[1])
        return mss.tools.to_png(screenshot.rgb, screenshot.size)


def b64_png(png_bytes: bytes) -> str:
    """Encode PNG bytes to base64 string."""
    return base64.b64encode(png_bytes).decode("utf-8")


def make_tool_result(
    tool_use_id: str,
    ok: bool,
    message: str,
    include_screenshot: bool,
    screenshot_bytes: Optional[bytes],
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build tool result dict with optional screenshot."""
    tr: Dict[str, Any] = {
        "tool_use_id": tool_use_id,
        "status": "success" if ok else "error",
        "output": message,
        "error": None if ok else message,
        "include_screenshot": bool(include_screenshot),
        "meta": meta or {},
    }
    if include_screenshot and screenshot_bytes:
        tr["screenshot_b64"] = b64_png(screenshot_bytes)
    return tr


def get_or_create_device_id() -> str:
    """Get or create persistent device ID."""
    device_file = os.path.expanduser(AUTOMATION_CONFIG["DEVICE_FILE"])
    if os.path.exists(device_file):
        with open(device_file, "r") as f:
            return f.read().strip()

    device_id = str(uuid.uuid4())
    with open(device_file, "w") as f:
        f.write(device_id)
    return device_id


# ========== Action Executor (from computer_action_executor.py) ==========

class ComputerActionExecutor:
    """Automation action executor using pynput."""

    def __init__(self, on_minimize_panel=None, screen_size=None):
        self.on_minimize_panel = on_minimize_panel
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            actual_width = monitor["width"]
            actual_height = monitor["height"]

        # If screen_size matches actual screen, scale = 1.0 (coords are already screen pixels)
        base_w = screen_size[0] if screen_size else AUTOMATION_CONFIG["SCREEN_SCALE_WIDTH"]
        base_h = screen_size[1] if screen_size else AUTOMATION_CONFIG["SCREEN_SCALE_HEIGHT"]
        self.scale_x = actual_width / base_w
        self.scale_y = actual_height / base_h

        self.mouse_controller = mouse.Controller()
        self.keyboard_controller = keyboard.Controller()

    def run_one(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Execute single action."""
        tool_name = action.get("name", "")
        tool_input = action.get("input") or {}
        action_type = (tool_input.get("action") or "").strip()
        start_time = time.time()

        try:
            if tool_name == "minimize_panel":
                if self.on_minimize_panel:
                    self.on_minimize_panel()
                msg = "panel minimized"
            elif tool_name == "computer":
                if action_type in ("left_click", "right_click", "double_click", "middle_click", "triple_click"):
                    self._do_click(action_type, tool_input)
                    msg = f"{action_type} ok"

                elif action_type == "type":
                    text = tool_input.get("text")
                    self._type_text(text)
                    msg = f"type {text} ok"

                elif action_type == "key":
                    self._do_hotkey(tool_input)
                    msg = "hotkey ok"

                elif action_type == "mouse_move":
                    x, y = self._mouse_move(tool_input)
                    msg = f"mouse_move ({x},{y}) ok"

                elif action_type == "left_click_drag":
                    start = tool_input.get("start_coordinate")
                    if start:
                        sx, sy = self._xy(start)
                        self.mouse_controller.position = (sx, sy)
                        time.sleep(0.2)
                    self.mouse_controller.press(Button.left)
                    x, y = self._mouse_move(tool_input)
                    time.sleep(0.1)
                    self.mouse_controller.release(Button.left)
                    msg = f"drag_to ({x},{y}) ok"

                elif action_type == "scroll":
                    self._do_scroll(tool_input)
                    msg = "scroll ok"

                elif action_type == "wait":
                    time.sleep(0.5)
                    msg = "wait ok"

                elif action_type == "screenshot":
                    msg = "screenshot requested"

                elif action_type in ("done", "finish_task", "fail", "call_user"):
                    msg = action_type

                else:
                    raise ValueError(f"Unknown action: {action_type}")
            else:
                msg = f"Unknown tool: {tool_name}"

            dt = time.time() - start_time
            return {
                "ok": action_type != "fail",
                "message": msg,
                "meta": {"action": action_type, "elapsed_time": dt},
            }

        except Exception as e:
            dt = time.time() - start_time
            return {
                "ok": False,
                "message": f"{type(e).__name__}: {e}",
                "meta": {"action": action_type, "elapsed_time": dt},
            }

    def _mouse_move(self, tool_input):
        """Smooth mouse movement."""
        coord = tool_input.get("coordinate")
        dur = tool_input.get("duration") or 0.3
        x, y = self._xy(coord)

        current_pos = self.mouse_controller.position
        steps = max(10, int(dur * AUTOMATION_CONFIG["MOUSE_MOVE_STEPS_PER_SEC"]))

        for i in range(steps + 1):
            t = i / steps
            new_x = current_pos[0] + (x - current_pos[0]) * t
            new_y = current_pos[1] + (y - current_pos[1]) * t
            self.mouse_controller.position = (new_x, new_y)
            time.sleep(dur / steps)
        return x, y

    def _do_click(self, action: str, tool_input: Dict[str, Any]):
        """Execute click operation."""
        coord = tool_input.get("coordinate")
        if coord:
            x, y = self._xy(coord)
            self.mouse_controller.position = (x, y)
            time.sleep(AUTOMATION_CONFIG["MOUSE_CLICK_DELAY"])

        mods = tool_input.get("modifiers") or []
        for k in mods:
            self.keyboard_controller.press(getattr(Key, k))

        if action == "left_click":
            self.mouse_controller.click(Button.left)
        elif action == "right_click":
            self.mouse_controller.click(Button.right)
        elif action == "double_click":
            self.mouse_controller.click(Button.left, 2)
        elif action == "triple_click":
            self.mouse_controller.click(Button.left, 3)
        elif action == "middle_click":
            self.mouse_controller.click(Button.middle)
        else:
            raise ValueError(action)

        for k in reversed(mods):
            self.keyboard_controller.release(getattr(Key, k))

    def _type_text(self, text: str):
        """Type text via clipboard paste (avoids input method conflicts)."""
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        elif system == "Windows":
            subprocess.run(["clip"], input=text.encode("utf-16le"), check=True)
        else:
            subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode("utf-8"), check=True)

        paste_key = Key.cmd if system == "Darwin" else Key.ctrl
        self.keyboard_controller.press(paste_key)
        self.keyboard_controller.press("v")
        self.keyboard_controller.release("v")
        self.keyboard_controller.release(paste_key)

    def _do_hotkey(self, tool_input):
        """Execute hotkey combination."""
        mods = tool_input.get("modifiers") or []
        mains = tool_input.get("mains") or []

        if not mains:
            return

        for m in mods:
            self.keyboard_controller.press(getattr(Key, m))
        time.sleep(AUTOMATION_CONFIG["HOTKEY_DELAY"])

        for k in mains:
            key_obj = getattr(Key, k) if hasattr(Key, k) else k
            self.keyboard_controller.press(key_obj)
            self.keyboard_controller.release(key_obj)

        time.sleep(0.02)
        for m in reversed(mods):
            self.keyboard_controller.release(getattr(Key, m))

    def _do_scroll(self, tool_input: Dict[str, Any]):
        """Execute scroll operation."""
        direction = tool_input.get("scroll_direction")
        scroll_amount = tool_input.get("scroll_amount") or 10
        coord = tool_input.get("coordinate")

        scroll_amount = scroll_amount * AUTOMATION_CONFIG["SCROLL_MULTIPLIER"]

        if coord:
            x, y = self._xy(coord)
            self.mouse_controller.position = (x, y)
            time.sleep(AUTOMATION_CONFIG["MOUSE_CLICK_DELAY"])

        if direction in ("up", "down"):
            delta_y = scroll_amount if direction == "up" else -scroll_amount
            self.mouse_controller.scroll(0, delta_y)
        elif direction in ("left", "right"):
            delta_x = scroll_amount if direction == "right" else -scroll_amount
            self.mouse_controller.scroll(delta_x, 0)
        else:
            raise ValueError(f"scroll_direction invalid: {direction}")

    def _xy(self, coord):
        """Convert coordinates to actual screen position."""
        if not (isinstance(coord, (list, tuple)) and len(coord) == 2):
            raise ValueError(f"coordinate must be [x,y], got {coord}")

        x = int(coord[0] * self.scale_x)
        y = int(coord[1] * self.scale_y)

        with mss.mss() as sct:
            primary = sct.monitors[1]
            x = primary["left"] + x
            y = primary["top"] + y
        return x, y

    def _move_to_primary(self, app_name):
        """Move app's front window to the primary screen (macOS only)."""
        try:
            script = (
                f'tell application "System Events"\n'
                f'    tell process "{app_name}"\n'
                f'        set position of window 1 to {{0, 25}}\n'
                f'    end tell\n'
                f'end tell'
            )
            subprocess.run(["osascript", "-e", script], timeout=3, capture_output=True)
        except Exception:
            pass

