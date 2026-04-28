# {Project Name} — PRD

## 1. Product Overview

**Core value:** {one sentence — why this product exists}
**Target user:** {who uses it and how}
**Scope boundary:** {what is explicitly NOT included}

## 2. Functional Requirements

Each feature includes acceptance criteria (AC) in Given-When-Then format. AC numbering: `AC-{feature}.{seq}`, tagged L1 (core path), L2 (business rules), or L3 (edge cases).

### 2.1 {Feature Name}

**Description:** {what it does, one paragraph}

**AC-2.1.1 (L1):** {title}
Given {precondition}
When {action}
Then {expected result}

**AC-2.1.2 (L2):** {title}
Given ... When ... Then ...

**AC-2.1.3 (L3):** {title}
Given ... When ... Then ...

## 3. Business Rules

### Data Constraints

| Field | Type | Constraint |
|---|---|---|
| {field} | {type} | {required/optional, range, format, max length} |

### State Machine (if applicable)

`{state_1} → {state_2} → ... → {terminal_state}`
- {transition rules, terminal state behavior}

## 4. Error & Exception Design

| Scenario | User-facing Message | Behavior |
|---|---|---|
| {scenario} | "{message}" | {recovery path} |

Every user-reachable error must have an explicit message and recovery path. No "TBD".

## 5. Visual Design

### Color Palette

Derive from the product's domain. Reference `preferences.md` for the user's global taste. Define at minimum: Primary (+ light/dark variants), Success, Warning, Error, Background, Surface, Text Primary/Secondary, Border — all with hex values.

### Layout

```
{ASCII wireframe of the main page}
```

{Brief layout description: navigation, content area, responsive behavior}

### Key Component Styles

Buttons, Cards, Forms, Tables — define border-radius, shadow, padding, hover/active transitions for each.

