# Code standards

Derived from `spec/`. This file is never a second source: if it disagrees with the spec, the spec wins.

- Python 3.11 or later.
- src layout (`src/journal_entry_tests/`).
- Dependencies: pandas, NumPy, SciPy, XlsxWriter.
- Dev dependencies: pytest, ruff, openpyxl (openpyxl only to read `results.xlsx` in tests).
- Versions are pinned in `constraints.txt`: `pip install -c constraints.txt -e ".[dev]"`.
- Command line with argparse. Override the default usage exit code 2 to 1.
- Amounts are integer cents. Never pass an amount through a float.
- Numbers and dates follow the exact formats of `rule.value_format`. Do not rely on `int()`, `Decimal()` or `date.fromisoformat()` alone: they accept forms the spec rejects.
- The five tests are pure functions in `checks.py`.
- Alerts use the common format: `test_id`, `source_row`, `entry_id`, `document_number`, `reason`, `detail`.
- Visible text comes from `content.py`, kept equal to `spec/CONTENT.xml` by a test.
- Input text goes to Excel with `write_string` only, as literal text (`rule.excel_writing`).
- No network calls.
- Ruff line length 100, rules E, F, I, B and UP.

## Folder layout

```
journal-entry-tests/
  CLAUDE.md
  README.md
  LICENSE
  pyproject.toml
  constraints.txt
  .gitignore
  context/
    code-standards.md
    progress-tracker.md
    next-steps.md
  spec/                 (12 XML files, changed only through the specification gate)
  src/journal_entry_tests/
    __init__.py
    cli.py
    content.py
    validation.py
    checks.py
    excel_writer.py
  tests/
    fixtures/
    __init__.py
  data/
  .github/workflows/
```
