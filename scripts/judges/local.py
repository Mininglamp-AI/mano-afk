#!/usr/bin/env python3
"""Local model judge — evaluate task completion using the on-device VLM.

Takes a session directory (with trajectory screenshots and result.json),
an expected result description, and uses the local Qwen3-VL model to judge
whether the final screenshot matches the expected outcome.

Usage:
    # Judge a completed session
    python scripts/local_judge.py <session_dir> --expected-result "Recipe 'Pasta Carbonara' appears in the recipe library"

    # Specify model path
    python scripts/local_judge.py <session_dir> --expected-result "..." --model-path ~/Downloads/weights/Qwen3-VL-4B-ckpt12000-8bit

    # Use multiple screenshots (last N) for context
    python scripts/local_judge.py <session_dir> --expected-result "..." --images 3
"""

import argparse
import base64
import io
import json
import os
import sys
import time

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import get_default_model_path


JUDGE_SYSTEM_PROMPT = "你是一个严格的GUI测试评审员。你根据最后一张截图中实际显示的内容来判断预期结果是否达成。你不关心任务是如何执行的，只关心最终状态。"

JUDGE_USER_PROMPT = """\
请根据截图判断以下预期结果是否已经达成。

**重要：以最后一张截图为准。** 如果提供了多张截图，前面的截图仅供参考（展示操作过程），最后一张截图才是最终状态。

### 预期结果（判断依据）
{expected_result}

### 当前截图
{image_tags}

请严格按以下格式回答（不要省略任何标签）：
<think>分析最后一张截图的内容，与预期结果逐项对比</think>
<verdict>PASS 或 FAIL</verdict>
<reason>简要说明判断理由</reason>
"""


def load_session(session_dir: str) -> dict:
    """Load result.json from session directory."""
    result_path = os.path.join(session_dir, "result.json")
    with open(result_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_last_screenshots(session_dir: str, count: int = 1) -> list:
    """Get screenshots from trajectory as PIL Images.

    If count == 1: returns only the last screenshot.
    If count >= 2: returns the first screenshot + last (count-1) screenshots.
    This gives the judge both the initial state and final state.
    """
    trajectory_dir = os.path.join(session_dir, "trajectory")
    if not os.path.isdir(trajectory_dir):
        raise FileNotFoundError(f"No trajectory directory: {trajectory_dir}")

    pngs = sorted(
        [f for f in os.listdir(trajectory_dir) if f.endswith(".png")],
        key=lambda x: int(os.path.splitext(x)[0]),
    )
    if not pngs:
        raise FileNotFoundError(f"No screenshots in {trajectory_dir}")

    if count <= 1 or len(pngs) <= count:
        selected = pngs[-count:]
    else:
        # First screenshot (initial state) + last N-1 (final state)
        selected = [pngs[0]] + pngs[-(count - 1):]
    images = []
    for fname in selected:
        path = os.path.join(trajectory_dir, fname)
        img = Image.open(path)
        # Resize to model input width
        target_w = 1280  # model input width
        if img.width != target_w:
            ratio = target_w / img.width
            new_h = int(img.height * ratio)
            img = img.resize((target_w, new_h), Image.LANCZOS)
        images.append(img)
    return images, selected


def run_judge(model_path: str, task: str, expected_result: str,
              images: list, verbose: bool = False) -> dict:
    """Run the local model as a judge and return verdict."""
    import mlx.core as mx
    import mlx_vlm as pm
    import mlx_vlm.generate as _gen_mod
    import vlm_engine as _cq
    from vlm_engine import custom_generate

    # Patch generation_stream → mx.gpu for thread safety
    # Must patch both the mlx_vlm.generate module AND vlm_engine module
    # because `from X import Y` creates a local binding
    _gen_mod.generation_stream = mx.gpu
    _cq.generation_stream = mx.gpu

    resolved_path = os.path.expanduser(model_path)
    print(f"Loading model from {resolved_path} ...", file=sys.stderr)
    model, processor = pm.load(resolved_path)
    print("Model loaded.", file=sys.stderr)

    # Build image tags
    image_tags = "\n".join(f"<image>" for _ in images)

    user_text = JUDGE_USER_PROMPT.format(
        task=task,
        expected_result=expected_result,
        image_tags=image_tags,
    )

    messages = [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]
    prompt = processor.tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )

    # Replace <image> with vision tokens
    ph = "<image>"
    new_ph = "<|vision_start|><|image_pad|><|vision_end|>"
    pi = len(images)
    while pi > 0:
        pi -= 1
        pos = prompt.rfind(ph)
        if pos >= 0:
            prompt = prompt[:pos] + prompt[pos:].replace(ph, new_ph, 1)
        else:
            break

    # Run inference
    t0 = time.time()
    result = custom_generate(
        model, processor, prompt, images or None,
        max_tokens=1024, temperature=0.0, top_p=1.0,
        prefill_step_size=2048,
    )
    elapsed = time.time() - t0
    raw_text = result.text
    if verbose:
        print(f"\n[Raw output]\n{raw_text}\n", file=sys.stderr)

    # Parse response
    import re

    def _parse_verdict(text):
        # 1. Full tag: <verdict>PASS</verdict>
        m = re.search(r"<verdict>\s*(PASS|FAIL)\s*</verdict>", text, re.IGNORECASE)
        if m:
            return m.group(1).upper()
        # 2. Open tag only: <verdict>PASS
        m = re.search(r"<verdict>\s*(PASS|FAIL)", text, re.IGNORECASE)
        if m:
            return m.group(1).upper()
        # 3. Bare keywords
        if re.search(r"\bPASS\b", text):
            return "PASS"
        if re.search(r"\bFAIL\b", text):
            return "FAIL"
        # 4. Chinese keywords
        if re.search(r"符合预期|预期已达成|已达成|已完成任务|通过|成功", text):
            return "PASS"
        if re.search(r"不符合|未达成|失败|未满足", text):
            return "FAIL"
        return None

    verdict = _parse_verdict(raw_text)

    # Retry once if verdict not found
    if verdict is None:
        print("Judge verdict unclear, retrying...", file=sys.stderr)
        t0_retry = time.time()
        result_retry = custom_generate(
            model, processor, prompt, images or None,
            max_tokens=1024, temperature=0.0, top_p=1.0,
            prefill_step_size=2048,
        )
        elapsed += time.time() - t0_retry
        raw_text_retry = result_retry.text
        if verbose:
            print(f"\n[Retry raw output]\n{raw_text_retry}\n", file=sys.stderr)
        verdict = _parse_verdict(raw_text_retry)
        if verdict is not None:
            raw_text = raw_text_retry

    # Final fallback: record UNKNOWN but treat as PASS
    if verdict is None:
        verdict = "UNKNOWN"

    think = ""
    m = re.search(r"<think>(.*?)</think>", raw_text, re.DOTALL)
    if m:
        think = m.group(1).strip()

    reason = ""
    m = re.search(r"<reason>(.*?)</reason>", raw_text, re.DOTALL)
    if m:
        reason = m.group(1).strip()
    elif think:
        # Use the last sentence of think as reason if no <reason> tag
        sentences = [s.strip() for s in re.split(r'[。；\n]', think) if s.strip()]
        if sentences:
            reason = sentences[-1]

    return {
        "verdict": verdict,
        "reason": reason,
        "think": think,
        "elapsed": round(elapsed, 2),
        "raw": raw_text,
    }


def main():
    parser = argparse.ArgumentParser(description="Local model judge for GUI task evaluation")
    parser.add_argument("session_dir", help="Session directory with trajectory/ and result.json")
    parser.add_argument("--expected-result", required=True, help="Expected result description")
    parser.add_argument("--model-path", default=None, help="Model weights path (default: config)")
    parser.add_argument("--images", type=int, default=1, help="Number of final screenshots to use (default: 1)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print raw model output")
    args = parser.parse_args()

    session_dir = os.path.expanduser(args.session_dir)
    model_path = args.model_path or get_default_model_path()
    if not model_path:
        print("Local model path not configured. Set it with:", file=sys.stderr)
        print("  mano-afk config --set default-model-path <path>", file=sys.stderr)
        sys.exit(1)

    # Load session
    session_data = load_session(session_dir)
    task = session_data["task"]

    # Get screenshots
    images, filenames = get_last_screenshots(session_dir, args.images)

    print(f"Session: {os.path.basename(session_dir)}", file=sys.stderr)
    print(f"Task: {task}", file=sys.stderr)
    print(f"Expected: {args.expected_result}", file=sys.stderr)
    print(f"Screenshots: {filenames}", file=sys.stderr)
    print(f"Model: {model_path}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Run judge
    result = run_judge(
        model_path=model_path,
        task=task,
        expected_result=args.expected_result,
        images=images,
        verbose=args.verbose,
    )

    # Output
    print(f"\n{'=' * 60}")
    print(f"Task: {task}")
    print(f"Expected: {args.expected_result}")
    print(f"Verdict: {result['verdict']}")
    print(f"Reason: {result['reason']}")
    print(f"Time: {result['elapsed']}s")
    print(f"{'=' * 60}")

    # Write judge results back into result.json under "judge" key
    result_path = os.path.join(session_dir, "result.json")
    try:
        with open(result_path, "r", encoding="utf-8") as f:
            session_result = json.load(f)
    except Exception:
        session_result = {}

    session_result["judge"] = {
        "verdict": result["verdict"],
        "reason": result["reason"],
        "expected_result": args.expected_result,
        "elapsed_sec": result["elapsed"],
        "model": os.path.basename(os.path.expanduser(model_path)),
        "token_usage": result.get("token_usage", {}),
    }

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(session_result, f, indent=4, ensure_ascii=False)

    # Also output JSON for programmatic use
    output = {
        "session": os.path.basename(session_dir),
        "task": task,
        "verdict": result["verdict"],
        "reason": result["reason"],
        "elapsed": result["elapsed"],
        "token_usage": result.get("token_usage", {}),
    }
    print(f"\n{json.dumps(output, indent=2, ensure_ascii=False)}")

    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
