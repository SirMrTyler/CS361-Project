# CS361 Project — Milestone #1 (Main Program)

**Sprint 1 Goal:** Log Workout Sessions (create + view history + edit).  
This repository contains a small monolith (no microservices yet) implemented as a Flask + SQLite + Vanilla JS web app.

## Quick Start

### Prereqs

- Python 3.10+ recommended

### Run locally

I personally use a venv to prevent dependency issues down the line/across projects. SOOOO, if that's what whoever wants to use this wants to do (again, I recommend it); here are the instructions:

```bash
# from repo root
python -m venv .venv

# macOS/Linux
source .venv/bin/activate

# Windows (PowerShell)
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
python app.py
```

Open: `http://127.0.0.1:5000`

### Data persistence

The SQLite DB is created automatically at:

- `instance/workouts.sqlite3`

> Note: I added `instance/` to gitignore so I (or you fellow classmates) don’t accidentally commit my personal data.

---

## Implemented User Stories (Milestone #1)

These map directly to the GitHub issues for Sprint 1.

### 1) Log Workout Session (Issue #11)

**User story:**  
“As a lifter, I want to log a workout session with exercises, sets, reps, and weight so that I can track my training over time.”

**Functional acceptance criteria:**

- Given the user is on the New Workout screen, when they enter a workout date and at least one exercise with at least one set (weight and reps) and press Save, then the workout is saved and appears in Workout History.
- Given the user attempts to save a workout with no exercises, when they press Save, then the app displays an error message and does not save the workout.
- Given the user enters a set with reps < 1 or weight < 0, when they try to add the set, then the app rejects the input and shows a validation message.

### 2) View Workout History (Issue #12)

**User story:**  
“As a lifter, I want to view my workout history and open a past workout’s details so that I can plan my next session based on what I did before.”

**Functional acceptance criteria:**

- Given the user has at least one saved workout, when they open Workout History, then the app displays a list of workouts sorted by date (newest first).
- Given the user selects a workout from the history list, when the workout opens, then the app displays its exercises and sets (weight and reps).
- Given the user has no saved workouts, when they open Workout History, then the app shows an empty-state message that tells the user how to create their first workout.

### 3) Edit Workout Entry (Issue #13)

**User story:**  
“As a lifter, I want to edit a logged workout (e.g., fix weight/reps or add/remove a set) so that my training data stays accurate.”

**Functional acceptance criteria:**

- Given the user is viewing a saved workout, when they choose Edit, change a set’s weight or reps, and press Save Changes, then the updated values appear immediately and remain after closing and reopening the app.
- Given the user is editing a workout, when they remove a set and confirm the removal, then the set is deleted from that workout.
- Given the user is editing a workout, when they press Cancel, then no changes are applied to the saved workout.

---

## Inclusivity Heuristics (How the UI reflects all 8)

1. **Explain benefits:** “Why this helps” section + expandable details.
2. **Explain costs:** explicit note about delete being permanent + time estimate.
3. **Let users get as much info as they want:** “More/less info” toggles (collapsible guidance).
4. **Keep familiar features:** standard date picker, forms, buttons, clear labels.
5. **Undo/backtracking:** Undo last set-entry + Cancel + Back to history.
6. **Explicit path:** numbered steps and clear “Save” call-to-action.
7. **Different approaches:** add exercise/set via button OR Enter key.
8. **Encourage mindful tinkering:** confirmations for destructive actions + warn on unsaved changes.

---

## Quality Attributes Demonstrated

- **Usability & Inclusivity:** quick start guidance + optional toggles, single-confirm for destructive actions, and undo for last set entry.
- **Responsiveness:** history endpoint includes a `timing_ms` value (and there’s a “Generate 200 sample workouts” button for demonstrating list load time).
- **Reliability:** DB operations for create/update are done inside transactions; edits persist after restart.

---

## TODO - Notes - Issues

1. Add ability to delete multilple workouts at once
2. Add picture entries capabilities to exercises.
3. Add premade exercise/workouts templates (helps with new users).
