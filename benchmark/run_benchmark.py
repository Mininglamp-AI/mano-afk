#!/usr/bin/env python3
"""CUA Benchmark Runner — run 100 benchmark tasks with detailed recording.

Normal tests (bug_triggered=none) run on golden URL, expected PASS.
Bug tests (bug_triggered!=none) run on buggy URL, expected FAIL.
Accuracy = tests where judge verdict matches expected / total judged.

Usage:
    uv run benchmark/run_benchmark.py --mode local
    uv run benchmark/run_benchmark.py --mode cloud
    uv run benchmark/run_benchmark.py --mode local --project TS
    uv run benchmark/run_benchmark.py --mode local --start TS-01 --end TS-05

Output:
    benchmark/results/bench-{mode}-{timestamp}.json
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
TASKS_FILE = os.path.join(SCRIPT_DIR, "tasks.json")
RESULTS_DIR = os.path.join(SCRIPT_DIR, "results")

TRAJ_DIR = os.path.expanduser("~/mano-trajectory/result")


def load_tasks():
    with open(TASKS_FILE) as f:
        tasks = json.load(f)
    for t in tasks:
        t["prefix"] = t["id"].split("-")[0]
    return tasks


def find_latest_session():
    if not os.path.exists(TRAJ_DIR):
        return None
    sessions = sorted(Path(TRAJ_DIR).iterdir(), key=lambda p: p.name, reverse=True)
    return str(sessions[0]) if sessions else None


def read_session_result(session_dir):
    if not session_dir:
        return {}
    result_path = os.path.join(session_dir, "result.json")
    if not os.path.exists(result_path):
        return {}
    with open(result_path) as f:
        return json.load(f)


def run_single_test(test, mode):
    """Run a single benchmark test.

    URL is determined by bug_triggered: none → golden, otherwise → buggy.
    Expected verdict: golden → PASS, buggy → FAIL.
    """
    test_id = test["id"]
    is_bug = test["bug_triggered"] != "none"
    version = "buggy" if is_bug else "golden"
    expected_verdict = "FAIL" if is_bug else "PASS"
    url = test["url"]
    max_steps = test.get("max_steps", 15)

    cmd = [
        sys.executable, os.path.join(PROJECT_DIR, "scripts", "main.py"),
        "run", test["task"],
        "--url", url,
        "--expect", test["expected_result"],
        "--max-steps", str(max_steps),
        "--minimize",
    ]
    if mode == "local":
        cmd.append("--local")
    else:
        cmd.append("--cloud")

    print(f"\n{'='*60}")
    print(f"[{test_id}] {test['task'][:80]}...")
    print(f"  URL: {url} ({version})")
    print(f"  Expected: {expected_verdict}")
    print(f"  Max steps: {max_steps}")
    print(f"{'='*60}")

    t0 = time.time()
    session_before = find_latest_session()

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1500,
            cwd=PROJECT_DIR,
        )
        elapsed = round(time.time() - t0, 1)

        session_dir = find_latest_session()
        if session_dir == session_before:
            session_dir = None

        session_data = read_session_result(session_dir)

        # Extract judge verdict (local: "verdict", cloud: "success")
        judge = session_data.get("judge", {})
        judge_verdict = judge.get("verdict")
        judge_reason = judge.get("reason", "")
        if judge_verdict is None and "success" in judge:
            judge_verdict = "PASS" if judge["success"] else "FAIL"

        step_timings = session_data.get("step_timings_sec", [])
        step_count = len(step_timings)
        avg_step_time = round(sum(step_timings) / len(step_timings), 2) if step_timings else None
        token_usage = session_data.get("token_usage", {})

        status = None
        output = result.stdout + result.stderr
        for line in output.split("\n"):
            if line.startswith("Status:"):
                status = line.split(":", 1)[1].strip()

        return {
            "id": test_id,
            "project": test.get("prefix", ""),
            "mode": mode,
            "version": version,
            "bug_triggered": test["bug_triggered"],
            "expected_verdict": expected_verdict,
            "status": status or session_data.get("status", "UNKNOWN"),
            "step_count": step_count,
            "step_timings_sec": step_timings,
            "avg_step_time_sec": avg_step_time,
            "elapsed_sec": elapsed,
            "judge_verdict": judge_verdict,
            "judge_reason": judge_reason,
            "judge_elapsed_sec": judge.get("elapsed_sec"),
            "judge_model": judge.get("model"),
            "token_usage": token_usage,
            "session_dir": session_dir,
            "exit_code": result.returncode,
            "error": None,
        }

    except subprocess.TimeoutExpired:
        return {
            "id": test_id, "project": test.get("prefix", ""),
            "mode": mode, "version": version,
            "bug_triggered": test["bug_triggered"],
            "expected_verdict": expected_verdict,
            "status": "TIMEOUT", "step_count": None,
            "step_timings_sec": [], "avg_step_time_sec": None,
            "elapsed_sec": 1500,
            "judge_verdict": None, "judge_reason": None,
            "judge_elapsed_sec": None, "judge_model": None,
            "token_usage": {}, "session_dir": None,
            "exit_code": -1, "error": "Timeout after 1500s",
        }
    except Exception as e:
        return {
            "id": test_id, "project": test.get("prefix", ""),
            "mode": mode, "version": version,
            "bug_triggered": test["bug_triggered"],
            "expected_verdict": expected_verdict,
            "status": "ERROR", "step_count": None,
            "step_timings_sec": [], "avg_step_time_sec": None,
            "elapsed_sec": round(time.time() - t0, 1),
            "judge_verdict": None, "judge_reason": None,
            "judge_elapsed_sec": None, "judge_model": None,
            "token_usage": {}, "session_dir": None,
            "exit_code": -1, "error": str(e),
        }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="CUA Benchmark Runner")
    parser.add_argument("--mode", required=True, choices=["local", "cloud"])
    parser.add_argument("--start", default=None, help="Start from this test ID (inclusive)")
    parser.add_argument("--end", default=None, help="End at this test ID (inclusive)")
    parser.add_argument("--project", default=None, help="Run only this project prefix (TS/MW/OMS/FL/LD)")
    args = parser.parse_args()

    tests = load_tasks()
    print(f"Loaded {len(tests)} tests from tasks.json")

    if args.project:
        tests = [t for t in tests if t["prefix"] == args.project]
    if args.start:
        idx = next((i for i, t in enumerate(tests) if t["id"] == args.start), 0)
        tests = tests[idx:]
    if args.end:
        idx = next((i for i, t in enumerate(tests) if t["id"] == args.end), len(tests) - 1)
        tests = tests[:idx + 1]

    n_golden = sum(1 for t in tests if t["bug_triggered"] == "none")
    n_buggy = len(tests) - n_golden
    print(f"Running {len(tests)} tests ({n_golden} golden + {n_buggy} buggy): {args.mode} mode\n")

    results = []
    correct_count = incorrect_count = error_count = 0
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(RESULTS_DIR, f"bench-{args.mode}-{timestamp}.json")
    os.makedirs(RESULTS_DIR, exist_ok=True)

    for i, test in enumerate(tests):
        print(f"\n>>> Test {i+1}/{len(tests)}: {test['id']}")
        result = run_single_test(test, args.mode)
        results.append(result)

        v = result["judge_verdict"]
        expected = result["expected_verdict"]
        if v is None:
            error_count += 1
            icon = "???"
            match = None
        elif v == expected:
            correct_count += 1
            icon = "CORRECT"
            match = True
        else:
            incorrect_count += 1
            icon = "WRONG"
            match = False
        result["match"] = match

        steps = result["step_count"] or "?"
        avg = f"{result['avg_step_time_sec']:.1f}s" if result["avg_step_time_sec"] else "?"
        print(f"  → {icon} | judge={v} expected={expected} | {steps} steps | avg {avg}/step | {result['elapsed_sec']}s")
        if result["judge_reason"]:
            print(f"    Judge: {result['judge_reason'][:80]}")

        # Save after each test (crash-safe)
        total_judged = correct_count + incorrect_count
        summary = {
            "mode": args.mode,
            "timestamp": timestamp,
            "total": len(tests),
            "completed": i + 1,
            "correct": correct_count,
            "incorrect": incorrect_count,
            "error": error_count,
            "accuracy": round(correct_count / max(total_judged, 1), 4),
            "results": results,
        }
        with open(output_file, "w") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

    # Final summary
    total_judged = correct_count + incorrect_count
    print(f"\n{'='*60}")
    print(f"  BENCHMARK COMPLETE")
    print(f"  Mode: {args.mode}")
    print(f"  Tests: {len(tests)} ({n_golden} golden + {n_buggy} buggy)")
    print(f"  Correct: {correct_count} | Wrong: {incorrect_count} | No verdict: {error_count}")
    if total_judged > 0:
        print(f"  Accuracy: {correct_count}/{total_judged} = {correct_count/total_judged:.1%}")
    if results:
        avgs = [r["avg_step_time_sec"] for r in results if r["avg_step_time_sec"]]
        if avgs:
            print(f"  Avg step time: {sum(avgs)/len(avgs):.1f}s")
    print(f"  Output: {output_file}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
