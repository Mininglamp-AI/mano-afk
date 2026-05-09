#!/usr/bin/env python3
"""
Mano — Desktop Automation CLI.

Subcommands:
    run             Execute a GUI automation task
    config          Manage persistent user configuration
    download-model  Download model weights (placeholder)

Environment variables (cloud mode):
    ANTHROPIC_API_KEY    — API key for Claude
    ANTHROPIC_BASE_URL   — API gateway URL (optional)
"""

import argparse
import asyncio
import json
import os
import platform
import signal
import sys
import threading
import traceback

from config import (
    ANIMATION_CONFIG,
    TASK_STATUS,
    CONFIG_KEYS,
    load_user_config,
    get_config,
    set_config,
    get_default_model_path,
    get_api_key,
    USER_CONFIG_FILE,
)
from task import TaskModel
from ui.overlay import TaskOverlayView
from agents import ClaudeAgent, LocalAgent


# ─── PID file for stop command ────────────────────────────────

PID_FILE = os.path.expanduser("~/.mano/mano-afk.pid")


def _write_pid():
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _remove_pid():
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


# ─── run subcommand ──────────────────────────────────────────

def run_task(
    task: str,
    url: str = None,
    expect: str = None,
    max_steps: int = None,
    minimize: bool = False,
    local: bool = False,
    model_path: str = None,
):
    """Run an automation task with optional judge evaluation."""
    _write_pid()
    try:
        return _run_task_inner(task, url, expect, max_steps, minimize, local, model_path)
    finally:
        _remove_pid()


def _run_task_inner(task, url, expect, max_steps, minimize, local, model_path):

    # 0. Open URL if provided (before agent starts)
    tab_info = None
    if url:
        from utils import open_url
        import time
        tab_info = open_url(url)
        time.sleep(2)  # Wait for browser to load
        print(f"Opened URL: {url}")

    # 1. Create agent
    if local:
        resolved_model_path = model_path or get_default_model_path()
        if not resolved_model_path:
            print("Local model path not configured. Set it with:")
            print("  mano-afk config --set default-model-path <path>")
            print("\nTo download a model:")
            print("  mano-afk install-model")
            return 1
        resolved_model_path = os.path.expanduser(resolved_model_path)
        agent = LocalAgent(model_path=resolved_model_path)
    else:
        api_key = get_api_key()
        if not api_key:
            print("ANTHROPIC_API_KEY not set. Export it in your shell:")
            print("  export ANTHROPIC_API_KEY=<your-key>")
            return 1
        agent = ClaudeAgent(platform=platform.system())

    # 2. Create Model and View
    model = TaskModel()
    try:
        view = TaskOverlayView()
        ui_available = view._ui_initialized
    except Exception:
        view = None
        ui_available = False

    if not ui_available:
        print("CustomTkinter UI unavailable, running headless.")
        model.init_task(task, agent, expected_result=expect, max_steps=max_steps)
        model.run_automation_task()
        exit_code = 0 if model.state.status == TASK_STATUS["COMPLETED"] else 1
        if url:
            from utils import close_browser_tab
            close_browser_tab(tab_info)
        # Run judge after headless execution
        if expect and exit_code == 0:
            exit_code = _run_judge(agent, task, expect, local, resolved_model_path if local else None)
        return exit_code

    # 3. Wire minimize callback
    def _minimize_if_needed():
        if not view._minimized:
            view._toggle_minimize()
    model.on_minimize_panel = lambda: view.root.after(0, _minimize_if_needed)

    # 4. Initialize model with agent
    model.init_task(task, agent, expected_result=expect, max_steps=max_steps)

    # 5. Bind model state changes to view updates
    def on_model_state_changed(task_state):
        view.root.after(0, lambda: view.update_task_state(task_state))
    model.set_state_changed_callback(on_model_state_changed)

    # 6. Track running state
    is_running = True
    task_thread = None

    # 7. Bind view commands
    def on_stop_command():
        nonlocal is_running
        if is_running:
            view.root.after(0, lambda: view.stop_button.configure(
                text="Stopping\u2026",
                state="disabled",
            ))
            view.root.after(ANIMATION_CONFIG["STOP_DELAY"], model.stop_task)

    def on_close_command():
        nonlocal is_running
        is_running = False
        model.stop_task()
        view.close()

    def on_continue_command():
        nonlocal is_running
        if not is_running:
            return

        def do_continue():
            try:
                view.root.after(0, lambda: [
                    view.continue_button.configure(text="Resuming...", state="disabled"),
                    view.stop_button.configure(state="disabled"),
                ])
                model.resume_task()
                view.root.after(0, lambda: [
                    view.stop_button.configure(state="normal"),
                ])
            except Exception as e:
                print(f"Continue failed: {e}")
                traceback.print_exc()
                view.root.after(0, lambda: [
                    view.continue_button.configure(text="Proceed", state="normal"),
                    view.stop_button.configure(state="normal"),
                ])

        threading.Thread(target=do_continue, daemon=True).start()

    view.on_stop_command = on_stop_command
    view.on_close_command = on_close_command
    view.on_continue_command = on_continue_command

    # 8. Show view
    view.show()
    if minimize:
        view.root.after(200, view._toggle_minimize)

    # 9. Start worker thread
    def worker():
        model.run_automation_task()

    task_thread = threading.Thread(target=worker, daemon=True)
    task_thread.start()

    # 10. Poll thread completion
    def poll_thread():
        if task_thread and task_thread.is_alive():
            view.root.after(ANIMATION_CONFIG["POLL_INTERVAL"], poll_thread)
            return
        if model.state.status in (TASK_STATUS["COMPLETED"], TASK_STATUS["ERROR"], TASK_STATUS["STOPPED"]):
            on_model_state_changed(model.state)
        elif model.stop_event.is_set():
            model.mark_stopped()

    view.root.after(ANIMATION_CONFIG["POLL_INTERVAL"], poll_thread)

    # 11. Run UI mainloop
    try:
        view.run_mainloop()
    except Exception as e:
        print(f"UI runtime exception: {e}")
        is_running = False
        model.mark_error(str(e))
    finally:
        if task_thread and task_thread.is_alive():
            task_thread.join(timeout=2)

    exit_code = 0 if model.state.status == TASK_STATUS["COMPLETED"] else 1

    # 12. Close the browser tab opened by --url
    if url:
        from utils import close_browser_tab
        close_browser_tab()

    # 13. Run judge after task completion
    if expect and model.state.status == TASK_STATUS["COMPLETED"]:
        exit_code = _run_judge(agent, task, expect, local, resolved_model_path if local else None)

    return exit_code


def _run_judge(agent, task, expect, local, model_path=None):
    """Run judge evaluation after task completion. Returns exit code.

    --expect triggers judge automatically:
      --local → local Mano-P judge
      cloud   → Gemini judge
    """
    session_dir = os.path.join(agent._get_save_dir(), agent.session_id)

    # Release agent model before loading judge to free GPU memory
    if local and hasattr(agent, 'model'):
        del agent.model
        del agent.processor
        try:
            import mlx.core as mx
            mx.clear_cache()
        except Exception:
            pass
        import gc
        gc.collect()

    if local:
        result = _run_local_judge(session_dir, task, expect, model_path)
        if result is None or result.get("verdict") not in ("PASS", "UNKNOWN"):
            return 1
    else:
        result = _run_cloud_judge(session_dir, task, expect)
        if result is not None:
            verdict = result.get("verdict", {})
            if isinstance(verdict, dict) and not verdict.get("success"):
                return 1

    return 0


def _run_local_judge(session_dir, task, expect, model_path=None):
    """Run local Mano-P judge in a separate thread.

    MLX Metal GPU streams are per-thread. The agent ran in a worker thread,
    so its stream doesn't exist in the main thread. We spawn a new thread
    for the judge so that pm.load() creates a fresh GPU stream.
    """
    result_holder = [None]
    error_holder = [None]

    def _judge_thread():
        try:
            from judges.local import run_judge, get_last_screenshots

            n_images = 2  # first (initial state) + last (final state)
            images, filenames = get_last_screenshots(session_dir, n_images)
            resolved = model_path or get_default_model_path()

            print(f"\n--- Local Judge ({n_images} screenshots, model: {os.path.basename(resolved)}) ---")
            result = run_judge(
                model_path=resolved,
                task=task,
                expected_result=expect,
                images=images,
            )
            print(f"Verdict: {result['verdict']}")
            print(f"Reason:  {result['reason']}")
            print(f"Time:    {result['elapsed']}s")

            # Write back to result.json
            _write_judge_to_result(session_dir, "judge", {
                "verdict": result["verdict"],
                "reason": result["reason"],
                "expected_result": expect,
                "elapsed_sec": result["elapsed"],
                "model": os.path.basename(os.path.expanduser(resolved)),
                "token_usage": result.get("token_usage", {}),
            })
            result_holder[0] = result
        except Exception as e:
            print(f"Local judge failed: {e}")
            traceback.print_exc()
            error_holder[0] = e

    t = threading.Thread(target=_judge_thread)
    t.start()
    t.join()

    return result_holder[0]


def _run_cloud_judge(session_dir, task, expect):
    """Run cloud judge."""
    try:
        from judges.cloud import run_cloud_judge, get_last_n_screenshot_paths, EVAL_SCREENSHOT_COUNT, _resolve_model

        n_images = EVAL_SCREENSHOT_COUNT
        screenshot_paths = get_last_n_screenshot_paths(session_dir, n_images)

        result_path = os.path.join(session_dir, "result.json")
        with open(result_path, "r", encoding="utf-8") as f:
            session_result = json.load(f)
        history_resps = session_result.get("history_resps", [])

        print(f"\n--- Cloud Judge ({n_images} screenshots) ---")
        result = asyncio.run(
            run_cloud_judge(task, expect, history_resps, screenshot_paths)
        )
        verdict = result["verdict"]
        print(f"Success:    {verdict.get('success')}")
        print(f"Failure:    {verdict.get('failure_type')}")
        print(f"Reason:     {verdict.get('reason')}")
        print(f"Confidence: {verdict.get('confidence')}")
        print(f"Time:       {result['elapsed_sec']}s")

        # Write back to result.json
        _write_judge_to_result(session_dir, "judge", {
            "success": verdict.get("success"),
            "failure_type": verdict.get("failure_type"),
            "reason": verdict.get("reason"),
            "evidence": verdict.get("evidence"),
            "confidence": verdict.get("confidence"),
            "model_failure": verdict.get("model_failure"),
            "expected_result": expect,
            "elapsed_sec": result["elapsed_sec"],
            "screenshots_used": result["screenshots_used"],
            "model": _resolve_model(),
            "token_usage": result["token_usage"],
        })
        return result
    except Exception as e:
        print(f"Cloud judge failed: {e}")
        traceback.print_exc()
        return None


def _write_judge_to_result(session_dir, key, data):
    """Write judge results back into result.json."""
    result_path = os.path.join(session_dir, "result.json")
    try:
        with open(result_path, "r", encoding="utf-8") as f:
            session_result = json.load(f)
    except Exception:
        session_result = {}
    session_result[key] = data
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(session_result, f, indent=4, ensure_ascii=False)


# ─── config subcommand ───────────────────────────────────────

def cmd_config(args):
    """Manage persistent user configuration (~/.mano/config.json)."""
    if args.list:
        cfg = load_user_config()
        print(f"Config file: {USER_CONFIG_FILE}\n")
        for key, desc in CONFIG_KEYS.items():
            current = cfg.get(key)
            if current:
                print(f"  {key:22s} = {current}")
            else:
                print(f"  {key:22s}   (not set)")
            print(f"  {'':22s}   {desc}")
        return 0

    if args.show:
        cfg = load_user_config()
        if cfg:
            print(json.dumps(cfg, indent=2, ensure_ascii=False))
        else:
            print(f"No config found at {USER_CONFIG_FILE}")
        return 0

    if args.get:
        value = get_config(args.get)
        if value is not None:
            print(value)
            return 0
        else:
            return 1

    if args.set:
        key, value = args.set
        set_config(key, value)
        print(f"{key} = {value}")
        return 0

    print("Use --list, --show, --get KEY, or --set KEY VALUE. See: mano-afk config --help")
    return 1


# ─── stop subcommand ─────────────────────────────────────────

def cmd_stop(args):
    """Gracefully stop a running mano-afk task."""
    if not os.path.isfile(PID_FILE):
        print("No active session.")
        return 1
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Stop signal sent to mano-afk (PID {pid}).")
        _remove_pid()
        return 0
    except ProcessLookupError:
        print("Process not found (stale PID file). Cleaning up.")
        _remove_pid()
        return 1
    except Exception as e:
        print(f"Failed to stop: {e}")
        return 1


# ─── install-sdk subcommand ──────────────────────────────────

def cmd_install_sdk(args):
    """Install local inference SDK (mlx-vlm + cider + torch) into the mano-afk environment."""
    import subprocess

    pip_cmd = [sys.executable, "-m", "pip"]

    # 1. mlx-vlm
    try:
        import mlx_vlm
        print(f"  mlx-vlm: already installed")
    except ImportError:
        print(f"  Installing mlx-vlm...")
        result = subprocess.run(pip_cmd + ["install", "mlx-vlm"])
        if result.returncode != 0:
            print(f"  mlx-vlm installation failed.")
            return 1
        print(f"  mlx-vlm installed.")

    # 2. torch (required by vlm_service)
    try:
        import torch
        print(f"  torch: already installed")
    except ImportError:
        print(f"  Installing torch...")
        result = subprocess.run(pip_cmd + ["install", "torch"])
        if result.returncode != 0:
            print(f"  torch installation failed.")
            return 1
        print(f"  torch installed.")

    # 3. cider — always install from GitHub (must compile C++ extension)
    print(f"  Installing cider from GitHub (compiling C++ extension)...")
    result = subprocess.run(pip_cmd + ["install", "--force-reinstall", "--no-deps", "git+https://github.com/Mininglamp-AI/cider.git"])
    if result.returncode != 0:
        print(f"  cider installation failed. Ensure CMake >= 3.27 and Xcode CLI tools are installed.")
        return 1
    print(f"  cider installed.")

    print("\nSDK ready. Run 'mano-afk check' to verify.")
    return 0


# ─── install-model subcommand ────────────────────────────────

def cmd_install_model(args):
    """Download Mano-P model weights from HuggingFace."""
    import subprocess

    # Skip if a valid model path is already configured
    existing = get_config("default-model-path")
    if existing and os.path.isdir(os.path.expanduser(existing)):
        print(f"Model already configured: {existing}")
        return 0

    model_name = args.name or "Mininglamp-2718/Mano-P"
    model_dir = os.path.expanduser("~/.mano/models/Mano-P")

    print(f"Downloading model: {model_name}\n")
    print("Option 1: Download from webpage")
    print(f"  https://huggingface.co/{model_name}/tree/main/w8a16")
    print(f"  Download all files, then:")
    print(f"  mano-afk config --set default-model-path /path/to/w8a16\n")
    print("Option 2: Download via CLI (requires HuggingFace token)")
    print("  1. Create a token at https://huggingface.co/settings/tokens ")
    print("  2. Run: hf auth login")
    print(f"  3. Downloading now...\n")

    result = subprocess.run(
        ["hf", "download", model_name, "--include", "w8a16/*", "--local-dir", model_dir]
    )
    if result.returncode != 0:
        print(f"\nDownload failed. Make sure you are logged in:")
        print(f"  hf auth login")
        print(f"  Then run: mano-afk install-model")
        print(f"\nOr download manually and set path:")
        print(f"  mano-afk config --set default-model-path /path/to/model")
        return 1

    model_path = os.path.join(model_dir, "w8a16")
    if not os.path.isdir(model_path):
        model_path = model_dir

    print(f"\nModel ready: {model_path}")
    set_config("default-model-path", model_path)
    print(f"Config updated: default-model-path = {model_path}")
    return 0


# ─── check subcommand ────────────────────────────────────────

def cmd_check(args):
    """Verify that the current e2e-mode setup is ready to run."""
    e2e_mode = get_config("e2e-mode")
    print(f"e2e-mode: {e2e_mode or '(not set)'}\n")

    if e2e_mode == "local" or args.all:
        print("Local mode:")
        # Check SDK — verify vlm_service can actually load (catches missing torch, broken cider)
        try:
            from vlm_service import custom_generate
            from cider import is_available
            w8a8_status = "available (M5+)" if is_available() else "not available (requires M5+)"
            print(f"  SDK: OK")
            print(f"  W8A8: {w8a8_status}")
        except ImportError as e:
            print(f"  SDK: NOT READY — {e}")
            print(f"    → run: mano-afk install-sdk")
        except Exception as e:
            print(f"  SDK: present but failed to load — {e}")
            print(f"    → run: mano-afk install-sdk")

        # Check model path
        model_path = get_config("default-model-path")
        if model_path:
            expanded = os.path.expanduser(model_path)
            exists = os.path.isdir(expanded)
            print(f"  Model path: {model_path} ({'exists' if exists else 'NOT FOUND'})")
            if not exists:
                print(f"    → run: mano-afk install-model")
                print(f"    → or:  mano-afk config --set default-model-path <path>")
        else:
            print(f"  Model path: (not set)")
            print(f"    → run: mano-afk config --set default-model-path <path>")
        print()

    if e2e_mode == "cloud" or args.all:
        print("Cloud mode:")
        api_key = get_api_key()
        if api_key:
            print(f"  API key: configured (****{api_key[-4:]})")
        else:
            print(f"  API key: NOT SET")
            print(f"    → run: export ANTHROPIC_API_KEY=<your-key>")
        print()

    if not e2e_mode and not args.all:
        print("No e2e-mode configured. Run:")
        print("  mano-afk config --set e2e-mode local   (on-device, Apple Silicon)")
        print("  mano-afk config --set e2e-mode cloud   (Claude CUA, needs API key)")
    return 0


# ─── CLI entry point ─────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="mano-afk",
        description="Mano AFK — Desktop Automation CLI",
        epilog="Environment: ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL (cloud mode)",
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # ── run ──
    run_parser = subparsers.add_parser("run", help="Execute a GUI automation task")
    run_parser.add_argument("task", help="Task description")
    run_parser.add_argument("--url", default=None, help="Open this URL in the default browser before starting the task")
    run_parser.add_argument("--expect", help="Expected result — triggers judge evaluation after task")
    run_parser.add_argument("--max-steps", type=int, default=None, help="Maximum steps (default: from config, fallback 30)")
    run_parser.add_argument("--minimize", action="store_true", default=None, help="Start with minimized UI panel (default: from config)")
    run_parser.add_argument("--no-minimize", action="store_true", help="Force full UI panel (overrides config)")
    run_parser.add_argument("--local", action="store_true", default=None, help="Use local model (default: from e2e-mode config)")
    run_parser.add_argument("--cloud", action="store_true", help="Use cloud model (overrides e2e-mode config)")
    run_parser.add_argument("--model-path", default=None, help="Local model weights path (overrides config)")

    # ── stop ──
    subparsers.add_parser("stop", help="Gracefully stop a running mano-afk task")

    # ── config ──
    config_parser = subparsers.add_parser("config", help="Manage persistent configuration")
    config_parser.add_argument("--list", action="store_true", help="List all config keys with current values and descriptions")
    config_parser.add_argument("--show", action="store_true", help="Show current config as JSON")
    config_parser.add_argument("--get", metavar="KEY", help="Get a config value")
    config_parser.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), help="Set a config value")

    # ── check ──
    check_parser = subparsers.add_parser("check", help="Verify e2e-mode setup (SDK, model, API key)")
    check_parser.add_argument("--all", action="store_true", help="Check both local and cloud modes")

    # ── install-sdk ──
    subparsers.add_parser("install-sdk", help="Install Cider inference SDK")

    # ── install-model ──
    model_parser = subparsers.add_parser("install-model", help="Download Mano-P model from HuggingFace")
    model_parser.add_argument("name", nargs="?", help="Model name to download")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "run":
        # Resolve args: CLI flag > config > default
        # -- local/cloud
        if args.cloud:
            use_local = False
        elif args.local:
            use_local = True
        else:
            e2e_mode = get_config("e2e-mode")
            if e2e_mode == "local":
                use_local = True
            elif e2e_mode == "cloud":
                use_local = False
            else:
                print("Error: e2e-mode not configured. Run: mano-afk config --set e2e-mode local")
                print("       or use --local / --cloud flag.")
                return 1
        # -- max-steps
        max_steps = args.max_steps
        if max_steps is None:
            cfg_val = get_config("max-steps")
            max_steps = int(cfg_val) if cfg_val else 30
        # -- minimize
        if args.no_minimize:
            minimize = False
        elif args.minimize:
            minimize = True
        else:
            cfg_val = get_config("minimize")
            minimize = cfg_val in ("true", "1", "yes") if cfg_val else True

        return run_task(
            task=args.task,
            url=args.url,
            expect=args.expect,
            max_steps=max_steps,
            minimize=minimize,
            local=use_local,
            model_path=args.model_path,
        )

    if args.command == "stop":
        return cmd_stop(args)

    if args.command == "config":
        return cmd_config(args)

    if args.command == "check":
        return cmd_check(args)

    if args.command == "install-sdk":
        return cmd_install_sdk(args)

    if args.command == "install-model":
        return cmd_install_model(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
