"""ClaudeAgent — cloud CUA agent using Anthropic API."""

import asyncio
import base64
import io
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union, cast

from anthropic import (
    AsyncAnthropic,
    APIError as AnthropicAPIError,
    APIResponseValidationError,
    APIStatusError,
)
from anthropic.types.beta import (
    BetaMessageParam,
    BetaTextBlockParam,
)
from PIL import Image

from agents.base import BaseAgent
from config import AGENT_CONFIG, AUTOMATION_CONFIG, get_api_key
from utils import (
    COMPUTER_USE_BETA_FLAG,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_WINDOWS,
    SYSTEM_PROMPT_MACOS,
    _response_to_params,
    _inject_prompt_caching,
    _maybe_filter_to_n_most_recent_images,
)

logger = logging.getLogger("mano.agent")

class ClaudeAgent(BaseAgent):
    """
    In-process Claude CUA agent using AsyncAnthropic.
    Migrated from AnthropicAgent in backend/model.py.
    """

    agent_type = "claude"

    def __init__(
        self,
        platform: str = "Darwin",
        model: str = None,
        max_tokens: int = None,
        api_key: str = None,
        system_prompt_suffix: str = "",
        only_n_most_recent_images: Optional[int] = None,
        screen_size: tuple[int, int] = (1280, 720),
        no_thinking: bool = False,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ):
        super().__init__()
        self.platform = platform
        self.logger = logger

        # Use config defaults
        if model is None:
            base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
            if "llm-gateway" in base_url:
                model = f"vertexai/{AGENT_CONFIG['MODEL']}"
            else:
                model = AGENT_CONFIG["MODEL"]
            logger.info(f"Auto-selected model: {model} (base_url: {base_url})")
        self.model_name = model
        self.max_tokens = max_tokens or AGENT_CONFIG["MAX_TOKENS"]
        self.api_key = api_key or get_api_key()
        self.system_prompt_suffix = system_prompt_suffix
        self.only_n_most_recent_images = only_n_most_recent_images if only_n_most_recent_images is not None else AGENT_CONFIG["N_MOST_RECENT_IMAGES"]
        self.messages: list[BetaMessageParam] = []
        self.screen_size = screen_size
        self.no_thinking = no_thinking
        self.temperature = temperature
        self.top_p = top_p

        self.client = AsyncAnthropic(
            base_url=os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            api_key=self.api_key,
            timeout=AGENT_CONFIG["CLIENT_TIMEOUT"],
            max_retries=4,
        ).with_options(default_headers={"anthropic-beta": COMPUTER_USE_BETA_FLAG})

    def _get_sampling_params(self):
        params = {}
        if self.temperature is not None:
            params["temperature"] = self.temperature
        if self.top_p is not None:
            params["top_p"] = self.top_p
        return params

    async def predict(
        self,
        task_instruction: str,
        tool_results: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        _t0 = time.time()

        # Save screenshot from tool_results for trajectory
        image_path = self._save_screenshot_from_tool_results(tool_results)

        # System prompt
        system_prompt = self._select_system_prompt()
        system_block = BetaTextBlockParam(
            type="text",
            text=f"{system_prompt}{' ' + self.system_prompt_suffix if self.system_prompt_suffix else ''}",
        )

        # First turn: add initial user message
        if not self.messages:
            self._append_initial_user_message(task_instruction)

        # Inject tool_results from executor
        if tool_results:
            self._inject_tool_results(tool_results)

        # Model call config
        betas = [COMPUTER_USE_BETA_FLAG]
        image_truncation_threshold = 10

        _inject_prompt_caching(self.messages)
        system_block["cache_control"] = {"type": "ephemeral"}

        if self.only_n_most_recent_images:
            _maybe_filter_to_n_most_recent_images(
                self.messages,
                self.only_n_most_recent_images,
                min_removal_threshold=image_truncation_threshold,
            )

        tool_config = {
            "name": "computer",
            "type": "computer_20251124",
            "display_width_px": self.screen_size[0],
            "display_height_px": self.screen_size[1],
            "display_number": 1,
        }
        minimize_panel_tool = {
            "name": "minimize_panel",
            "description": "Minimize the task status widget to a tiny bar in the bottom-right corner. Use this when the widget is overlapping an important UI component you need to interact with.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        }

        tools = [tool_config, minimize_panel_tool]

        # Thinking mode
        if self.no_thinking:
            extra_body = {}
            actual_max_tokens = self.max_tokens
        else:
            budget_tokens = AGENT_CONFIG["THINKING_BUDGET"]
            if self.max_tokens <= budget_tokens:
                actual_max_tokens = budget_tokens + 500
            else:
                actual_max_tokens = self.max_tokens
            extra_body = {"thinking": {"type": "enabled", "budget_tokens": budget_tokens}}

        # Call API
        response = await self._call_anthropic_with_retries(
            system_block=system_block,
            tools=tools,
            betas=betas,
            extra_body=extra_body,
            actual_max_tokens=actual_max_tokens,
        )

        # Parse response
        response_params = _response_to_params(response)
        raw_response_str = self._extract_raw_response_string(response)

        # Record per-step token usage
        if hasattr(response, "usage") and response.usage:
            u = response.usage
            step_usage = {
                "input_tokens": u.input_tokens or 0,
                "output_tokens": u.output_tokens or 0,
                "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
                "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
            }
            steps = self._token_usage.setdefault("steps", [])
            steps.append(step_usage)
            for k, v in step_usage.items():
                self._token_usage[k] = self._token_usage.get(k, 0) + v

        self.messages.append({"role": "assistant", "content": response_params})

        reasoning, actions = self._parse_response_blocks(response_params, raw_response_str)
        self._save_history(reasoning, actions, elapsed=time.time() - _t0)

        # Save debug image with action overlay
        if actions and image_path:
            try:
                action_str = actions[0].get("input", {}).get("action", "unknown")
                text_content = actions[0].get("input", {}).get("text")
                if text_content:
                    action_str = f"{action_str}: {text_content}"
                draw_point = actions[0].get("input", {}).get("coordinate")
                self._save_debug_image(image_path, draw_point, action_str)
            except Exception as e:
                logger.warning(f"[{self.session_id}] Failed to save debug image: {e}")

        return reasoning, actions

    def agree_to_continue(self) -> None:
        self.messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": "允许进行计算机操作，请继续"},
            ],
        })

    def _extract_raw_response_string(self, response) -> str:
        raw_response_str = ""
        if response.content:
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    raw_response_str += f"[TEXT] {block.text}\n"
                elif hasattr(block, "thinking") and block.thinking:
                    raw_response_str += f"[THINKING] {block.thinking}\n"
                elif hasattr(block, "name") and hasattr(block, "input"):
                    raw_response_str += f"[TOOL_USE] {block.name}: {block.input}\n"
                else:
                    raw_response_str += f"[OTHER] {str(block)}\n"
        return raw_response_str.strip()

    def _select_system_prompt(self) -> str:
        if self.platform.lower().startswith("win"):
            return SYSTEM_PROMPT_WINDOWS
        elif self.platform.lower().startswith("darwin"):
            return SYSTEM_PROMPT_MACOS
        else:
            return SYSTEM_PROMPT

    def _compress_image(self, image_bytes: bytes, max_size_mb: float = 5) -> bytes:
        max_size = int(max_size_mb * 1024 * 1024)

        with Image.open(io.BytesIO(image_bytes)) as img:
            resized = img.resize((1280, 720), Image.Resampling.LANCZOS)

            out = io.BytesIO()
            resized.save(out, format="PNG")
            b = out.getvalue()
            if len(b) <= max_size:
                return b

            out = io.BytesIO()
            resized.save(out, format="PNG", optimize=True, compress_level=9)
            b2 = out.getvalue()
            if len(b2) <= max_size:
                return b2

            rgb = resized.convert("RGB")
            bq = b2
            for colors in (256, 128, 64):
                q = rgb.quantize(colors=colors, dither=Image.Dither.NONE)
                out = io.BytesIO()
                q.save(out, format="PNG", optimize=True, compress_level=9)
                bq = out.getvalue()
                if len(bq) <= max_size:
                    return bq

            return bq

    def _append_initial_user_message(self, task_instruction: str):
        self.messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": task_instruction},
            ],
        })

    def _pending_tool_use_ids_from_last_assistant(self) -> List[str]:
        if not self.messages:
            return []
        last_assistant = None
        for m in reversed(self.messages):
            if m.get("role") == "assistant":
                last_assistant = m
                break
        if not last_assistant:
            return []
        content = last_assistant.get("content") or []
        return [b["id"] for b in content if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id")]

    def _inject_tool_results(self, tool_results: List[Dict[str, Any]]):
        pending_ids = set(self._pending_tool_use_ids_from_last_assistant())
        if not pending_ids:
            return

        for tr in tool_results:
            tid = tr.get("tool_use_id") or tr.get("id")
            if not tid or tid not in pending_ids:
                continue

            status = (tr.get("status") or "success").lower()
            ok = status == "success"
            text = tr.get("output") or ("" if ok else tr.get("error")) or ("Success" if ok else "Error")

            screenshot_bytes = None
            b64 = tr.get("screenshot_b64")
            if b64:
                try:
                    screenshot_bytes = base64.b64decode(b64)
                except Exception:
                    screenshot_bytes = None

            if not ok and not text.lower().startswith("error"):
                text = f"ERROR: {text}"

            self._add_tool_result(
                tool_use_id=tid,
                ok=ok,
                text=text,
                screenshot=screenshot_bytes,
            )

    def _add_tool_result(
        self,
        tool_use_id: str,
        *,
        ok: bool = True,
        text: Optional[str] = None,
        output: Optional[Union[str, Dict[str, Any], list]] = None,
        screenshot: Optional[bytes] = None,
        screenshot_b64: Optional[str] = None,
    ) -> None:
        if not tool_use_id or not isinstance(tool_use_id, str):
            raise ValueError("tool_use_id must be a non-empty string")

        parts = []
        if text is None:
            text = "Success" if ok else "Error"
        parts.append({"type": "text", "text": text})

        if output is not None:
            if isinstance(output, (dict, list)):
                output_text = json.dumps(output, ensure_ascii=False)
            else:
                output_text = str(output)
            parts.append({"type": "text", "text": output_text})

        img_b64 = None
        if screenshot_b64:
            img_b64 = screenshot_b64
        elif screenshot is not None:
            img_b64 = base64.b64encode(screenshot).decode("utf-8")

        if img_b64:
            img_bytes = base64.b64decode(img_b64)
            compressed_bytes = self._compress_image(img_bytes, max_size_mb=5)
            compressed_b64 = base64.b64encode(compressed_bytes).decode("utf-8")
            parts.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": compressed_b64,
                },
            })

        if not ok:
            parts = [part for part in parts if part.get("type") == "text"]

        tool_result_block: Dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": parts,
            "is_error": not ok,
        }

        self.messages.append({
            "role": "user",
            "content": [tool_result_block],
        })

    def _reduce_images_for_size_limit(self):
        current = self.only_n_most_recent_images or 10
        new = max(1, current // 2)
        logger.warning(f"Size limit hit, reducing images {current} -> {new}")
        self.only_n_most_recent_images = new
        _maybe_filter_to_n_most_recent_images(self.messages, new, min_removal_threshold=2)

    async def _call_anthropic_with_retries(
        self,
        system_block,
        tools,
        betas,
        extra_body,
        actual_max_tokens: int,
    ):
        retry_times = AGENT_CONFIG["API_RETRY_TIMES"]
        retry_interval = AGENT_CONFIG["API_RETRY_INTERVAL"]

        for attempt in range(retry_times):
            try:
                response = await self.client.beta.messages.create(
                    max_tokens=actual_max_tokens,
                    messages=self.messages,
                    model=self.model_name,
                    system=[system_block],
                    tools=tools,
                    betas=betas,
                    extra_body=extra_body,
                    **self._get_sampling_params(),
                )
                return response
            except (AnthropicAPIError, APIStatusError, APIResponseValidationError) as e:
                msg = str(e)
                status_code = getattr(e, "status_code", None)

                if "request size" in msg.lower() or "request_too_large" in msg:
                    self._reduce_images_for_size_limit()
                    if attempt < retry_times - 1:
                        await asyncio.sleep(retry_interval)
                        continue

                if status_code and 400 <= status_code < 500 and status_code != 429:
                    logger.error(f"Non-retryable API error ({status_code}): {msg}")
                    raise

                logger.warning(f"Anthropic API error (attempt {attempt + 1}/{retry_times}): {msg}")
                if attempt < retry_times - 1:
                    await asyncio.sleep(retry_interval)
                else:
                    raise

    def _parse_response_blocks(self, response_params: List[Dict[str, Any]], raw_response_str: str):
        actions: List[Dict[str, Any]] = []
        reasonings: List[str] = []

        for block in response_params:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                tool_name = block.get("name")
                tool_input = cast(Dict[str, Any], block.get("input") or {})
                actions.append({
                    "name": tool_name,
                    "input": tool_input,
                    "id": block.get("id"),
                    "action_type": "tool_use",
                    "raw_response": raw_response_str,
                })
            elif block.get("type") == "text":
                txt = block.get("text") or ""
                if txt:
                    reasonings.append(txt)

        reasoning = reasonings[0] if reasonings else ""

        if raw_response_str and "[INFEASIBLE]" in raw_response_str:
            actions = [{"action_type": "FAIL", "raw_response": raw_response_str}]

        if not actions:
            actions = [{"action_type": "DONE", "raw_response": raw_response_str}]

        return reasoning, actions

