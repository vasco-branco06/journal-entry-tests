# Progress tracker

One entry per unit: status, owner of the code, spec to read, test ids from `spec/TESTS.xml`.

Note: the specification network (version 0.2) is marked **unverified** because the official checker is unavailable.

- **U0 base files:** done and verified by the owner (no tests).
- **U2 validation** (CSV to valid and rejected rows, `content.py`): done, agent; awaiting owner review.
  - Spec: `SCHEMA.xml` (ledger_input, ledger_valid, rejected_row); `RULES.xml` (rule.amount_cents, rule.validation_rows, rule.value_format, rule.file_structure, rule.encoding); `CONTENT.xml`.
  - Tests: test.amount_cents, test.validation_rows, test.file_structure, test.content_sync
- **U3 five tests, aggregator and fixtures:** done, agent; awaiting owner review.
  - Still to prove later: test.benford_min_rows, the text shown on the Benford sheet (U5, test.states_sheets); test.holidays, exit code 1 (U6). U3 checks that Benford does not run and that the error names the line.
  - Decisions the spec leaves open: `detail` holds data only, because `CONTENT.xml` has no text for it; "sort by test_id" is alphabetical.
  - Spec: `SCHEMA.xml` (alert, benford_result, holidays_input, seed_data); `RULES.xml` (rule.duplicate, rule.round, rule.weekend_holiday, rule.holidays_format, rule.gaps, rule.benford_digit, rule.benford_mad, rule.benford_min_rows, rule.benford_alert, rule.aggregator, rule.generator_outside_repo).
  - Tests: test.fixture_recall, test.fixture_clean, test.benford_mad, test.benford_min_rows, test.round_base, test.holidays, test.aggregator
- **U5 Excel writer:** done, agent; the owner opened the sample `results.xlsx` from `ledger_planted.csv` in real Excel with no problems (2026-11-06); code review pending.
  - Closes the Benford sheet text of test.benford_min_rows (U3). Still to prove later: test.excel_writing, exit code 1 (U6). U5 raises `WorkbookError` with the output directory error.
  - Decisions the spec leaves open: document numbers above 15 digits are text; `description` reaches the workbook only inside a raw line; rejected and Benford tables use the body colours; the Benford reason at A19 uses the alert colours; a sheet in its empty state has no header row, so nothing is frozen.
  - The 32767-unit cut is done by XlsxWriter 3.3.1 inside `write_string`, without splitting a character, so the writer has no cut of its own. Tests cover it, so an upgrade that changes this fails.
  - Spec: `INTERFACE.xml` (screens); `DESIGN.xml`; `CONTENT.xml`; `RULES.xml` (rule.formula_neutralize, rule.excel_writing, rule.alert_notice).
  - Tests: test.workbook_sheets, test.formula_neutralize, test.excel_writing, test.states_sheets
- **U6 CLI (`analyze`):** done, agent; awaiting owner review.
  - Closes the exit code 1 parts of test.holidays and test.excel_writing, and repeats test.fixture_recall, test.fixture_clean and test.workbook_sheets end to end.
  - Decisions the spec leaves open, approved by the owner: `--help` lists the options without a description for each one, because `CONTENT.xml` has only `str.help_analyze`; a holidays file that cannot be opened (a folder, no permission) uses `ERR_MISSING_FILE`, code 1; the output folder is created before the holidays and the ledger are read, so a run that fails on them can leave an empty folder, which is not removed; a `results.xlsx` locked by Excel is found only at the final replace, so bad columns in the same run win over the lock.
  - Change from the approved plan, approved by the owner (2026-11-06): the writable-folder check creates and removes a file directly instead of using `tempfile.TemporaryFile`. On Python 3.11 on Windows, `tempfile` hung on a folder with write access denied (still running when stopped after 15 s); `analyze` gives code 1 on 3.11 and 3.14. Checked once by hand with `icacls`; the automated test forces the error instead, because real permissions differ between Windows and Ubuntu.
  - Spec: `INTERFACE.xml` (inv.analyze); `ARCHITECTURE.xml`; `RULES.xml` (rule.exit_codes, rule.overwrite).
  - Tests: test.exit_codes, test.overwrite, test.states_analyze, test.runtime, test.no_network
- **U7 CI and README:** built by the agent (2026-11-06); not committed, not pushed. Awaiting owner review and the three tests that need GitHub or the owner.
  - Done with evidence: `ci.yml` (checked with actionlint 1.7.12, not yet run on GitHub); README with no TODO left; test.design_contrast (5 of 5 pairs at 4.5 or more, ratios match `DESIGN.xml`); test.readme_checklist (5 of 5); test.no_real_data (fixtures profiled column by column, secret patterns searched in tracked files and in history, second independent scan: PASS-WITH-WARNINGS, only author identity); clean build in a fresh environment outside the repository on Python 3.14 and 3.11: 63 alerts, 0 rejected rows, code 0; 254 tests and ruff pass on 3.14 and 3.11, also on a CRLF copy of fixtures and tests.
  - Decisions: `fail-fast: false` and `permissions: contents: read` in the workflow; actions at `@v7`; `setuptools==84.2.1` pinned in `pyproject.toml` (pip builds in an isolated environment and ignores `constraints.txt`); `python-docx` not pinned, it belongs to U8.
  - test.ci_matrix: passed. The first runs (push and pull request) failed on both Windows jobs: 2 CLI tests looked for the installed script only next to `python.exe`, and the runner has no venv (issue I01, closed). `script()` in `tests/test_cli.py` now also searches `sysconfig.get_path("scripts")`. Runs 42223571648 (push) and 42223580586 (pull request) on commit 4504ce0: 4 of 4 jobs green in each.
  - Repository: `github.com/vasco-branco06/journal-entry-tests`, public; PR #1 open, not merged. `gh api .../collaborators` lists only `vasco-branco06` (evidence for test.publish_permission, still to be confirmed by the owner in Settings).
  - test.budget_zero: passed, reported by the owner on 2026-11-06 ("spent nothing"); no invoice file was shown to the agent. test.publish_permission: passed, the owner confirmed they are the only collaborator, matching `gh api`.
  - Still open: the tag `v0.1.0` and the merge of PR #1 (both approved by the owner on 2026-11-06). Not tested: a `results.xlsx` really held open by Excel (the tests force `os.replace` to fail). The specification network is still marked unverified.
  - Spec: `DEPLOYMENT.xml`; `SECURITY.xml`; `GOAL.xml` (crit.readme, constraints); `DESIGN.xml` (colour_tokens); `RULES.xml` (rule.no_real_data).
  - Tests: test.ci_matrix, test.readme_checklist, test.no_real_data, test.budget_zero, test.design_contrast, test.publish_permission
- **U8 Word report:** optional, outside v1. Test: test.word_scope

## Owner code review, 2026-11-06

Six issues found in U2, U3, U5 and U6, all reproduced. Five are fixed, each with tests beyond the ids of `spec/TESTS.xml`.

- E01 and E02 (U2): broken quoting swallowed rows or altered values. The CSV reader is now strict, so the whole file gives `ERR_UNREADABLE`, code 2 (d23). The message does not name the line, because that would need a new string.
- E03 (U2): a line with only spaces is now skipped in the ledger, as in the holidays file.
- E05 (U6): `main()` no longer fails when stdout is `None` or has no `reconfigure`.
- E06 (U5): more than 1048573 rows in one sheet now stops with `ERR_TOO_MANY_ROWS`, code 1, and writes nothing (d24).
- E04 (U3), not fixed by owner-approved decision: `check_benford` with a minimum of 0 and no rows gives NaN and `non_conforming`. Its only caller is the CLI, which refuses 0.
- Recorded from the audit, with no change: `--round-base` and `--benford-min-rows` refuse `+5`, because they accept ASCII digits only; `csv.field_size_limit` changes a value global to the process, which is harmless in a single-run command.
- Known limit of E01: an unclosed quote followed later by a quote next to a comma (`x,",y"`) still closes the field. Above 255 characters the swallowed text shows as a rejected row; below that, or in an extra column, it passes. It cannot be told apart from a multi-line field, which the spec allows.

The four synthetic files for U3 are in `tests/fixtures`, written by the separate private generator (`rule.generator_outside_repo`).
All 26 tests of v1 have passed. Only the optional U8 (test.word_scope) is left, so `context/next-steps.md` was deleted.
Order: U2, U3, U5, U6, U7, then optional U8. There is no U4: the aggregator moved into U3.
U3 tests that say "run analyze" call the functions directly; U6 repeats them end to end through the CLI.
Each unit comes with a plain-language explanation for the owner (what, why, how) before or after the code.
