# mano-afk

**Go AFK. Come back to a production-ready app.**

mano-afk is the first fully autonomous software development pipeline — from a single sentence to a deployed, tested, bug-fixed application. No prompts, no approvals, no babysitting. You describe what you want, grab a coffee, and come back to a running app with a complete test report.

What happens when you say:
```
"Build me a personal finance tracker with charts and budget management"
```

1. A structured PRD is generated with acceptance criteria (Given-When-Then)
2. Architecture is designed, code is written, app is deployed
3. Lint, API tests, and **real browser E2E tests** are executed automatically
4. An independent adversary agent reviews for bugs the builder missed
5. Failed tests trigger automatic fix → re-deploy → re-test loops (up to 10 rounds)
6. You get: a running app + `report.md` with every test result and fix history

**No human in the loop. The entire pipeline is autonomous.**

## The Problem

AI can write code. That's table stakes. But writing code is maybe 30% of shipping software. The other 70% — requirements, deployment, testing, debugging, fixing, re-testing — is where projects stall.

Every AI coding tool today stops at some variation of "here's the code, good luck." You still have to deploy it, test it, find the bugs, explain the bugs, wait for fixes, and re-test. That's not autonomous — that's autocomplete with extra steps.

## How mano-afk Solves It

### 1. PRD-First: Define Before You Build

Before writing a single line of code, mano-afk generates a structured PRD with acceptance criteria (L1/L2/L3 priority). Every test case traces back to a PRD requirement. Every bug fix maps to an AC number.

This eliminates the #1 failure mode of AI coding: **"the code works but doesn't match the intent."**

### 2. E2E Testing: The Final Mile of Automated Programming

Lint checks syntax. Unit tests check functions. API tests check endpoints. But none of them answer the question that matters: **does the app actually work when a human uses it?**

mano-afk closes this gap with real browser-based E2E testing — the final mile that turns "code that compiles" into "software that ships." Using the **Mano-P** vision model (or Claude CUA in cloud mode), it opens the app, clicks buttons, fills forms, navigates pages, and verifies that what the user sees matches what the user should see.

```bash
mano-afk run "Click Add Category, fill in 'Food', pick green, click Save" \
  --url "http://localhost:3000" \
  --expect "A category called Food with green color appears in the list"
```

**Why this matters:** An API test can pass while the button that calls it is broken. A unit test can pass while the layout renders nothing. E2E is the only test that catches what your users will actually experience.

### 3. [Mano-P](https://github.com/Mininglamp-AI/Mano-P): On-Device Vision for GUI Testing

[Mano-P](https://github.com/Mininglamp-AI/Mano-P) is a lightweight vision-language model that runs **entirely on your Mac**. No cloud API calls, no token costs, no data leaving your machine.

| | Mano-P (Local) | Cloud CUA |
|---|---|---|
| **Privacy** | Screenshots never leave your device | Sent to cloud API |
| **Cost** | $0 — runs on your hardware | ~$0.05-0.15 per test |
| **Setup** | `mano-afk install-model` | `ANTHROPIC_API_KEY` |
| **Offline** | Works without internet | Requires internet |

### 4. Adversary Review: Don't Let the Builder Test Itself

When the same agent builds and tests, it has a blind spot — it unconsciously avoids testing its own weak points. mano-afk fixes this with **separation of concerns**:

- **Build Agent**: writes code, deploys, fixes bugs
- **Adversary Agent**: independently reviews PRD + source code to find problems the builder missed
- **Main Agent**: triages each finding via code inspection, API test, or E2E test

The adversary catches what automated tests miss: usability gaps, data integrity issues, inconsistent behavior across features, missing edge cases.

### 5. Self-Evolution

mano-afk maintains two persistent files that survive across projects:

**`rules.md`** — Build rules learned from past failures. When a bug takes multiple fix iterations, the lesson is extracted and applied to all future projects.

**`preferences.md`** — Your accumulated taste. Color preferences, layout patterns, component styles. The system converges on your style over time.

### 6. True AFK

As long as minimal setup requirements are clear: **"AFK is from now on."**

From that point, every decision is autonomous. Deployment fails? It reads the logs. Test fails? It spawns a fresh fix agent. 10 iterations later, everything passes or you get a detailed report of what's left.

## Architecture

```
Step 0: User Setup (the only interaction point)
  │
Step 1: Prepare (autonomous from here)
  │
Step 2: Build (background sub-agent)
  │     Phase 1: PRD.md — requirements + acceptance criteria
  │     Phase 2: Architecture + README.md — test cases from PRD
  │     Phase 3: Code generation
  │     Phase 4: Deployment
  │
Step 3: Verify Deployment
  │
Step 4: Test
  │     4.1 Lint
  │     4.2 API Tests (curl)
  │     4.3 E2E Tests (mano-afk + Mano-P / Claude CUA)
  │     4.4 Adversary Review (independent sub-agent)
  │
Step 5: Fix Loop (up to 10 iterations)
  │
Step 6: Completion — report.md, update rules & preferences
```

## Getting Started

### Prerequisites

- [Claude Code](https://claude.ai/claude-code) or [OpenClaw](https://openclaw.ai)
- macOS with Apple Silicon (for Mano-P) or Anthropic API key (for cloud E2E)

### Install

```bash
brew install Mininglamp-AI/tap/mano-afk
```

### Setup

```bash
# Local mode (recommended on Mac — free, private, fast)
mano-afk install-model
mano-afk config --set e2e-mode local

# Or cloud mode
mano-afk config --set e2e-mode cloud
export ANTHROPIC_API_KEY=<your-key>

# Verify setup
mano-afk check
```

### Skill Installation

**Claude Code:**

Add the skill to your project's `.claude/settings.json`:

```json
{
  "permissions": {
    "allow": ["Bash(mano-afk:*)"]
  },
  "customInstructions": "Read and follow skill/claude/SKILL.md for mano-afk tasks."
}
```

Or simply tell Claude Code:
```
Read skill/claude/SKILL.md and follow it to build me a todo app.
```

**OpenClaw:**

Install from [ClawHub](https://clawhub.ai):
```
/install mano-afk
```

| Platform | SKILL.md | Key Differences |
|----------|----------|-----------------|
| Claude Code | `skill/claude/SKILL.md` | Agent tool, `run_in_background`, Auto mode |
| OpenClaw | `skill/openclaw/SKILL.md` | `sessions_spawn` with `runtime="subagent"` |

Both share the same `skill/references/` directory.

### Usage

Just describe what you want:

```
"Build me a todo app with categories and due dates"
"Create a habit tracker with daily streaks and weekly charts"
"Make a recipe app with ingredient parsing and shopping list"
"Build a kanban board with drag-drop columns and team assignment"
```

The skill handles everything else.

## Benchmark

mano-afk includes a [CUA Benchmark](benchmark/) — 100 test cases across 5 web applications for evaluating GUI automation agents. See [`benchmark/README.md`](benchmark/README.md) for full methodology.

**Mano-P 4B on MacBook Pro M5, 16GB:**

| Configuration | Accuracy | Avg Steps | Avg Step Time | Avg Tokens/Step |
|---------------|----------|-----------|---------------|-----------------|
| W8A16 | **58.0%** | 6.1 | 10.1s | 3,389 |
| W8A8 ([Cider](https://github.com/Mininglamp-AI/cider)) | **54.0%** | 6.93 | 10.4s | 3,104 |

## Project Structure

```
mano-afk/
├── skill/
│   ├── claude/SKILL.md             # Claude Code skill
│   ├── openclaw/SKILL.md           # OpenClaw skill
│   └── references/
│       ├── build-pipeline.md       # Build sub-agent instructions
│       ├── prd-template.md         # PRD generation template
│       ├── rules.md                # Learned build rules (evolves)
│       ├── preferences.md          # User style preferences (evolves)
│       ├── project-structure.md    # Directory layout template
│       ├── readme-template.md      # README generation template
│       └── report-template.md      # Build report template
├── scripts/
│   ├── main.py                     # CLI entry point
│   ├── agents/                     # Cloud (Claude CUA) + Local (Mano-P) agents
│   ├── judges/                     # Local + Cloud judge
│   ├── ui/                         # CustomTkinter overlay
│   ├── vlm_engine.py               # MLX VLM inference engine
│   ├── task.py                     # Task orchestration
│   ├── executor.py                 # Action execution (pynput + mss)
│   ├── config.py                   # Constants + user config
│   └── utils.py                    # Prompts, hotkey mapping
├── benchmark/
│   ├── README.md                   # Benchmark methodology
│   ├── tasks.json                  # 100 test cases
│   ├── run_benchmark.py            # Benchmark runner
│   └── results/                    # Test results per model
├── Formula/mano-afk.rb             # Homebrew formula
├── requirements.txt
└── pyproject.toml
```

## Philosophy

1. **PRD first.** Define what to build before building it. Every feature has acceptance criteria. Every test traces to a requirement.

2. **Test like a human.** If a human would find a bug by clicking a button, the test suite should click that button.

3. **E2E is the final mile.** Code that compiles isn't software. Software is what works when a real user touches it.

4. **Separate building from testing.** The agent that wrote the code is the worst person to test it.

5. **Learn from mistakes.** Every bug fixed is a lesson. Capture it, generalize it, apply it next time.

6. **Privacy by default.** Mano-P runs on your machine. Your screenshots, your data, your device.

7. **Autonomy means no half-measures.** If the user has to approve file writes or answer questions mid-build, it's not autonomous.

## License

MIT

## Links

- [mano-afk](https://github.com/Mininglamp-AI/mano-afk) — This project
- [CUA Benchmark](benchmark/) — GUI automation evaluation suite
- [ClawHub](https://clawhub.ai) — Skill marketplace
- [OpenClaw](https://openclaw.ai) — Agent framework
