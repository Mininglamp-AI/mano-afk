# Build Rules

General rules learned from past projects. Max 100 rules — remove the least valuable when adding beyond the limit.

## Technical Defaults

1. **Python projects: always use a virtual environment.** Create venv in the project directory and install all deps inside it. Never `pip install` globally.
2. **Prefer SQLite over PostgreSQL for simple projects.** Use PostgreSQL only when the app needs concurrent multi-user writes, complex queries, or multiple related tables with joins.
3. **Pin dependency versions.** Use exact versions in `requirements.txt` and `package.json` to prevent build breakage from upstream changes.
4. **Use environment variables for all configuration.** Never hardcode API keys, database paths, ports, or secrets. Provide sensible defaults in code.
5. **Create `.gitignore` appropriate for the stack.** Include node_modules, __pycache__, .env, venv, build artifacts, and IDE files.

## Code Quality

6. **One component per file.** Keep components, routes, and models in separate files. Avoid god files with multiple unrelated exports.
7. **Every API route must return proper HTTP status codes.** 200 for success, 201 for created, 400 for validation errors, 404 for not found, 500 for server errors. Never return 200 with an error in the body.
8. **Add input validation at the API boundary.** Validate request bodies before processing. Return 400 with a clear error message for invalid input.
9. **Frontend must handle three states for every async operation:** loading, success, and error. Never leave the user staring at a blank screen.

## Lint

10. **JavaScript/TypeScript: use ESLint with recommended rules.** Generate `.eslintrc.json` with `"extends": ["eslint:recommended"]`. For React, add `plugin:react/recommended`.
11. **Python: use Ruff.** Generate `ruff.toml` with default rules. Enable `select = ["E", "F", "I"]` at minimum (errors, pyflakes, isort).
12. **Zero lint errors before proceeding to other tests.** Auto-fix what can be auto-fixed, manually fix the rest.

## Adversary Testing

13. **Adversary sub-agent receives README and source code access.** It reviews findings in two layers: Layer 1 (user perspective) from README and running app, Layer 2 (code perspective) from reading source code. No build history or prior test results.
14. **Adversary scope: functional correctness, edge cases, error handling, data integrity.** Do NOT test for security attacks (XSS, SQL injection, CSRF) unless explicitly requested.
15. **Maximum 10 adversary test cases per session.** Focus on high-value tests the builder likely missed.
16. **Always add delete confirmation dialogs for destructive actions.** Any button that permanently removes user data (holdings, entries, records) must show a `window.confirm()` or custom confirmation dialog before executing.
17. **Persist triggered/computed state changes to the backend.** If the frontend computes a state change (e.g., alert triggered), it must call the corresponding backend endpoint to persist it. Client-side-only state is lost on refresh.
18. **Add upper bound validation for numeric inputs.** Beyond `> 0`, validate that quantities and prices don't exceed a reasonable maximum (e.g., `999,999,999,999`) to prevent Infinity/NaN in calculations.
19. **Modals must close on Escape key press.** Add a `keydown` event listener for the Escape key on all modal components. This is a standard UX expectation.
20. **Wrap all async handlers in try/catch with user-facing error feedback.** Every `async` handler that calls an API must have a try/catch that shows a toast or inline error. Unhandled promise rejections leave users without feedback.
21. **Cache third-party API responses with rate limits.** When proxying external APIs (CoinGecko, OpenWeather, etc.), add server-side in-memory caching with a TTL matching the refresh interval. On rate-limit (429) or network errors, return cached data instead of forwarding the error. Without caching, normal usage (auto-refresh, multiple users, testing) will quickly trigger rate limits.
