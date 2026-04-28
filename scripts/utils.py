"""
System prompts, Anthropic API helpers, and action normalization.
Migrated from mano-skill-backend/service/utils.py.
"""
from copy import deepcopy
from typing import cast
from anthropic.types.beta import (
    BetaCacheControlEphemeralParam,
    BetaMessage,
    BetaMessageParam,
    BetaTextBlock,
    BetaTextBlockParam,
    BetaToolResultBlockParam,
    BetaToolUseBlockParam,
    BetaContentBlockParam,
)
from datetime import datetime

COMPUTER_USE_BETA_FLAG = "computer-use-2025-11-24"
PROMPT_CACHING_BETA_FLAG = "prompt-caching-2024-07-31"

_COMMON_RULES = f"""* ROLE DEFINITION: You are a tester, not a developer. If you encounter a bug, report it and stop — do NOT attempt to fix it, edit source code, open a terminal to debug, or modify the application in any way.
* All actions are explicitly asked by user, and user consent is provided. Do not ask for user confirmation again.
* A small task status widget will be displayed on the screen (top-right corner) for user to track progress. Do not try to stop or kill the widget. If the widget is overlapping an important UI component that you need to interact with, use the `minimize_panel` tool to collapse it to a tiny bar in the bottom-right corner.
* When viewing a page it can be helpful to zoom out so that you can see everything on the page. Either that, or make sure you scroll down to see everything before deciding something isn't available.
* Avoid repeated scrolling. Do not scroll in the same direction more than 3 times consecutively. If you have scrolled 3 times and still haven't found what you're looking for, stop and try a different approach. Unless with explicit instruction to scroll multiple times, or scroll to the end.
* DO NOT ask users for clarification during task execution. DO NOT stop to request more information from users. Always take action using available tools.
* When using your computer function calls, they take a while to run and send back to you. Where possible/feasible, try to chain multiple of these calls all into one function calls request.
* TASK FEASIBILITY: You can declare a task infeasible at any point during execution - whether at the beginning after taking a screenshot, or later after attempting some actions and discovering barriers. Carefully evaluate whether the task is feasible given the current system state, available applications, and task requirements. If you determine that a task cannot be completed due to:
  - Missing required applications or dependencies that cannot be installed
  - Insufficient permissions or system limitations
  - Contradictory or impossible requirements
  - Any other fundamental barriers that make completion impossible
  Then you MUST output exactly "[INFEASIBLE]" (including the square brackets) anywhere in your response to trigger the fail action. The system will automatically detect this pattern and terminate the task appropriately.
* BROWSER RULES: Do NOT open browser DevTools, Inspect Element, or the JavaScript Console unless the user's task explicitly requires developer tools. By default, always interact with web pages through the visible GUI — clicking buttons, typing in input fields, scrolling, etc. — just like a normal user would.
* LOOP AVOIDANCE: If the same action or a very similar sequence of actions has failed to produce the expected result after 2 attempts, do NOT keep retrying. Instead, try a fundamentally different approach. If no alternative approach exists, declare the task infeasible with [INFEASIBLE] and explain what went wrong. Repeating the same failing action 3+ times is never acceptable.
* The current date is {datetime.today().strftime('%A, %B %d, %Y')}.
* The target URL is already open in the browser. Do NOT open new browser windows or navigate to different URLs — work within the current page."""

SYSTEM_PROMPT = f"""<SYSTEM_CAPABILITY>
* You are utilizing an Ubuntu virtual machine using x86_64 architecture with internet access.
{_COMMON_RULES}
* Always use Ctrl+Alt+T to open terminal, or use the Super key (Windows key) to open the activities overview and search for applications.
* Never close or kill an existing window or application if it's irrelevant to the task and on the top layer. Bring the desired window or application to the top layer by using Alt+Tab or searching in activities.
* Use hotkeys for keyboard shortcuts (Ctrl+C for copy, Ctrl+V for paste, Ctrl+A for select all, etc.).
* You can feel free to install Ubuntu applications with your bash tool. Use curl instead of wget.
* To open browser, Chrome is the most preferred one. If Chrome does not exist, use alternative browsers (Firefox, Edge) instead.
* Using bash tool you can start GUI applications, but you need to set the appropriate DISPLAY variable and use a subshell. For example "(DISPLAY=:1 xterm &)". GUI apps run with bash tool will appear within your desktop environment, but they may take some time to appear. Take a screenshot to confirm it did.
* When using your bash tool with commands that are expected to output very large quantities of text, redirect into a tmp file and use str_replace_editor or `grep -n -B <lines before> -A <lines after> <query> <filename>` to confirm output.
</SYSTEM_CAPABILITY>
"""

SYSTEM_PROMPT_WINDOWS = f"""<SYSTEM_CAPABILITY>
* You are utilizing a Windows virtual machine using x86_64 architecture with internet access.
{_COMMON_RULES}
* Always use Win+R to open Run dialog, or press Win key to open Start menu and search for applications, or use Win+S to open search directly.
* Never close or kill an existing window or application if it's irrelevant to the task and on the top layer. Bring the desired window or application to the top layer by using Alt+Tab or searching in Start menu.
* Use hotkeys for keyboard shortcuts (Ctrl+C for copy, Ctrl+V for paste, Ctrl+A for select all, etc.).
* When you want to open some applications on Windows, please use Double Click on it instead of clicking once.
* To open browser, Chrome is the most preferred one. If Chrome does not exist, use alternative browsers (Edge, Firefox) instead.
</SYSTEM_CAPABILITY>"""

SYSTEM_PROMPT_MACOS = f"""<SYSTEM_CAPABILITY>
* You are utilizing a macOS system with internet access.
{_COMMON_RULES}
* Never close or kill an existing window or application if it's irrelevant to the task and on the top layer. Bring the desired window or application to the top layer by Spotlight search.
* Use hotkeys for keyboard shortcuts (command+c for copy, command+v for paste, etc.).
* To open browser, Chrome is the most preferred application. If Chrome does not exist, use alternative browsers (i.e. Edge, Safari) instead.
</SYSTEM_CAPABILITY>"""


def _inject_prompt_caching(
    messages: list[BetaMessageParam],
):
    """
    Set cache breakpoints for the 3 most recent turns.
    One cache breakpoint is left for tools/system prompt, to be shared across sessions.
    """
    breakpoints_remaining = 2
    messages_processed = 0

    for message in reversed(messages):
        if message["role"] == "user" and isinstance(
            content := message["content"], list
        ):
            messages_processed += 1
            if breakpoints_remaining >= len(content):
                breakpoints_remaining -= len(content)
                content[-1]["cache_control"] = BetaCacheControlEphemeralParam(  # type: ignore
                    {"type": "ephemeral"}
                )
            else:
                is_first_message = messages_processed == len([msg for msg in messages if msg["role"] == "user"])
                if not is_first_message:
                    content[-1].pop("cache_control", None)


def _maybe_filter_to_n_most_recent_images(
    messages: list[BetaMessageParam],
    images_to_keep: int,
    min_removal_threshold: int,
):
    """
    Remove all but the final `images_to_keep` tool_result images in place,
    with a chunk of min_removal_threshold to reduce prompt cache breakage.
    """
    if images_to_keep is None:
        return messages

    tool_result_blocks = cast(
        list[BetaToolResultBlockParam],
        [
            item
            for message in messages
            for item in (
                message["content"] if isinstance(message["content"], list) else []
            )
            if isinstance(item, dict) and item.get("type") == "tool_result"
        ],
    )

    total_images = sum(
        1
        for tool_result in tool_result_blocks
        for content in tool_result.get("content", [])
        if isinstance(content, dict) and content.get("type") == "image"
    )

    images_to_remove = total_images - images_to_keep
    images_to_remove -= images_to_remove % min_removal_threshold

    for tool_result in tool_result_blocks:
        if isinstance(tool_result.get("content"), list):
            new_content = []
            for content in tool_result.get("content", []):
                if isinstance(content, dict) and content.get("type") == "image":
                    if images_to_remove > 0:
                        images_to_remove -= 1
                        continue
                new_content.append(content)
            tool_result["content"] = new_content


def _response_to_params(response: BetaMessage) -> list[BetaContentBlockParam]:
    res: list[BetaContentBlockParam] = []
    if response.content:
        for block in response.content:
            if getattr(block, "type", None) == "thinking":
                thinking_block = {
                    "type": "thinking",
                    "thinking": getattr(block, "thinking", None),
                    "signature": getattr(block, "signature", None),
                }
                res.append(cast(BetaContentBlockParam, thinking_block))
            elif isinstance(block, BetaTextBlock):
                if block.text:
                    res.append(BetaTextBlockParam(type="text", text=block.text))
            else:
                dumped = block.model_dump(exclude={'caller'})
                if dumped.get("type") == "tool_use" and dumped.get("name") not in ("computer", "minimize_panel"):
                    import logging
                    logging.getLogger("mano.agent").warning(f"SDK model_dump non-standard tool_use: {dumped}")
                res.append(cast(BetaToolUseBlockParam, dumped))
        return res
    else:
        return []


def parse_action_desc(actions):
    """Parse action input into human-readable description."""
    first_action = actions[0] if actions else {}
    if first_action.get("action_type") != "tool_use":
        return first_action.get("action_type")

    tool_name = first_action.get("name", "")
    action_input = first_action.get("input", {}) or {}
    action_name = action_input.get("action", "unknown")
    action_desc = action_name

    if tool_name == "minimize_panel":
        return "Minimize panel"

    if action_name in ("left_click", "right_click", "double_click", "middle_click", "mouse_move", "left_click_drag"):
        coord = action_input.get("coordinate")
        if coord and isinstance(coord, (list, tuple)) and len(coord) >= 2:
            action_desc += f" ({coord[0]}, {coord[1]})"

    elif action_name in ("type", "key"):
        text = action_input.get("text")
        if text:
            if len(str(text)) > 20:
                text_display = str(text)[:17] + "..."
            else:
                text_display = str(text)
            action_desc += f": {text_display}"

    elif action_name == "scroll":
        direction = action_input.get("scroll_direction")
        if direction:
            action_desc += f" {direction}"
        coord = action_input.get("coordinate")
        if coord and isinstance(coord, (list, tuple)) and len(coord) >= 2:
            action_desc += f" ({coord[0]}, {coord[1]})"
        scroll_amount = action_input.get("scroll_amount") or 10
        if scroll_amount:
            action_desc += f" scroll_amount {scroll_amount}"

    return action_desc


def normalize_actions(actions, platform):
    """Normalize key/modifier names for the target platform."""
    is_macos = str(platform).lower() in ("darwin",)
    click_actions = {"left_click", "right_click", "double_click", "middle_click", "triple_click"}

    normalized = []

    for a in actions or []:
        item = deepcopy(a)
        tool_input = item.get("input") or {}
        action = str(tool_input.get("action") or "").strip().lower()

        if action == "key":
            mods, mains = _normalize_combo_to_mods_and_mains(tool_input.get("text"), is_macos)
            tool_input["modifiers"] = mods
            tool_input["mains"] = mains

        elif action in click_actions:
            mods, _ = _normalize_combo_to_mods_and_mains(tool_input.get("text"), is_macos)
            tool_input["modifiers"] = mods

        item["input"] = tool_input
        normalized.append(item)

    return normalized


def _normalize_combo_to_mods_and_mains(combo, is_macos):
    parts = _split_combo(combo)
    modifiers = []
    mains = []

    for p in parts:
        k = _normalize_key_token(p, is_macos)
        if not k:
            continue
        if _is_modifier(k):
            modifiers.append(k)
        else:
            mains.append(k)

    return modifiers, mains


def _split_combo(combo):
    if combo is None:
        return []
    if isinstance(combo, list):
        return [str(x).strip() for x in combo if str(x).strip()]
    s = str(combo).strip()
    # Support both "ctrl+a" (Claude CUA style) and "ctrl a" (local model style)
    if "+" in s:
        return [x.strip() for x in s.split("+") if x.strip()]
    return [x.strip() for x in s.split() if x.strip()]


def _is_modifier(k):
    return k in {
        "cmd", "ctrl", "alt", "shift",
        "cmd_l", "cmd_r",
        "ctrl_l", "ctrl_r",
        "alt_l", "alt_r", "alt_gr",
        "shift_l", "shift_r",
    }


def _normalize_key_token(k, is_macos):
    k = str(k).strip().lower()
    k = k.replace("-", "_").replace(" ", "_")

    if k in ("command", "cmd", "win", "meta", "super"):
        return "cmd" if is_macos else "ctrl"

    if k in ("control", "ctl", "ctrl"):
        return "cmd" if is_macos else "ctrl"
    if k in ("option", "opt"):
        return "alt"

    if k in ("command_l", "cmd_l", "meta_l", "super_l", "win_l"):
        return "cmd_l" if is_macos else "ctrl_l"
    if k in ("command_r", "cmd_r", "meta_r", "super_r", "win_r"):
        return "cmd_r" if is_macos else "ctrl_r"
    if k in ("control_l", "ctl_l", "ctrl_l"):
        return "cmd_l" if is_macos else "ctrl_l"
    if k in ("control_r", "ctl_r", "ctrl_r"):
        return "cmd_r" if is_macos else "ctrl_r"
    if k in ("option_l", "opt_l"):
        return "alt_l"
    if k in ("option_r", "opt_r"):
        return "alt_r"
    if k == "altgr":
        return "alt_gr"

    alias_map = {
        "return": "enter",
        "escape": "esc",
        "spacebar": "space",
        "arrowup": "up",
        "arrow_up": "up",
        "arrowdown": "down",
        "arrow_down": "down",
        "arrowleft": "left",
        "arrow_left": "left",
        "arrowright": "right",
        "arrow_right": "right",
        "pageup": "page_up",
        "pgup": "page_up",
        "pagedown": "page_down",
        "pgdn": "page_down",
        "del": "delete",
        "ins": "insert",
        "bksp": "backspace",
        "capslock": "caps_lock",
    }

    return alias_map.get(k, k)


def open_url(url: str) -> dict | None:
    """Open a URL in the default browser. Returns tab info for later close_browser_tab().

    On macOS, uses AppleScript to detect which browser opened and record the tab index.
    """
    import platform
    import subprocess
    import time
    system = platform.system()
    tab_info = None
    try:
        if system == "Darwin":
            # Detect frontmost browser before opening
            subprocess.Popen(["open", url])
            time.sleep(2)
            # Detect which browser is now frontmost and its active tab
            detect = subprocess.run(
                ["osascript", "-l", "JavaScript", "-e",
                 'const se = Application("System Events"); se.processes.whose({frontmost: true})[0].name()'],
                capture_output=True, text=True, timeout=5,
            )
            browser = detect.stdout.strip() if detect.returncode == 0 else ""
            if browser in ("Google Chrome", "Safari", "Arc", "Brave Browser", "Microsoft Edge"):
                tab_info = {"browser": browser}
            # Position window
            script = (
                'tell application "System Events"\n'
                '    set frontApp to name of first application process whose frontmost is true\n'
                '    tell process frontApp\n'
                '        set position of window 1 to {0, 25}\n'
                '    end tell\n'
                'end tell'
            )
            subprocess.run(["osascript", "-e", script], timeout=3, capture_output=True)
        elif system == "Windows":
            subprocess.Popen(f'start "" "{url}"', shell=True)
        else:
            subprocess.Popen(["xdg-open", url])
    except Exception as e:
        raise RuntimeError(f"Failed to open {url}: {e}")
    return tab_info


def close_browser_tab(tab_info: dict = None):
    """Close the browser tab opened by open_url().

    Uses the browser name from tab_info to activate it first, then Cmd+W.
    Falls back to Cmd+W on the frontmost app if no tab_info.
    """
    import platform
    import subprocess
    import time
    system = platform.system()

    if system == "Darwin":
        browser = (tab_info or {}).get("browser")
        if browser:
            # Activate the browser first so Cmd+W targets it
            try:
                subprocess.run(
                    ["osascript", "-e", f'tell application "{browser}" to activate'],
                    timeout=3, capture_output=True,
                )
                time.sleep(0.5)
            except Exception:
                pass
        # Cmd+W to close the frontmost tab
        from pynput.keyboard import Controller, Key
        kb = Controller()
        with kb.pressed(Key.cmd):
            kb.tap('w')
    elif system == "Windows":
        from pynput.keyboard import Controller, Key
        kb = Controller()
        with kb.pressed(Key.ctrl):
            kb.tap('w')
    else:
        from pynput.keyboard import Controller, Key
        kb = Controller()
        with kb.pressed(Key.ctrl):
            kb.tap('w')
