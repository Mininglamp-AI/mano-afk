"""
TaskModel + TaskState + TaskProgress — merged and refactored.
HTTP calls replaced with direct agent.predict() calls.
"""
import asyncio
import json
import platform
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from config import AUTOMATION_CONFIG, TASK_STATUS
from executor import ComputerActionExecutor, screenshot_to_bytes, make_tool_result, get_or_create_device_id
from utils import normalize_actions, parse_action_desc


@dataclass
class TaskProgress:
    """Task progress data model."""
    step_idx: int = 0
    action: str = ""
    reasoning: str = ""
    action_meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskState:
    """Task state data model."""
    task_name: str = ""
    status: str = ""
    progress: TaskProgress = field(default_factory=TaskProgress)
    error_msg: Optional[str] = None
    is_running: bool = False


class TaskModel:
    """Automation task core model — direct agent invocation, no HTTP."""

    def __init__(self):
        self.state = TaskState()
        self.stop_event = threading.Event()
        self.pause_event: Optional[threading.Event] = None

        self._on_state_changed: Optional[Callable[[TaskState], None]] = None

        self.on_minimize_panel: Optional[Callable] = None
        self.executor: Optional[ComputerActionExecutor] = None
        self.agent = None  # BaseAgent instance, set via init_task()
        self.expected_result: Optional[str] = None
        self.eval_result = None

    # ========== Data Monitoring ==========
    def set_state_changed_callback(self, callback: Callable[[TaskState], None]):
        self._on_state_changed = callback

    def _notify_state_changed(self):
        if self._on_state_changed:
            self._on_state_changed(self.state)

    # ========== Initialization ==========
    def init_task(self, task_name: str, agent, expected_result: Optional[str] = None, max_steps: Optional[int] = None):
        """Initialize automation task with an agent instance."""
        self.state.task_name = task_name
        self.agent = agent
        self.expected_result = expected_result
        self.max_steps = max_steps
        self.state.status = TASK_STATUS["RUNNING"]
        self.state.is_running = True
        self.state.error_msg = None
        self.state.progress = TaskProgress()

        agent_screen_size = getattr(agent, "screen_size", None)
        self.executor = ComputerActionExecutor(
            on_minimize_panel=self.on_minimize_panel,
            screen_size=agent_screen_size,
        )
        self.stop_event.clear()
        self._notify_state_changed()

    # ========== Progress Update ==========
    def update_progress(self, step_idx: int, action_desc: str, reasoning: str = "", meta: Optional[Dict[str, Any]] = None):
        if not self.state.is_running:
            return
        self.state.progress = TaskProgress(
            step_idx=step_idx,
            action=action_desc,
            reasoning=reasoning,
            action_meta=meta or {},
        )
        print(f"[step {step_idx}] Action: {action_desc}")
        if reasoning:
            print(f"[step {step_idx}] Reasoning: {reasoning}")
        self._notify_state_changed()

    # ========== State Management ==========
    def mark_completed(self):
        self.state.status = TASK_STATUS["COMPLETED"]
        self.state.is_running = False
        self.stop_event.set()
        self._save_result()
        self._print_summary("COMPLETED")
        self._notify_state_changed()

    def mark_stopped(self):
        self.state.status = TASK_STATUS["STOPPED"]
        self.state.is_running = False
        self.stop_event.set()
        self._save_result()
        self._print_summary("STOPPED_BY_USER")
        self._notify_state_changed()

    def mark_error(self, error_msg: str):
        self.state.status = TASK_STATUS["ERROR"]
        self.state.error_msg = error_msg
        self.state.is_running = False
        self.stop_event.set()
        self._save_result()
        self._print_summary("ERROR", error_msg)
        self._notify_state_changed()

    def _save_result(self):
        """Save result.json via agent."""
        if self.agent and hasattr(self.agent, "save_result"):
            result_path = self.agent.save_result(self.state.task_name)
            if result_path:
                print(f"Result saved to: {result_path}")

    def _print_summary(self, final_status: str, error_msg: str = ""):
        print(f"\n{'=' * 50}")
        print(f"Task: {self.state.task_name}")
        print(f"Status: {final_status}")
        print(f"Total steps: {self.state.progress.step_idx}")
        if self.state.progress.action:
            print(f"Last action: {self.state.progress.action}")
        if self.state.progress.reasoning:
            print(f"Last reasoning: {self.state.progress.reasoning}\n")
        if error_msg:
            print(f"Error: {error_msg}")
        if self.eval_result:
            print(f"Evaluation result: {json.dumps(self.eval_result, indent=2, ensure_ascii=False)}")
        print(f"{'=' * 50}\n")

    def mark_call_user(self):
        """Mark task requires user intervention, pause until resumed."""
        self.state.status = TASK_STATUS["CALL_USER"]
        self._notify_state_changed()
        self.pause_task()
        self.pause_event.wait()
        self.state.status = TASK_STATUS["RUNNING"]

    # ========== Thread Control ==========
    def stop_task(self):
        if self.state.is_running:
            self.mark_stopped()

    def pause_task(self):
        if self.state.is_running and not self.stop_event.is_set():
            self.pause_event = threading.Event()
            self.pause_event.clear()
            self._notify_state_changed()

    def resume_task(self):
        if self.pause_event:
            self.pause_event.set()
            self._notify_state_changed()

    # ========== Core Business Logic ==========
    def run_automation_task(self):
        """Run complete automation task using direct agent calls."""
        if not self.state.is_running:
            return

        print(f"Expected result: {self.expected_result}")

        try:
            if not self.agent:
                raise RuntimeError("No agent provided")

            self.update_progress(0, "Initializing", "Starting task")
            self._execute_task_steps()

            if self.state.is_running and self.state.status != TASK_STATUS["ERROR"]:
                self.mark_completed()

        except Exception as e:
            self.mark_error(f"Task execution failed: {str(e)}")

    def _execute_task_steps(self):
        """Execute task step loop with direct agent.predict() calls."""
        tool_results: List[Dict[str, Any]] = []
        step_idx = 0
        loop = asyncio.new_event_loop()

        try:
            while self.state.is_running and not self.stop_event.is_set():
                if self.stop_event.is_set():
                    self.mark_stopped()
                    break

                if self.max_steps is not None and step_idx >= self.max_steps:
                    print(f"Max steps ({self.max_steps}) reached, stopping.")
                    break

                # Call agent.predict() directly (no HTTP)
                try:
                    reasoning, actions = loop.run_until_complete(
                        self.agent.predict(
                            task_instruction=self.state.task_name,
                            tool_results=tool_results,
                        )
                    )
                except Exception as e:
                    raise RuntimeError(f"Agent prediction failed: {e}")

                # Determine status from actions (logic from web_server.py)
                status = "RUNNING"
                for a in actions:
                    at = (a.get("action_type") or a.get("type") or "").upper()
                    if at in ("DONE", "FAIL", "CALL_USER"):
                        status = at
                        break

                # Normalize actions and get description
                platform_tag = platform.system()
                normalized_actions = normalize_actions(actions, platform_tag)
                action_desc = parse_action_desc(actions)

                # Update UI progress
                self.update_progress(step_idx, action_desc, reasoning)

                # Handle terminal/special status
                if status == "DONE":
                    break
                elif status == "FAIL":
                    self.mark_error("Agent marked task as failed")
                    break
                elif status == "CALL_USER":
                    self.mark_call_user()
                    # After resume, agent needs the continue message
                    self.agent.agree_to_continue()
                    continue

                # Execute actions
                tool_results = []
                if not normalized_actions:
                    continue

                for i, a in enumerate(normalized_actions):
                    tool_use_id = a.get("id")
                    if not tool_use_id:
                        continue

                    result = self.executor.run_one(a)
                    time.sleep(AUTOMATION_CONFIG["ACTION_DELAY"])

                    include_screenshot = (i == len(normalized_actions) - 1)
                    after_shot = screenshot_to_bytes() if include_screenshot else None

                    tool_results.append(
                        make_tool_result(
                            tool_use_id=tool_use_id,
                            ok=bool(result["ok"]),
                            message=result["message"],
                            include_screenshot=include_screenshot,
                            screenshot_bytes=after_shot,
                            meta=result.get("meta"),
                        )
                    )

                step_idx += 1
        finally:
            loop.close()
