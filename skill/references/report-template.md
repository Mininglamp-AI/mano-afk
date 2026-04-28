# Build Report: {Project Name}

## Summary
- Total iterations: {N}
- Final status: {ALL PASS / X failures remaining}
- Total time: {elapsed}

## Test Results

### Lint
| Linter | Errors | Warnings | Status |
|---|---|---|---|
| ESLint | 0 | 0 | PASS |

### API Tests
| ID | AC | Test | Result | Notes |
|---|---|---|---|---|
| api_1 | AC-2.1.1 | GET /api/items | PASS | — |
| api_2 | AC-2.2.1 | POST /api/items | PASS | — |
| api_3 | AC-2.2.2 | POST /api/items (invalid) | FAIL -> PASS (iter 2) | Fixed validation |

### E2E Tests
| ID | AC | Journey | Result | Notes |
|---|---|---|---|---|
| e2e_1 | AC-2.1.1 | Page load visual check | PASS | — |
| e2e_2 | AC-2.2.1 | Create item | FAIL | Confirm dialog not dismissed |

### Adversary Tests
| ID | Finding | Severity | Result | Notes |
|---|---|---|---|---|
| adv_1 | Empty form submission | Medium | PASS | — |
| adv_2 | Rapid double-click submit | High | FAIL | Created duplicate entry |

## Iteration Log

### Iteration 1 (Initial Build)
- **Status**: FAIL (3/10 tests failed)
- **Failures**:
  - api_3 (AC-2.2.2): Missing input validation, returned 500 instead of 400
  - e2e_1 (AC-2.1.1): VISUAL_DEFECT — Card component has no padding, text overlaps border
  - e2e_2 (AC-2.2.1): Delete confirm dialog not handled

### Iteration 2
- **Fixed**:
  - api_3: Added request body validation in POST /api/items route
  - e2e_1: Added padding: 16px to .card-body CSS class
- **Files modified**: backend/routes/items.py, frontend/src/styles/card.css
- **Status**: FAIL (1/10 tests failed)
- **Remaining failures**:
  - e2e_2 (AC-2.2.1): Confirm dialog not dismissed

### Iteration N (Final)
- **Fixed**:
  - e2e_2: Added window.confirm() handler in delete button onClick
- **Files modified**: frontend/src/components/ItemDetail.jsx
- **Status**: ALL PASS

## Lessons Learned
- {Any new rules written to new-rules.md during this build}
