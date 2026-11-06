# CLAUDE.md

Project: `journal-entry-tests`, a public, self-hosted Python command-line tool for fraud-risk triage of journal entries.

## Read order (every window)

1. `spec/INDEX.xml`
2. `context/code-standards.md`
3. `context/progress-tracker.md`
4. The spec of the unit being built (the files and test ids listed for that unit in `context/progress-tracker.md`)

## Rules

- One unit per window, in a fresh chat.
- Implement exactly the unit spec, no extras.
- Run the unit's tests and update `context/progress-tracker.md`.
- Do not edit files in `spec/`. A new feature goes back through the specification gate for that part only.
- A new bug goes into `current-issues.md`: analyse and propose a plan, wait for the owner's approval, fix, then delete the file once closed.
- Never use real data (only synthetic). Never write secrets (use environment variables and placeholders).
- No paid tools or APIs. Extra budget is 0 EUR.
- Each unit comes with a short plain explanation for the owner: what, why and how.
- English in all repository files. Portuguese (European, 1990 agreement) only in conversation with the owner (Vasco).
