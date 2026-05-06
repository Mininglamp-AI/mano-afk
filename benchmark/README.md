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

## Benchmark Results

**Test Environment:** MacBook Pro 14", Apple M5, 16GB

**Model:** Mano-P 4B (W8A16 / W8A8 8-bit quantized)

### Mano-P 4B W8A16

| Metric | Value |
|--------|-------|
| **Accuracy** | **58/100 = 58.0%** |
| Avg steps | 6.1 |
| Prefill speed | ~1,253 tok/s |
| Avg tokens/step | prompt: 3,222 · gen: 167 · total: 3,389 |

### Mano-P 4B W8A8 (with [Cider](https://github.com/Mininglamp-AI/cider) acceleration)

| Metric | Value |
|--------|-------|
| **Accuracy** | **54/100 = 54.0%** |
| Avg steps | 6.93 |
| Prefill speed | ~1,453 tok/s |
| Avg tokens/step | prompt: 2,935 · gen: 168 · total: 3,104 |

> **Note on W8A8:** W8A8 accelerates prefill via INT8 TensorOps but requires extra memory to store both original and quantized weights simultaneously. On memory-constrained devices, this additional pressure can cause unified memory swapping that negates the prefill speedup — resulting in slower overall inference than W8A16. Ensure sufficient free memory (recommended: 4GB+ headroom beyond model size) before enabling W8A8.

## Test Design

100 test cases across 5 web applications, all built autonomously via mano-afk:

| Project | Description | Framework | Tests |
|---------|-------------|-----------|-------|
| **TripSplit** | Travel expense splitting | Vanilla JS SPA | 20 (15 golden + 5 buggy) |
| **md-wechat** | Markdown → WeChat formatter | marked.js + highlight.js | 20 (16 golden + 4 buggy*) |
| **OMS** | Order management system | Vanilla JS + localStorage | 20 (15 golden + 5 buggy) |
| **Family Ledger** | Household bookkeeping | Vue 3 + Element Plus | 20 (15 golden + 5 buggy) |
| **Life Dashboard** | Personal dashboard widgets | React 18 + Vite | 20 (15 golden + 5 buggy) |

### Golden vs Buggy

Each application has two versions. The **golden** version is the correct, bug-free build. The **buggy** version is derived from golden with specific bugs injected (UI defects, logic errors, JS exceptions) — designed to test whether the model can detect that something is wrong.

- **Golden tests** (76 tasks): Run on the bug-free version. Expected verdict: **PASS**.
- **Buggy tests** (24 tasks): Run on the bug-injected version. Expected verdict: **FAIL**.

```
Accuracy = tasks where judge verdict matches expected / total judged
```

### Stateless Guarantee

All projects reset to initial state on page load:
- Single HTML projects: `localStorage.clear()` + fixture injection
- Multi-file projects (Life Dashboard): `/api/reset` restores database

No manual cleanup needed between tests.

## Usage

```bash
# Local model (Mano-P)
uv run benchmark/run_benchmark.py --mode local

# Cloud model (Claude CUA)
uv run benchmark/run_benchmark.py --mode cloud
```

## Output Format

Each run produces a JSON file:

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
