"""LocalAgent — on-device VLM agent using MLX."""

import base64
import io
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from agents.base import BaseAgent
from config import LOCAL_AGENT_CONFIG, AUTOMATION_CONFIG

logger = logging.getLogger("mano.agent")

class LocalAgent(BaseAgent):

    agent_type = "local"
    
    SYSTEM_PROMPT = "You are a helpful assistant."

    INSTRUCTION_TEMPLATE = """\
You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.

## OS Platform
{platform}

## Output Format
<think>思考过程</think>
<action_desp>动作描述</action_desp>
<action>具体动作</action>

## Action Space

hover(start_box='<|box_start|>(x1,y1)<|box_end|>')
click(start_box='<|box_start|>(x1,y1)<|box_end|>')
triple_click(start_box='<|box_start|>(x1,y1)<|box_end|>') left click at the coordinate (x1,y1) three times
hotkey_click(start_box='<|box_start|>(x1,y1)<|box_end|>', key=''). press command key and click at the coordinate (x1,y1)
right_single(start_box='<|box_start|>(x1,y1)<|box_end|>').  right click at the coordinate (x1,y1)
type(content='') type the content.
doubleclick(start_box='<|box_start|>(x1,y1)<|box_end|>')
drag(start_box='<|box_start|>(x1,y1)<|box_end|>', end_box='<|box_start|>(x3,y3)<|box_end|>') # Drag an element from the start coordinate (x1,y1) to the end coordinate (x3,y3).
hotkey(key='') # Trigger a keyboard shortcut.
wait(duration='') # Sleep for specified duration (in seconds) and take a screenshot to check for any changes.
call_user() # Request human assistance
stop(reason='') # If the item can not found in the image, give the reason
scroll(start_box='<|box_start|>(x1,y1)<|box_end|>', direction='down or up or right or left', amount='scroll_amount') # Scroll on the specified direction at the coordinate (x1,y1) by the given amount
finish() # The task is completed.

## Note
- Use Chinese in `<think>` part.
- Write a small plan and finally summarize your next action (with its target element) in one sentence in `<action_desp>` part.

## User Instruction:
{instruction}
"""

    def __init__(self, model_path: Optional[str] = None):
        super().__init__()
        import re as _re  # for parse helpers
        self._re = _re

        self.cfg = LOCAL_AGENT_CONFIG

        self._model_path = os.path.expanduser(model_path or self.cfg["MODEL_PATH"])
        self.model_name = os.path.basename(self._model_path)
        # self._engine = None  # HMInference instance (cider path)
        # To revert to cider HMInference, uncomment _engine and see _ensure_model_loaded / _infer:
        self.model = None
        self.processor = None
        self._custom_generate = None
        self._model_loaded = False

        self.prompt_history: list[dict] = []  # [{"desc": str, "screenshot_b64": str}]

        # Store actual screen size for coordinate conversion
        import mss as _mss
        with _mss.mss() as sct:
            m = sct.monitors[1]
            self.screen_size = (m["width"], m["height"])

    def _ensure_model_loaded(self):
        """Lazy-load model on first use. Must be called from the worker thread
        so that MLX Metal GPU streams are created in the same thread that runs inference."""
        if self._model_loaded:
            return
        import mlx_vlm as pm
        from vlm_service import custom_generate
        from config import get_config

        logger.info(f"Loading local model from {self._model_path} ...")
        self.model, self.processor = pm.load(self._model_path)

        # W8A8 acceleration (config: auto/on/off, default auto)
        w8a8_mode = get_config("w8a8") or "auto"
        if w8a8_mode != "off":
            try:
                import mlx.core as mx
                from cider import convert_model, is_available
                if w8a8_mode == "auto" and not is_available():
                    logger.info("W8A8 not available on this hardware (requires M5+)")
                elif w8a8_mode == "on" or is_available():
                    try:
                        stats = convert_model(self.model.language_model)
                    except Exception:
                        stats = convert_model(self.model)
                    # Pre-warm: quantize all INT8 weights upfront
                    from cider.nn import CiderLinear
                    for module in self.model.language_model.modules():
                        if isinstance(module, CiderLinear):
                            module._ensure_w8()
                    mx.eval(self.model.parameters())
                    logger.info(f"W8A8 enabled: {stats}")
            except ImportError:
                if w8a8_mode == "on":
                    logger.warning("W8A8 requested but cider not installed. Run: mano-afk install-sdk")
            except Exception as e:
                logger.warning(f"W8A8 init failed: {e}")

        self._custom_generate = custom_generate
        self._model_loaded = True
        logger.info("Local model loaded successfully.")

    # ─── BaseAgent interface ──────────────────────────────────

    async def predict(
        self,
        task_instruction: str,
        tool_results: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        self._ensure_model_loaded()
        _t0 = time.time()

        # 1. Extract screenshot — take one if first step (no tool_results)
        screenshot_b64 = self._extract_screenshot(tool_results)
        if screenshot_b64 is None:
            screenshot_b64 = self._take_screenshot_b64()
        _t1 = time.time()

        # 2. Build prompt and images list
        user_text, images = self._build_prompt(task_instruction, screenshot_b64)
        _t2 = time.time()

        # 3. Run local inference
        response_text = self._infer(user_text, images)
        _t3 = time.time()
        print(f"  [timing] screenshot={_t1-_t0:.1f}s prompt={_t2-_t1:.1f}s infer={_t3-_t2:.1f}s")
        print(f"  [model output] {response_text}")
        self._save_raw_response(self.step_counter, response_text)

        # 4. Parse <think>/<action_desp>/<action> tags
        parsed = self._parse_response(response_text)
        think = parsed["think"]
        action_desp = parsed["action_desp"]
        action = parsed["action"]
        if action:
            print(f"  [parsed] {action}")

        # 5. Record prompt history (current screenshot + action description)
        if screenshot_b64:
            self.prompt_history.append({
                "desc": action_desp or str(action),
                "screenshot_b64": screenshot_b64,
            })

        # 6. Convert to Claude-compatible actions format
        if action is None:
            actions = [{"action_type": "FAIL", "raw_response": response_text}]
        else:
            actions = self._convert_action(action)

        # 7. Save trajectory
        image_path = self._save_screenshot_from_tool_results(tool_results)
        if image_path is None and screenshot_b64:
            # First step: no tool_results, save the self-captured screenshot
            image_path = self._save_screenshot(base64.b64decode(screenshot_b64))
        self._save_history(think, actions, action_desp, elapsed=time.time() - _t0)
        if actions and image_path:
            try:
                a = actions[0]
                inp = a.get("input", {})
                action_str = a.get("action_type") or inp.get("action", "unknown")
                # Enrich label for specific actions
                if action_str in ("type",) and inp.get("text"):
                    action_str = f"type: {inp['text'][:30]}"
                elif action_str in ("key",) and inp.get("text"):
                    action_str = f"key: {inp['text']}"
                elif action_str in ("scroll",):
                    d = inp.get("scroll_direction", "")
                    action_str = f"scroll {d}"
                elif action_str in ("wait",):
                    action_str = f"wait {inp.get('duration', '')}s"
                draw_point = inp.get("coordinate")
                self._save_debug_image(image_path, draw_point, action_str)
            except Exception as e:
                logger.warning(f"[{self.session_id}] Failed to save debug image: {e}")

        return think, actions

    def agree_to_continue(self) -> None:
        self.prompt_history.append({
            "desc": "用户已确认继续",
            "screenshot_b64": "",
        })

    # ─── Prompt building ──────────────────────────────────────

    def _take_screenshot_b64(self) -> str:
        """Capture screen and return resized base64 PNG (for first step with no tool_results)."""
        from executor import screenshot_to_bytes, b64_png
        raw_bytes = screenshot_to_bytes()
        raw_b64 = b64_png(raw_bytes)
        return self._resize_screenshot_b64(raw_b64)

    def _extract_screenshot(self, tool_results: Optional[List[Dict[str, Any]]]) -> Optional[str]:
        """Extract the most recent screenshot_b64 from tool_results, resized to SCREENSHOT_WIDTH."""
        if not tool_results:
            return None
        for tr in reversed(tool_results):
            b64 = tr.get("screenshot_b64")
            if b64:
                return self._resize_screenshot_b64(b64)
        return None

    def _resize_screenshot_b64(self, b64: str) -> str:
        """Resize a base64 screenshot to SCREENSHOT_WIDTH, preserving aspect ratio."""
        target_w = self.cfg["SCREENSHOT_WIDTH"]  # 1280
        img_bytes = base64.b64decode(b64)
        img = Image.open(io.BytesIO(img_bytes))
        if img.width == target_w:
            return b64
        ratio = target_w / img.width
        new_h = int(img.height * ratio)
        img = img.resize((target_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def _build_prompt(self, task: str, current_screenshot_b64: Optional[str]) -> Tuple[str, list]:
        """Build user message text and images list."""
        import platform as _platform
        images: list[str] = []
        history_count = self.cfg["HISTORY_IMAGE_COUNT"]
        recent = self.prompt_history[-(history_count + 1):]

        history_parts = []
        for i, h in enumerate(self.prompt_history):
            step_num = i + 1
            desc = h["desc"]
            if h in recent and h.get("screenshot_b64"):
                images.append(h["screenshot_b64"])
                history_parts.append(f"第{step_num}步：{desc}，对应的截图为<image>")
            else:
                history_parts.append(f"第{step_num}步：{desc}")

        history_text = "\n".join(history_parts) if history_parts else "无"

        # Build instruction section
        instruction_parts = [f"### task: {task}"]
        instruction_parts.append(f"### action history: {history_text}")
        if current_screenshot_b64:
            images.append(current_screenshot_b64)
            instruction_parts.append("当前截图为<image>")

        text = self.INSTRUCTION_TEMPLATE.format(
            platform=_platform.system(),
            instruction="\n".join(instruction_parts),
        )
        return text, images

    # ─── Inference ────────────────────────────────────────────

    def _infer(self, user_text: str, images: list[str]) -> str:
        """Call local model via cider vlm_service."""
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]

        # Convert base64 images to PIL for mlx_vlm
        pil_images = []
        for b64 in images:
            img_bytes = base64.b64decode(b64)
            pil_images.append(Image.open(io.BytesIO(img_bytes)))

        # ── vlm_service path ──
        prompt = self.processor.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        org_placeholder = "<image>"
        new_placeholder = "<|vision_start|><|image_pad|><|vision_end|>"
        pi = len(pil_images)
        while pi > 0:
            pi -= 1
            pos = prompt.rfind(org_placeholder)
            if pos >= 0:
                prompt = prompt[:pos] + prompt[pos:].replace(org_placeholder, new_placeholder, 1)
            else:
                break
        result = self._custom_generate(
            self.model, self.processor, prompt,
            pil_images if pil_images else None,
            max_tokens=self.cfg["MAX_NEW_TOKENS"],
            temperature=self.cfg["TEMPERATURE"],
            top_p=self.cfg["TOP_P"],
            prefill_step_size=2048,
        )
        print(f"  [decode] {getattr(result, 'generation_tokens', 0)} tokens, {getattr(result, 'generation_tps', 0):.1f} tok/s, peak_mem={getattr(result, 'peak_memory', 0):.1f}GB")
        step_usage = {
            "prompt_tokens": getattr(result, "prompt_tokens", 0) or 0,
            "generation_tokens": getattr(result, "generation_tokens", 0) or 0,
        }
        steps = self._token_usage.setdefault("steps", [])
        steps.append(step_usage)
        for k, v in step_usage.items():
            self._token_usage[k] = self._token_usage.get(k, 0) + v
        self._token_usage["peak_prompt_tokens"] = step_usage["prompt_tokens"]
        return result.text
        # ── To revert to cider HMInference, replace above block with: ──
        # code, text, stats = self._engine.complete(
        #     messages, pil_images, [], [],
        # )
        # prefill_time = stats.get("prefill_time", 0)
        # step_usage = {
        #     "prompt_tokens": 0,
        #     "generation_tokens": 0,
        # }
        # steps = self._token_usage.setdefault("steps", [])
        # steps.append(step_usage)
        # for k, v in step_usage.items():
        #     self._token_usage[k] = self._token_usage.get(k, 0) + v
        # return text

    # ─── Response parsing (from action_parser.py) ─────────────

    def _parse_response(self, text: str) -> dict:
        """Parse model output: extract <think>, <action_desp>, <action>."""
        think = self._extract_tag(text, "think") or ""
        action_desp = self._extract_tag(text, "action_desp") or ""
        action_raw = self._extract_tag(text, "action") or ""
        action = self._parse_action(action_raw) if action_raw else None
        return {
            "think": think.strip(),
            "action_desp": action_desp.strip(),
            "action": action,
            "raw": text,
        }

    def _extract_tag(self, text: str, tag: str) -> Optional[str]:
        m = self._re.search(rf"<{tag}>(.*?)</{tag}>", text, self._re.DOTALL)
        return m.group(1) if m else None

    def _parse_box(self, box_str: str) -> list:
        m = self._re.search(r"\((\d+)\s*,\s*(\d+)\)", box_str)
        if not m:
            return [0, 0]
        return [int(m.group(1)), int(m.group(2))]

    def _parse_action(self, action_str: str) -> Optional[dict]:
        """Parse action function call string into structured dict."""
        action_str = action_str.strip()
        m = self._re.match(r"(\w+)\((.*)\)$", action_str, self._re.DOTALL)
        if not m:
            return None

        func_name = m.group(1)
        args_str = m.group(2).strip()

        kwargs = {}
        for km in self._re.finditer(r"(\w+)\s*=\s*'(.*?)'", args_str, self._re.DOTALL):
            kwargs[km.group(1)] = km.group(2)

        if func_name in ("click", "doubleclick", "hover"):
            box = kwargs.get("start_box", "")
            return {"action": func_name, "coords": self._parse_box(box)}
        if func_name == "triple_click":
            box = kwargs.get("start_box", "")
            return {"action": "triple_click", "coords": self._parse_box(box)}
        if func_name == "right_single":
            box = kwargs.get("start_box", "")
            return {"action": "right_click", "coords": self._parse_box(box)}
        if func_name == "hotkey_click":
            box = kwargs.get("start_box", "")
            return {"action": "hotkey_click", "coords": self._parse_box(box), "key": kwargs.get("key", "")}
        if func_name == "type":
            return {"action": "type", "text": kwargs.get("content", "")}
        if func_name == "hotkey":
            return {"action": "hotkey", "key": kwargs.get("key", "")}
        if func_name == "scroll":
            box = kwargs.get("start_box", "")
            amount = kwargs.get("amount", "3")
            try:
                amount = int(amount)
            except (ValueError, TypeError):
                amount = 3
            result = {"action": "scroll", "direction": kwargs.get("direction", "down"), "amount": amount}
            if box:
                result["coords"] = self._parse_box(box)
            return result
        if func_name == "drag":
            return {
                "action": "drag",
                "start": self._parse_box(kwargs.get("start_box", "")),
                "end": self._parse_box(kwargs.get("end_box", "")),
            }
        if func_name == "wait":
            duration = kwargs.get("duration", "5")
            try:
                duration = float(duration)
            except (ValueError, TypeError):
                duration = 5.0
            return {"action": "wait", "duration": duration}
        if func_name == "finish":
            return {"action": "finish"}
        if func_name == "stop":
            return {"action": "stop", "reason": kwargs.get("reason", "")}
        if func_name == "call_user":
            return {"action": "call_user"}
        return None

    # ─── Action conversion: Qwen3-VL → Claude format ─────────

    def _norm_coord(self, x: int, y: int) -> list:
        """Convert [0,1000] normalised coords to actual screen pixel coordinates.

        Matches the ground truth in cua/action_executor.py:
            x = coords[0] / 1000 * screen_w
            y = coords[1] / 1000 * screen_h
        """
        return [int(x / 1000 * self.screen_size[0]),
                int(y / 1000 * self.screen_size[1])]

    def _make_tool_action(self, input_dict: dict) -> dict:
        """Wrap an input dict as a Claude-compatible tool_use action."""
        import uuid
        return {
            "name": "computer",
            "input": input_dict,
            "id": str(uuid.uuid4()),
            "action_type": "tool_use",
        }

    def _convert_action(self, action: dict) -> List[Dict[str, Any]]:
        """Convert parsed Qwen3-VL action to Claude-compatible action list."""
        act = action["action"]

        if act == "finish":
            return [{"action_type": "DONE"}]
        if act == "stop":
            return [{"action_type": "FAIL"}]
        if act == "call_user":
            return [{"action_type": "CALL_USER"}]

        if act == "click":
            coords = action.get("coords", [0, 0])
            return [self._make_tool_action({
                "action": "left_click",
                "coordinate": self._norm_coord(coords[0], coords[1]),
            })]

        if act == "doubleclick":
            coords = action.get("coords", [0, 0])
            return [self._make_tool_action({
                "action": "double_click",
                "coordinate": self._norm_coord(coords[0], coords[1]),
            })]

        if act == "triple_click":
            coords = action.get("coords", [0, 0])
            return [self._make_tool_action({
                "action": "triple_click",
                "coordinate": self._norm_coord(coords[0], coords[1]),
            })]

        if act == "right_click":
            coords = action.get("coords", [0, 0])
            return [self._make_tool_action({
                "action": "right_click",
                "coordinate": self._norm_coord(coords[0], coords[1]),
            })]

        if act == "hover":
            coords = action.get("coords", [0, 0])
            return [self._make_tool_action({
                "action": "mouse_move",
                "coordinate": self._norm_coord(coords[0], coords[1]),
            })]

        if act == "hotkey_click":
            coords = action.get("coords", [0, 0])
            key = action.get("key", "")
            return [self._make_tool_action({
                "action": "left_click",
                "coordinate": self._norm_coord(coords[0], coords[1]),
                "text": key,  # modifier key passed via text for normalize_actions
            })]

        if act == "type":
            return [self._make_tool_action({
                "action": "type",
                "text": action.get("text", ""),
            })]

        if act == "hotkey":
            return [self._make_tool_action({
                "action": "key",
                "text": action.get("key", ""),
            })]

        if act == "scroll":
            direction = action.get("direction", "down")
            amount = action.get("amount", 3)
            coords = action.get("coords")
            coordinate = self._norm_coord(coords[0], coords[1]) if coords else [640, 360]
            # Compensate for executor's SCROLL_MULTIPLIER (model already controls amount)
            multiplier = AUTOMATION_CONFIG["SCROLL_MULTIPLIER"]
            return [self._make_tool_action({
                "action": "scroll",
                "scroll_direction": direction,
                "coordinate": coordinate,
                "scroll_amount": max(1, amount // multiplier),
            })]

        if act == "drag":
            start = action.get("start", [0, 0])
            end = action.get("end", [0, 0])
            return [self._make_tool_action({
                "action": "left_click_drag",
                "start_coordinate": self._norm_coord(start[0], start[1]),
                "coordinate": self._norm_coord(end[0], end[1]),
            })]

        if act == "wait":
            duration = action.get("duration", 5)
            return [self._make_tool_action({
                "action": "wait",
                "duration": duration,
            })]

        # Fallback: unknown action → FAIL
        return [{"action_type": "FAIL"}]
