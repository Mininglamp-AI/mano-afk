# CUA Benchmark

A benchmark suite for evaluating Computer Use Agent (CUA) models on real-world web application testing tasks.

## Overview

| Metric | Description | Source |
|--------|-------------|--------|
| **Accuracy** | Judge verdict matches expected (PASS/FAIL) | `judge_verdict` vs `expected_verdict` |
| **Steps** | Number of actions taken per task | `step_count` |
| **Step Time** | Average time per action step (model-only) | `avg_step_time_sec` |
| **Total Time** | End-to-end time per task | `elapsed_sec` |
| **Token Usage** | Prompt + generation tokens per task | `token_usage` |

## Test Design

100 test cases across 5 web applications:

| Project | Description | Framework | Tests |
|---------|-------------|-----------|-------|
| **TripSplit** | Travel expense splitting | Vanilla JS SPA | 20 (15 golden + 5 buggy) |
| **md-wechat** | Markdown → WeChat formatter | marked.js + highlight.js | 20 (16 golden + 4 buggy*) |
| **OMS** | Order management system | Vanilla JS + localStorage | 20 (15 golden + 5 buggy) |
| **Family Ledger** | Household bookkeeping | Vue 3 + Element Plus | 20 (15 golden + 5 buggy) |
| **Life Dashboard** | Personal dashboard widgets | React 18 + Vite | 20 (15 golden + 5 buggy) |

\* md-wechat has 4 bugs; B5 is pending.

### Golden vs Buggy

- **Golden tests** (76 tasks): Run on the bug-free version. Expected verdict: **PASS**.
- **Buggy tests** (24 tasks): Run on the version with injected bugs. Expected verdict: **FAIL** (the bug causes visible incorrect behavior).

```
Accuracy = tasks where judge verdict matches expected / total judged
```

### Stateless Guarantee

All projects reset to initial state on page load:
- Single HTML projects: `localStorage.clear()` + fixture injection
- Multi-file projects (Life Dashboard): `/api/reset` restores database

No manual cleanup needed between tests.

## Test Flow

```
1. Open target URL (golden or buggy, auto-selected by bug_triggered field)
2. Execute mano-afk with task + expected_result
3. Agent operates via screenshots + actions
4. Agent outputs result.json (step_timings, token_usage, status)
5. Judge compares final state against expected_result → PASS/FAIL
6. Close browser tab
7. Repeat next task (stateless: page refresh resets state)
```

## Files

```
benchmark/
├── README.md              ← this file
├── tasks.json             ← 100 test cases with URLs, tasks, expected results, max_steps
├── run_benchmark.py       ← benchmark runner (auto golden/buggy selection)
└── results/               ← benchmark result JSONs (per-model, per-run)
```

## Usage

### Run all 100 tests (local model)

```bash
uv run benchmark/run_benchmark.py --mode local
```

### Run all 100 tests (cloud model)

```bash
uv run benchmark/run_benchmark.py --mode cloud
```

### Run a specific project

```bash
uv run benchmark/run_benchmark.py --mode local --project TS
```

### Run a range

```bash
uv run benchmark/run_benchmark.py --mode local --start TS-01 --end TS-05
```

## Output Format

Each run produces `benchmark/results/bench-{mode}-{timestamp}.json`:

```json
{
  "mode": "local",
  "timestamp": "20260428_103000",
  "total": 100,
  "correct": 72,
  "incorrect": 25,
  "error": 3,
  "accuracy": 0.7423,
  "results": [
    {
      "id": "TS-01",
      "project": "TS",
      "version": "buggy",
      "bug_triggered": "B1",
      "expected_verdict": "FAIL",
      "status": "COMPLETED",
      "step_count": 6,
      "step_timings_sec": [9.4, 10.2, ...],
      "avg_step_time_sec": 10.5,
      "elapsed_sec": 85.3,
      "judge_verdict": "FAIL",
      "judge_reason": "...",
      "token_usage": {
        "prompt_tokens": 18400,
        "generation_tokens": 1200,
        "steps": [...]
      },
      "session_dir": "~/mano-trajectory/result/sess-..."
    }
  ]
}
```

Each test's full trajectory (screenshots, raw model responses) is saved in `session_dir`.

## tasks.json Schema

```json
{
  "id": "TS-01",
  "title": "Create trip and verify display",
  "project": "tripsplit",
  "url": "https://mano.mininglamp.com/tripsplit/buggy.html",
  "task": "Natural language instruction for the agent...",
  "expected_result": "What the judge should verify...",
  "bug_triggered": "B1",
  "max_steps": 8
}
```

- `url`: Golden URL for normal tests, buggy URL for bug tests (pre-assigned)
- `bug_triggered`: `"none"` for golden tests, `"B1"`~`"B5"` for buggy tests
- `max_steps`: Maximum allowed steps before timeout

## Bug Catalog

Each project has 5 injected bugs (md-wechat has 4, B5 pending):

| Project | B1 | B2 | B3 | B4 | B5 |
|---------|----|----|----|----|-----|
| TripSplit | Create doesn't refresh | Sort reversed | Settlement direction wrong | Amount text invisible | Delete JS error |
| md-wechat | Footnotes all [0] | No zebra stripes | Theme switch broken | Copy JS error | *pending* |
| OMS | Sort reversed | Pending count wrong | Status skip | Labels all gray | Export JS error |
| Family Ledger | Storage write fails | Delete condition inverted | Category ignores type | Income amount black | Progress bar fixed color |
| Life Dashboard | Total off by $100 | Checkbox won't toggle | Timer min/sec swapped | Habit check invisible | Forecast temp NaN |
