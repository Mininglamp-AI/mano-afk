# {Project Name}

{One-sentence description}

## Tech Stack

| Layer | Technology | Reason |
|---|---|---|
| Frontend | {framework} | {why} |
| Backend | {framework} | {why} |
| Database | {db} | {why} |

## Architecture

### API Endpoints
| Method | Path | Description | Request | Response |
|---|---|---|---|---|
| GET | /api/items | List all items | — | `[{id, name, ...}]` |
| POST | /api/items | Create item | `{name, ...}` | `{id, name, ...}` |

### Data Model
| Entity | Fields |
|---|---|
| {Entity} | {field1} ({type}), {field2} ({type}), ... |

### File Structure
{directory tree}

## Setup & Deployment

```bash
./deploy/start.sh
```

## Test Cases

Test cases are derived from the acceptance criteria in `PRD.md`. Each test ID references the corresponding AC number for traceability.

### Lint
- {Linter} with {config}: zero errors required

### API Tests
| ID | AC | Method | Path | Input | Expected Status | Expected Response |
|---|---|---|---|---|---|---|
| api_1 | AC-2.1.1 | GET | /api/items | — | 200 | `[{id, name, ...}]` |
| api_2 | AC-2.2.1 | POST | /api/items | `{name: "test"}` | 201 | `{id: 1, name: "test"}` |
| api_3 | AC-2.2.2 | POST | /api/items | `{}` | 400 | `{error: "name is required"}` |
| api_4 | AC-2.1.3 | GET | /api/items/999 | — | 404 | `{error: "not found"}` |

### E2E Tests (VLA via mano-afk)

**Writing rules:**
- **task**: Operation path only — clicks, inputs, navigation. No verification verbs (verify, check, ensure). No conditionals (if, any). Targets must be specific ("the first item", not "any item").
- **expect**: Observable page state only — what is visible after operations. No conditionals. No instructions.
- Tests run sequentially top-to-bottom. Use Depends to declare state dependencies.
- `--url` opens the page before the agent starts — do not include URL navigation in task.
- Merge tests that verify the same screen with no additional operations.

| ID | AC | Depends | Task | Expect |
|---|---|---|---|---|
| e2e_1 | AC-2.1.1 | — | `mano-afk run "Open the Items tab" --url "http://localhost:3000" --expect "..."` | List of items with names and dates. No broken layout or missing images. |
| e2e_2 | AC-2.2.1 | — | `mano-afk run "Click Add Item, type 'Test' in the name field, click Submit" --url "http://localhost:3000" --expect "..."` | "Test" appears as a new row in the items list |
| e2e_3 | AC-2.2.3 | e2e_2 | `mano-afk run "Click the delete icon on the first item row, confirm the deletion" --url "http://localhost:3000" --expect "..."` | The item is removed. "No items yet" message displayed. |

### Adversary Tests
Designed and executed by independent sub-agent based on PRD.md and this README. Up to 10 test cases covering edge cases, error handling, and spec compliance.
