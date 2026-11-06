# Next steps

What is still untested and what the next unit needs. `spec/` wins over this file.
Delete an item once its test passes, and delete this file when nothing is left.

## Still to test

Status of the 27 tests in `spec/TESTS.xml`: 20 fully passing, 0 partly proven, 7 not started. All 7 are manual.

| Unit | Manual tests |
|---|---|
| U7 | test.ci_matrix (GitHub Actions on Ubuntu and Windows, Python 3.11 and 3.14), test.readme_checklist, test.no_real_data, test.budget_zero, test.design_contrast, test.publish_permission |
| U8 (optional, outside v1) | test.word_scope |

### Checks outside the test list

- Run on Ubuntu: so far everything ran only on Windows. Covered by test.ci_matrix.
- A `results.xlsx` really held open by Excel: the tests force `os.replace` to fail, and no run has used a real lock with `analyze`.
- Owner review of U2, U3, U5 and U6: findings E01 to E06 are closed; see `context/progress-tracker.md`.
- Specification network still marked unverified: the official checker is unavailable.

## What U7 needs: CI and README

Build in a fresh chat, following the read order in `CLAUDE.md`. Show the owner a plan first: this list is not an approved plan.

### CI (`DEPLOYMENT.xml`)

- Workflow in `.github/workflows`, which holds only `.gitkeep` so far.
- Trigger: every push and every pull request.
- Matrix: Python 3.11 and 3.14, each on `ubuntu-latest` and `windows-latest` (4 jobs).
- Steps: checkout, setup-python, `pip install -c constraints.txt -e .[dev]`, `ruff check`, `pytest`.
- The install step also creates the `journal-entry-tests` script, which `tests/test_cli.py` needs.
- No secrets.
- Decide whether to pin `setuptools` (build) and `python-docx` (the `word` extra), which `constraints.txt` does not cover.

### README

Fill in the `TODO` comments in `README.md`:

- Badges and a short demo description.
- One short paragraph per test, taken from the final rules.
- Install: Python 3.11 or later, a virtual environment, `constraints.txt`.
- An explanation of each option and an example run on synthetic data. `--help` lists the options without describing them, so the README is where they are explained.
- A column-by-column table of the input CSV, with examples, and that broken quoting makes the whole file unreadable (code 2) with no line number in the message.
- The columns of each sheet.
- The tested size of 100000 rows (`huge_file` in `SECURITY.xml`).
- The complete list of limits, including 1048573 rows per sheet (code 1) and the known limit of unclosed quotes in `context/progress-tracker.md`.

The README must state: the warning that an alert is not proof of fraud, English text, the MIT licence, install and usage, the input table (`crit.readme`); rejected rows can appear as gaps (`rule.gaps`); the Benford small-sample caveat; decimal point only. Some of these are already there, so check each one.

### Manual checks

- test.readme_checklist: 5 of 5 items of `crit.readme`.
- test.no_real_data: review `tests/fixtures` and search for secret patterns (`rule.no_real_data`, `SECURITY.xml`).
- test.budget_zero: the owner reads the real invoices of the month.
- test.design_contrast: every colour pair in `DESIGN.xml` (`colour_tokens`) at 4.5 or more.
- test.ci_matrix: green on all 4 jobs. Needs a first commit and a push, which only happen with the owner's approval.
- test.publish_permission: only the maintainer can publish the tag.

### Before publishing

- Clean build: a fresh environment, install with `constraints.txt`, run `analyze` on `ledger_planted.csv`.
- Tag `v0.1.0` on GitHub, with the owner's approval. No PyPI publication in version 1.
