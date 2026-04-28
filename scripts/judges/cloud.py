#!/usr/bin/env python3
"""Judge — evaluate task completion via Anthropic Messages API.

Takes a session directory (with trajectory screenshots and result.json),
an expected result description, and uses an LLM to judge whether the task
succeeded, with detailed failure classification.

Usage:
    python scripts/cloud_judge.py <session_dir> --expected-result "..."

    # Override number of screenshots (default: 8)
    python scripts/cloud_judge.py <session_dir> --expected-result "..." --images 5

Environment:
    ANTHROPIC_API_KEY   — API key for the gateway
    ANTHROPIC_BASE_URL  — Gateway base URL (defaults to https://api.anthropic.com)
"""

import argparse
import asyncio
import base64
import json
import logging
import os
import re
import sys
import time

from anthropic import AsyncAnthropic

logger = logging.getLogger("mano.cloud_judge")

EVAL_SCREENSHOT_COUNT = 8

# Model selection: auto-prefix "vertexai/" when using llm-gateway
_BASE_MODEL = "claude-opus-4-6"

SYSTEM_PROMPT = """
## Role

You are an automatic software testing validator. Given a task description, expected result, agent action history, and screenshots, determine whether the task succeeded and classify any failure.

## Inputs

1. Task description (what the agent was asked to do)
2. Expected result (what success looks like)
3. Agent action history (thoughts and actions taken)
4. Screenshots from final steps (chronological order, last = final state)

## Success Definition

A task succeeds when:
- The expected result is clearly satisfied (screenshots are primary evidence, action history is secondary)
- AND the page has no severe visual or interaction defects

If the expected result is met but the page is visually broken, return VISUAL_DEFECT.
If the agent's notes indicate it cannot be determined from screenshots alone, use action history to fill gaps.

## Failure Types

Choose exactly ONE type when success = false. When multiple issues coexist, pick the **root cause** — the one that, if fixed, would most likely make the others disappear.

### App-side failures (model_failure = false)

| Type | When to use |
|---|---|
| UNEXPECTED_EXCEPTION | Page shows an error state: 404, 500, crash screen, "something went wrong" |
| UI_MALFUNCTION | A visible UI component does not respond correctly to interaction: clicks have no effects, scrolling doesn't work, element is blocked by an overlay, or component behavior contradicts its label |
| UNMATCHED_OUTCOME | The task ran to completion but the final state does not match the expected result |
| VISUAL_DEFECT | The expected result is functionally met, but the page has severe visual problems: broken layout, missing/broken assets, grossly mis-sized elements, or empty content areas |
| BAD_INSTRUCTION | The instruction references a UI path or component that does not exist in the software |
| MAX_STEPS_EXCEED | The step limit was reached before task completion |
| MODEL_ABORTION | The agent explicitly decided the task is infeasible and aborted |

### Model-side failures (model_failure = true)

| Type | When to use |
|---|---|
| MODEL_REASONING | The agent's strategy or planning is clearly wrong |
| EXECUTION_FAILURE | The agent had the right plan but its own actions failed (mis-click, typo) — not an app bug |

### Disambiguation

- **UI_MALFUNCTION vs EXECUTION_FAILURE**: If the agent clicked the correct target but the app didn't respond, it's UI_MALFUNCTION (app bug). If the agent clicked the wrong target or used the wrong interaction method for a standard control, it's EXECUTION_FAILURE (agent error). When in doubt, check: would a human clicking the same element also fail? If yes → UI_MALFUNCTION. If only the agent fails → EXECUTION_FAILURE.
- **UI_MALFUNCTION vs UNMATCHED_OUTCOME**: If the agent's action history shows repeated failed interactions with a specific component, prefer UI_MALFUNCTION. If the outcome is simply wrong without clear interaction failures, use UNMATCHED_OUTCOME.
- **VISUAL_DEFECT vs UNMATCHED_OUTCOME**: VISUAL_DEFECT applies only when the expected result IS functionally achieved but the page looks broken. If the expected result itself is not met, use UNMATCHED_OUTCOME regardless of visual issues.

## Visual Quality Check (MANDATORY)

**You MUST perform this check on every evaluation, even when the expected result is fully met.** Examine the final screenshot and answer each question:

1. **Layout** — Is any major UI section missing, collapsed to zero height, or invisible? Are elements overlapping or overflowing?
2. **Assets** — Are there broken image placeholders, missing icons, or font rendering failures?
3. **Sizing** — Are any elements grossly mis-sized?
4. **Content areas** — Are there large empty/blank regions where content should be visible?

If ANY check reveals a severe problem, return VISUAL_DEFECT even if the expected result is functionally satisfied. Minor CSS differences are NOT defects.

## Confidence

0.85-1.0 = very clear | 0.65-0.84 = strong evidence | 0.40-0.64 = moderate | 0.20-0.39 = weak

## Output Format (Strict)

Return only JSON:
{
  "success": true/false,
  "failure_type": null | "MODEL_REASONING" | "EXECUTION_FAILURE" | "MAX_STEPS_EXCEED" | "MODEL_ABORTION" | "BAD_INSTRUCTION" | "UNEXPECTED_EXCEPTION" | "UNMATCHED_OUTCOME" | "UI_MALFUNCTION" | "VISUAL_DEFECT",
  "reason": "...",
  "evidence": "...",
  "confidence": <0-1>,
  "model_failure": true/false
}
"""


def _resolve_model() -> str:
    """Prefix vertexai/ when using llm-gateway, matching agent.py convention."""
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    if "llm-gateway" in base_url:
        return f"vertexai/{_BASE_MODEL}"
    return _BASE_MODEL


def get_last_n_screenshot_paths(session_dir: str, n: int = EVAL_SCREENSHOT_COUNT) -> list[str]:
    trajectory_dir = os.path.join(session_dir, "trajectory")
    files = sorted(
        [f for f in os.listdir(trajectory_dir) if f.endswith(".png")],
        key=lambda f: int(f.split(".")[0]),
    )
    selected = files[-n:] if len(files) >= n else files
    return [os.path.join(trajectory_dir, f) for f in selected]


def load_image_as_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def extract_json(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = content.find(start_char)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(content[start:], start):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(content[start : i + 1])
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"No valid JSON found in content: {content[:200]}")


async def run_cloud_judge(
    task: str,
    expected_result: str,
    history_resps: list,
    screenshot_paths: list[str],
    max_retries: int = 3,
) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    model = _resolve_model()

    client = AsyncAnthropic(api_key=api_key, base_url=base_url)

    screenshot_b64_list = [load_image_as_base64(p) for p in screenshot_paths]

    # Build user message content with text + images (Anthropic format)
    user_content = [
        {
            "type": "text",
            "text": (
                f"## User Input Data\n"
                f"- task description: {task}\n"
                f"- expected result: {expected_result}\n"
                f"- history of thoughts and actions: {history_resps}\n"
                f"- screenshots: {len(screenshot_b64_list)} screenshot(s) from the final steps, "
                f"in chronological order (last = final state)"
            ),
        }
    ]
    for b64_img in screenshot_b64_list:
        user_content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64_img,
                },
            }
        )

    messages = [{"role": "user", "content": user_content}]

    t0 = time.time()
    for attempt in range(max_retries):
        try:
            response = await client.messages.create(
                model=model,
                system=SYSTEM_PROMPT,
                messages=messages,
                temperature=0.1,
                max_tokens=4096,
            )

            # Extract text from response content blocks
            ans_str = ""
            for block in response.content:
                if block.type == "text":
                    ans_str += block.text

            elapsed = round(time.time() - t0, 2)

            # Extract thinking if present (from <thinking> tags)
            reason_str = ""
            m = re.search(r"<thinking>(.*?)</thinking>", ans_str, re.DOTALL)
            if m:
                reason_str = m.group(1)

            verdict = extract_json(ans_str)

            usage_dict = {}
            if response.usage:
                usage_dict = {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                }

            return {
                "verdict": verdict,
                "think": reason_str,
                "elapsed_sec": elapsed,
                "screenshots_used": len(screenshot_b64_list),
                "token_usage": usage_dict,
                "model": model,
            }

        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Judge attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(3)
            else:
                raise


def main():
    parser = argparse.ArgumentParser(description="Judge for GUI task evaluation")
    parser.add_argument("session_dir", help="Session directory with trajectory/ and result.json")
    parser.add_argument("--expected-result", required=True, help="Expected result description")
    parser.add_argument("--images", type=int, default=EVAL_SCREENSHOT_COUNT,
                        help=f"Number of final screenshots to use (default: {EVAL_SCREENSHOT_COUNT})")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print thinking output")
    args = parser.parse_args()

    session_dir = os.path.expanduser(args.session_dir)
    result_path = os.path.join(session_dir, "result.json")

    with open(result_path, "r", encoding="utf-8") as f:
        session_result = json.load(f)

    task = session_result["task"]
    history_resps = session_result.get("history_resps", [])

    screenshot_paths = get_last_n_screenshot_paths(session_dir, args.images)

    model = _resolve_model()
    print(f"Session:     {os.path.basename(session_dir)}", file=sys.stderr)
    print(f"Task:        {task}", file=sys.stderr)
    print(f"Expected:    {args.expected_result}", file=sys.stderr)
    print(f"Screenshots: {[os.path.basename(p) for p in screenshot_paths]}", file=sys.stderr)
    print(f"Model:       {model}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    result = asyncio.run(
        run_cloud_judge(task, args.expected_result, history_resps, screenshot_paths)
    )

    if args.verbose and result["think"]:
        print(f"\n[Thinking]\n{result['think']}\n", file=sys.stderr)

    verdict = result["verdict"]
    print(f"\n{'=' * 60}")
    print(f"Task:        {task}")
    print(f"Expected:    {args.expected_result}")
    print(f"Success:     {verdict.get('success')}")
    print(f"Failure:     {verdict.get('failure_type')}")
    print(f"Reason:      {verdict.get('reason')}")
    print(f"Evidence:    {verdict.get('evidence')}")
    print(f"Confidence:  {verdict.get('confidence')}")
    print(f"Model fault: {verdict.get('model_failure')}")
    print(f"Time:        {result['elapsed_sec']}s")
    print(f"{'=' * 60}")

    # Write back to result.json under "judge" key
    session_result["judge"] = {
        "success": verdict.get("success"),
        "failure_type": verdict.get("failure_type"),
        "reason": verdict.get("reason"),
        "evidence": verdict.get("evidence"),
        "confidence": verdict.get("confidence"),
        "model_failure": verdict.get("model_failure"),
        "expected_result": args.expected_result,
        "elapsed_sec": result["elapsed_sec"],
        "screenshots_used": result["screenshots_used"],
        "model": result.get("model", model),
        "token_usage": result["token_usage"],
    }

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(session_result, f, indent=4, ensure_ascii=False)

    print(f"\nWritten to {result_path}")
    return 0 if verdict.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
