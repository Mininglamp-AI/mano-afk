"""All constants and configuration for mano-afk."""

import json
import os

WINDOW_CONFIG = {
    "WIDTH": 320,
    "MINIMIZED_WIDTH": 110,
    "MINIMIZED_HEIGHT": 28,
    "MIN_HEIGHT": 240,
    "MAX_HEIGHT": 400,
    "MARGIN": 18,
    "ALPHA": 0.92,
    "BG_COLOR": "#1e1e1e",
    "LOG_BG_COLOR": "#000000",
    "TEXT_COLOR": "#eaeaea",
    "TITLE_FONT_SIZE": 12,
    "LOG_FONT_SIZE": 11,
    "CORNER_RADIUS": 14,
    "BUTTON_RADIUS": 10,
    "BUTTON_HEIGHT": 32,
    "STOP_BTN_COLOR": "#ff5050",
    "STOP_BTN_HOVER": "#ff7070",
}

ANIMATION_CONFIG = {
    "BLINK_INTERVAL": 500,
    "POLL_INTERVAL": 200,
    "STOP_DELAY": 1000,
    "HEIGHT_ADJUST_DELAY": 10,
}

TEXT_CONSTANTS = {
    "WINDOW_TITLE": "VLA Task Monitor",
    "RUNNING_TEXT": "Running",
    "EVALUATING_TEXT": "Evaluating",
    "DONE_TEXT": "Done \u2705",
    "STOPPED_TEXT": "Stopped \u23f9",
    "ERROR_TEXT": "Error \u274c",
    "STEP_PREFIX": "Step: ",
    "TASK_PREFIX": "Task: ",
    "STOP_BUTTON_TEXT": "Stop",
    "STOPPING_BUTTON_TEXT": "Stopping\u2026",
    "CLOSE_BUTTON_TEXT": "Close",
    "ACTION_PREFIX": "Action: ",
    "REASONING_PREFIX": "Reasoning: ",
}

TASK_STATUS = {
    "RUNNING": "running",
    "COMPLETED": "completed",
    "STOPPED": "stopped",
    "ERROR": "error",
    "CALL_USER": "call_user",
    "EVALUATING": "evaluating",
}

AUTOMATION_CONFIG = {
    "DEVICE_FILE": "~/.myapp_device_id",
    "SCREEN_SCALE_WIDTH": 1280,
    "SCREEN_SCALE_HEIGHT": 720,
    "SCROLL_MULTIPLIER": 5,
    "ACTION_DELAY": 2,
    "APP_START_DELAY": 1,
    "MOUSE_MOVE_STEPS_PER_SEC": 30,
    "MOUSE_CLICK_DELAY": 0.1,
    "HOTKEY_DELAY": 0.08,
}

AGENT_CONFIG = {
    "MODEL": "claude-sonnet-4-6",
    "MAX_TOKENS": 4096,
    "THINKING_BUDGET": 2048,
    "N_MOST_RECENT_IMAGES": 8,
    "API_RETRY_TIMES": 10,
    "API_RETRY_INTERVAL": 3,
    "CLIENT_TIMEOUT": 1800,
}

LOCAL_AGENT_CONFIG = {
    "MAX_NEW_TOKENS": 2048,
    "TEMPERATURE": 0.0,
    "TOP_P": 1.0,
    "SCREENSHOT_WIDTH": 1280,
    "HISTORY_IMAGE_COUNT": 1,
}

# ─── User-level persistent config (~/.mano/config.json) ────────
#
# All keys use kebab-case (CLI-style). Each key has ONE source of truth:
# ~/.mano/config.json (with optional default in CONFIG_DEFAULTS).
# API key is read from env var only — never stored in config.
#
# Supported keys:
#   e2e-mode            — "local" or "cloud" (required, no default)
#   default-model-path  — local model weights directory (required for local mode, no default)
#   projects-dir        — root directory for new projects (default: ~/Projects)
#   max-steps           — max steps per task (default: 30)
#   minimize            — start minimized (default: true)

USER_CONFIG_DIR = os.path.expanduser("~/.mano")
USER_CONFIG_FILE = os.path.join(USER_CONFIG_DIR, "config.json")

# Migration: old keys → new keys (or removal)
_KEY_MIGRATION = {
    "default_local_model_path": "default-model-path",
    "api-key": None,  # removed: use ANTHROPIC_API_KEY env var instead
}

CONFIG_DEFAULTS = {
    "projects-dir": "~/Projects",
    "max-steps": "30",
    "minimize": "true",
}

# All known config keys with descriptions (for --list)
CONFIG_KEYS = {
    "e2e-mode":           "E2E test mode: 'local' or 'cloud' (required, set during first-time setup)",
    "default-model-path": "Local Mano-P model weights directory (required for local mode)",
    "w8a8":               "W8A8 INT8 acceleration: 'auto', 'on', or 'off' (default: auto, requires M5+)",
    "projects-dir":       f"Root directory for new projects (default: {CONFIG_DEFAULTS['projects-dir']})",
    "max-steps":          f"Maximum steps per task (default: {CONFIG_DEFAULTS['max-steps']})",
    "minimize":           f"Start with minimized UI panel: true/false (default: {CONFIG_DEFAULTS['minimize']})",
}


def load_user_config() -> dict:
    """Load ~/.mano/config.json with key migration. Returns empty dict if not found."""
    if not os.path.isfile(USER_CONFIG_FILE):
        return {}
    with open(USER_CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # Migrate old keys
    migrated = False
    for old_key, new_key in _KEY_MIGRATION.items():
        if old_key in cfg:
            if new_key and new_key not in cfg:
                cfg[new_key] = cfg.pop(old_key)
            else:
                del cfg[old_key]
            migrated = True
    if migrated:
        save_user_config(cfg)
    return cfg


def save_user_config(config: dict):
    """Write config to ~/.mano/config.json."""
    os.makedirs(USER_CONFIG_DIR, exist_ok=True)
    with open(USER_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_config(key: str) -> str | None:
    """Get a single config value. Returns default if not set."""
    cfg = load_user_config()
    value = cfg.get(key)
    if value is None:
        value = CONFIG_DEFAULTS.get(key)
    return value


def set_config(key: str, value: str):
    """Set a single config value."""
    cfg = load_user_config()
    cfg[key] = value
    save_user_config(cfg)


def get_default_model_path() -> str | None:
    """Get local model path from config. Returns None if not set."""
    return get_config("default-model-path")


def get_api_key() -> str | None:
    """Get API key from ANTHROPIC_API_KEY environment variable."""
    return os.environ.get("ANTHROPIC_API_KEY")
