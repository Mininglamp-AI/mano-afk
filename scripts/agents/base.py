"""Base agent ABC — session management, trajectory saving, result.json."""

import base64
import json
import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from config import AUTOMATION_CONFIG

logger = logging.getLogger("mano.agent")


class BaseAgent(ABC):
    """Abstract base for task prediction agents."""

    agent_type: str = "unknown"

    def __init__(self):
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.session_id = f"sess-{ts}-{uuid.uuid4().hex[:8]}"
        self.step_counter = 0
        self.history: list[str] = []
        self._start_time = time.time()
        self._token_usage: dict = {}
        self._step_timings: list[float] = []

    @abstractmethod
    async def predict(
        self,
        task_instruction: str,
        tool_results: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Run one prediction step. Returns (reasoning, actions)."""
        ...

    @abstractmethod
    def agree_to_continue(self) -> None:
        """Signal that user has approved continuation after CALL_USER."""
        ...

    # ─── Trajectory saving ────────────────────────────────────

    def _get_save_dir(self) -> str:
        return os.path.expanduser(os.getenv("save_dir", "~/mano-trajectory/result"))

    def _save_screenshot_from_tool_results(self, tool_results: Optional[List[Dict[str, Any]]]) -> Optional[str]:
        if not tool_results:
            return None
        for tr in reversed(tool_results):
            b64 = tr.get("screenshot_b64")
            if b64:
                try:
                    screenshot_bytes = base64.b64decode(b64)
                    return self._save_screenshot(screenshot_bytes)
                except Exception as e:
                    logger.warning(f"[{self.session_id}] Failed to decode screenshot: {e}")
        return None

    def _save_screenshot(self, screenshot_bytes: Optional[bytes]) -> Optional[str]:
        if not screenshot_bytes:
            return None
        try:
            trajectory_dir = os.path.join(self._get_save_dir(), self.session_id, "trajectory")
            os.makedirs(trajectory_dir, exist_ok=True)
            screenshot_path = os.path.join(trajectory_dir, f"{self.step_counter}.png")
            self.step_counter += 1
            with open(screenshot_path, "wb") as f:
                f.write(screenshot_bytes)
            return screenshot_path
        except Exception as e:
            logger.warning(f"[{self.session_id}] Failed to save screenshot: {e}")
            return None

    def _save_debug_image(self, image_path: str, point: Optional[list], action_text: str):
        if not image_path or not os.path.exists(image_path):
            return
        try:
            from PIL import ImageDraw, ImageFont

            trajectory_dir = os.path.join(self._get_save_dir(), self.session_id, "trajectory_visual")
            os.makedirs(trajectory_dir, exist_ok=True)

            img = Image.open(image_path).convert("RGB")
            draw = ImageDraw.Draw(img)

            coord_base = getattr(self, "screen_size", None)
            base_w = coord_base[0] if coord_base else AUTOMATION_CONFIG["SCREEN_SCALE_WIDTH"]
            base_h = coord_base[1] if coord_base else AUTOMATION_CONFIG["SCREEN_SCALE_HEIGHT"]
            scale_x = img.width / base_w
            scale_y = img.height / base_h

            if point and len(point) >= 2:
                cx = int(point[0] * scale_x)
                cy = int(point[1] * scale_y)
                r = max(6, int(6 * scale_x))
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="red", outline="red")

            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=24)
            except Exception:
                font = ImageFont.load_default()

            text_pos = (50, 50)
            bbox = draw.textbbox(text_pos, action_text, font=font)
            draw.rectangle([bbox[0] - 5, bbox[1] - 5, bbox[2] + 5, bbox[3] + 5], fill=(255, 255, 255, 200))
            draw.text(text_pos, action_text, font=font, fill=(0, 0, 255))

            save_path = os.path.join(trajectory_dir, os.path.basename(image_path))
            img.save(save_path)
        except Exception as e:
            logger.warning(f"[{self.session_id}] Failed to save debug image: {e}")

    def _save_history(self, reasoning: str, actions: list, action_desp: str = "", elapsed: float = 0.0):
        self.history.append(f"<think>{reasoning}</think>\n<action_desp>{action_desp}</action_desp>\n<action>{actions}</action>\n<elapsed>{elapsed:.2f}</elapsed>")
        self._step_timings.append(round(elapsed, 3))

    def _save_raw_response(self, step: int, raw_text: str):
        try:
            trajectory_dir = os.path.join(self._get_save_dir(), self.session_id, "trajectory")
            os.makedirs(trajectory_dir, exist_ok=True)
            path = os.path.join(trajectory_dir, "raw_responses.jsonl")
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"step": step, "raw": raw_text}, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"[{self.session_id}] Failed to save raw response: {e}")

    def _get_chip_info(self) -> Optional[str]:
        import platform as _platform
        if _platform.system() != "Darwin":
            return None
        try:
            import subprocess
            r = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=3,
            )
            chip = r.stdout.strip()
            return chip if chip else None
        except Exception:
            return None

    def save_result(self, task: str):
        try:
            session_dir = os.path.join(self._get_save_dir(), self.session_id)
            os.makedirs(session_dir, exist_ok=True)
            result = {
                "task": task,
                "agent_type": self.agent_type,
                "model_name": getattr(self, "model_name", None),
                "history_resps": self.history,
                "elapsed_time_sec": round(time.time() - self._start_time, 2),
                "step_count": self.step_counter,
                "step_timings_sec": self._step_timings,
                "token_usage": self._token_usage,
            }
            chip = self._get_chip_info()
            if chip:
                result["hw_chip"] = chip
            result_path = os.path.join(session_dir, "result.json")
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=4, ensure_ascii=False)
            logger.info(f"[{self.session_id}] Result saved to {result_path}")
            return result_path
        except Exception as e:
            logger.warning(f"[{self.session_id}] Failed to save result: {e}")
            return None
