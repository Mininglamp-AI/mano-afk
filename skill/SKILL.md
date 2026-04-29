---
name: mano-afk
description: Autonomous full-cycle app builder. Turns a natural language description into a production-ready application — PRD, architecture, code, deployment, testing, and bug fixing — fully automated, no human in the loop. Self-improving across projects via persistent build rules and user preferences. Use when the user wants to build an application end-to-end without manual intervention.
---

# mano-afk (Claude Code)

Fully automated pipeline that builds, deploys, and tests applications from a natural language description. The user is AFK for the entire duration. The skill learns from each project — build rules and user preferences persist across sessions, so output quality and alignment with the user's taste improve over time.

**References directory:** `references/` (shared with OpenClaw version)

## Prerequisites

This skill requires **Auto mode** for fully autonomous execution. If not already in Auto mode, remind the user to press **Shift+Tab** to switch to Auto mode before proceeding.

## Architecture

Three roles collaborate to deliver the application:

- **Main Agent** (you): orchestration, test execution, fix coordination, user communication
- **Build Sub-agent** (via Agent tool): requirements → architecture → code → deploy → bug fixes
- **Adversary Sub-agent** (via Agent tool): independent test case design (does not execute tests)

The main agent delegates code generation to a sub-agent (the longest phase) and stays free during that time. The main agent runs all tests directly for full visibility into results.

## Orchestration

**AFK rule:** Step 0 is the only user interaction window. From Step 1 onward, make all decisions autonomously — never ask the user. Ambiguous decisions (8bit vs float, React vs Vue, port selection) use the most reasonable default and document in PRD.md. Only stop if completely infeasible (missing hardware, no permissions, 10 fix iterations exhausted).

### Step 0: User Setup (interactive)

This is the only step where the agent may ask the user questions.

**Requirements triage:** If the request is too vague to determine core functionality (e.g., "build me an app"), or contains ambiguous requirements that could lead to fundamentally different products, ask the user to clarify — keep it to 1-2 focused questions, not a long interview. Non-critical gaps (visual design, validation rules, tech stack, layout) are filled autonomously by the build sub-agent.

**App LLM check:** If the request involves LLM/AI features, ask the user for the environment variable name that holds the API key (e.g., `OPENAI_API_KEY`). The build sub-agent will reference this env var in the generated code.

**E2E test mode:** Check `mano-afk config --get e2e-mode` (`local` or `cloud`).

- **`local`** — requires `default-model-path` to be configured via `mano-afk config --set default-model-path <path>`.
- **`cloud`** — requires `ANTHROPIC_API_KEY` environment variable to be set.
- **Not set** — first-time setup. Check the platform:
  - **macOS**: ask the user: Local (Mano-P) or Cloud (Anthropic API key)?
  - **Other platforms**: Local is not available. Ask the user to configure Cloud or Skip.
  - If **Local**: run `mano-afk check` to verify SDK and model. Follow the printed guidance to resolve any missing components (install SDK, set model path, etc.).
  - If **Cloud**: ask the user to set `export ANTHROPIC_API_KEY=<key>` in their shell. Run `mano-afk check` to confirm.
  - If `mano-afk run` or `mano-afk check` prints setup guidance (missing model path, missing API key), follow the instructions in the output to help the user complete configuration.
  - If the user declines both → run `mano-afk config --set e2e-mode skipped` to persist the choice, then **Skip** E2E tests (logged in `report.md`).
- **`skipped`** — user previously declined E2E setup. Skip E2E tests without re-asking.

**Auto mode check (Claude Code only):** If not already in Auto mode, remind the user to press **Shift+Tab** to switch to Auto mode. This is required for fully AFK execution — without it, every file write and sub-agent spawn will prompt the user.

Tell the user: **"Hold the beer. AFK from now on."**

### Step 1: Prepare (autonomous — no user interaction)

Derive a short, kebab-case project name from the request (e.g., "make me a todo app" → `todo-app`).

**Project directory:** Read the configured project root via `mano-afk config --get projects-dir` (default: `~/Projects/`). Project directory: `{projects-dir}/{project-name}/`.

Read `references/report-template.md` — you will use it in Step 4 to write `report.md`. Note the absolute path to the `references/` directory — it will be passed to sub-agents for the remaining reference files.

### Step 2: Build (sub-agent)

Use the **Agent tool** to spawn a build sub-agent with `run_in_background: true`. Construct the prompt with:

1. The absolute path to `build-pipeline.md` — instruct the sub-agent to read and follow it
2. The absolute path to `references/` — the sub-agent reads rules, preferences, and templates as needed
3. The user's original request, verbatim
4. The project directory path

Respond to the user immediately with what is being built and the project directory. The build sub-agent follows 4 phases internally: **Phase 1** generates `PRD.md` (product requirements with acceptance criteria), **Phase 2** designs architecture and generates `README.md` (with test cases derived from PRD), **Phase 3** writes code, **Phase 4** deploys. Wait for `progress.md` to show `status: ready_for_testing`.

**Timeout:** Set the Agent tool timeout to at least 1800000ms (30 minutes). Build tasks take a long time.

### Step 3: Verify Deployment

Before testing, confirm the app is accessible:
1. Check that `deploy/start.sh` exists in the project
2. Run it if servers are not already running
3. Verify with `curl` or port check
4. If deployment fails (start.sh missing, server crashes, port unreachable), read `deploy/backend.log` and `deploy/frontend.log`, then go to Step 5 (Fix Loop) with the deployment error as the failure description

### Step 4: Test

Execute every test case defined in the README across all categories. No test case may be skipped or deferred.

Before starting each category, count the total test cases from the README. Print a progress counter for each test: `[3/18] api_3 PASS` or `[5/18] api_5 FAIL`. This makes skipped tests visible — if the counter jumps from 3 to 7, tests 4-6 were skipped.

Record results in `report.md` (use the report template). On failure, include full error output (response body, stderr, logs).

**Headless environments:** If no graphical desktop is available, skip VLA tests (4.3). Adversary review (4.4) still runs — triage uses code inspection and curl, not mano-afk.

#### 4.1 Lint

Run the linter configured by the build sub-agent. Auto-fix what's possible (`--fix`), then report remaining errors.

#### 4.2 API Tests

Run every API test case defined in the README. Use `curl -s -w "\nHTTP_STATUS:%{http_code}\n"` to capture response body and status code. Print full response body on failure.

**mano-afk requirement (4.3):** Install `mano-afk` if missing. macOS: `brew install Mininglamp-AI/tap/mano-afk`. If installation fails, skip 4.3 and log the reason.

#### 4.3 VLA Tests (E2E)

Read `mano-afk config --get e2e-mode`. If `local` → use Local mode. If `cloud` → use Cloud mode. If `skipped` or not set → Skip (record reason in `report.md`).

**Database reset:** Before running the first E2E test, clear all application tables (e.g., `DELETE FROM` each app table, or delete and re-initialize the SQLite file). This removes residual data from API tests. Do NOT reset between individual E2E tests — they run sequentially and may depend on state created by prior tests.

Run every E2E test case defined in the README using the chosen mode:

```bash
mano-afk run "{steps}" --url "{url}" --expect "{expected}"
```

`--url` opens the target page in the default browser before the agent starts. The agent sees the page already loaded — do NOT include "Open localhost:..." in the task steps.

All execution parameters (`--local`/`--cloud`, `--max-steps`, `--minimize`) are read from `mano-afk config`. CLI flags override config when specified. Use `mano-afk config --list` to see current values.

Execution rules:
- Run each test sequentially using Bash tool with `timeout: 1800000` (30 minutes)
- Do NOT kill `mano-afk` with SIGKILL or SIGTERM. To stop a session, use `mano-afk stop`
- If 409 (session conflict), run `mano-afk stop`, wait 5 seconds, then retry
- If a `mano-afk` process is killed unexpectedly, run `mano-afk stop` to clean up before retrying
- Do not use mouse/keyboard while a test is running

#### 4.4 Adversary Review

After all previous tests pass, use the **Agent tool** to spawn an adversary sub-agent. Construct the prompt with:
1. Role: "You are an independent QA reviewer. Your job is to identify potential problems the builder likely missed."
2. The full content of the project's `PRD.md` (requirements and acceptance criteria) and `README.md` (architecture and test cases)
3. The project directory path (the adversary reads source code for code-level findings)

The adversary does NOT interact with the running app — it reviews requirements and code only.

The adversary sub-agent **identifies potential problems only** — it does NOT execute anything. It returns findings in two layers, each as a table with columns: ID, Finding, Severity, Suggested Verification.

- **Layer 1 — User perspective**: usability gaps, cross-feature consistency, confusing flows, poor UX
- **Layer 2 — Code perspective**: data integrity, missing validation, error handling, state consistency

Constraints: cover both layers, do NOT repeat issues already in README test cases, do NOT flag security vulnerabilities (XSS, SQL injection, CSRF).

**Triage each finding yourself** using the appropriate method: code inspection (schema/config issues), API test (backend behavior via curl), or E2E test (UI rendering, user flows, visual state). At least 2-3 findings must be verified via E2E test. **Reset the database before running adversary E2E verifications** to avoid pollution from prior tests. Record each verdict in report.md: confirmed (→ fix loop) or dismissed (with reason).

### Completion Checklist (before proceeding to Step 5 or 6)

Before moving forward, verify each item. If any is "no", go back and complete it.

- [ ] Every API test case in README executed and recorded
- [ ] Every E2E test case in README executed and recorded
- [ ] Adversary review completed with findings from both layers
- [ ] At least 2-3 adversary findings verified via E2E test
- [ ] All confirmed adversary findings entered into fix loop

### Step 5: Fix Loop

If any test fails:

1. Collect all failures with full error output (response body, stderr, logs, mano-afk output)
2. Use the **Agent tool** to spawn a **new** build sub-agent in fix mode (`run_in_background: true`, timeout 1800000ms) — provide:
   - The absolute path to `build-pipeline.md` (fix mode does not need other reference files)
   - Project directory path
   - Detailed failure descriptions: test ID, command run, expected result, actual result, full error output
3. Wait for the sub-agent to fix and re-deploy (`progress.md` shows `status: ready_for_testing`)
4. Re-run failed tests with the same tool and method used in the original test. A test verified via E2E test must be re-verified via E2E test.
5. Repeat until all pass (max 10 iterations)

**E2E false positives:** If an E2E test fails but you inspect the code and confirm the implementation is correct (the failure is a vision model misinterpretation), dismiss it as a false positive in `report.md` with your reasoning. Do not enter the fix loop for false positives — fixing correct code wastes iterations.

**Step back on repeated failures:** If the same test fails 2+ times, include a note in the fix prompt: "This test has failed N times. Previous fix attempts: [descriptions]. Consider a structural fix rather than a patch."

**Exhausted iterations:** If 10 iterations are reached and failures remain, proceed to Step 6 with current results. Finalize `report.md` with all remaining failures, iteration history, and a summary of what was attempted.

### Step 6: Completion

- Summarize to the user: total tests, pass/fail, project directory
- **Update rules:** Review the fix loop history. If any error pattern would prevent the same class of bug in a future project, add a general rule to `references/rules.md` (max 100, remove least valuable if full). Also merge any `new-rules.md` the build sub-agent wrote in the project root.
- **Update preferences:** If the user gives follow-up feedback (styling, features), update `references/preferences.md`

## Reference Directory

The `references/` directory contains files that evolve across projects:

| File | Purpose | Max entries |
|---|---|---|
| `build-pipeline.md` | Build sub-agent instructions (phases 1-4 + fix mode) | — |
| `rules.md` | General build rules, lessons learned | 100 |
| `preferences.md` | User styling/UX preferences | 50 |
| `prd-template.md` | PRD generation template (5 chapters) | — |
| `project-structure.md` | Standard directory layout template | — |
| `readme-template.md` | README.md generation template | — |
| `report-template.md` | report.md generation template | — |

Rules and preferences are updated during execution (fix loop lessons, post-completion feedback) and persist across projects.
