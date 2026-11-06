# journal-entry-tests

A command-line tool that reads an accounting ledger CSV, applies five journal entry tests and writes the alerts to an Excel workbook.

> **An alert is a suspicion to be reviewed by a person. It is not proof of fraud.**

<!-- TODO (U7): badges, short demo description. -->

## What it does

Five tests for fraud-risk triage of journal entries:

1. Duplicates
2. Round values
3. Weekend and holiday
4. Numbering gaps
5. Benford first digit (mean absolute deviation, MAD)

The ISA 240 reference is by topic only. The official text was not verified and no paragraph numbers are cited.

<!-- TODO (U7): one short paragraph per test, copied from the final rules. -->

## Install

<!-- TODO (U7): Python 3.11 or later, virtual environment, `pip install -c constraints.txt .` -->

## Usage

```
journal-entry-tests analyze LEDGER [--out-dir out] [--round-base 1000] [--holidays FILE] [--benford-min-rows 1000] [--overwrite]
```

<!-- TODO (U6/U7): explain each option and show an example run on synthetic data. -->

## Input CSV format

- Required columns: `entry_id`, `document_number`, `posting_date` (YYYY-MM-DD), `account_code`, `amount`.
- Optional columns: `description`, `user_id`, `entry_type`.
- UTF-8, comma separated, dot decimal. A decimal comma is not accepted.
- Extra columns are ignored and column order is free.
- Values are read exactly as written. Forms such as `1_000`, `1E+3`, `.5` or `20240131`, and numbers or dates with surrounding spaces, send the row to Rejected rows.

<!-- TODO (U7): column-by-column table with examples. -->

## Output sheets

`results.xlsx` has 8 sheets:

1. README
2. Summary
3. Duplicates
4. Round values
5. Weekend and holiday
6. Numbering gaps
7. Benford
8. Rejected rows

<!-- TODO (U5/U7): describe the columns of each sheet. -->

## Exit codes

- `0`: success (also when there are alerts).
- `1`: incorrect usage, missing file, unwritable or locked output (for example, `results.xlsx` open in Excel), existing output file or invalid holidays file.
- `2`: missing required columns or unreadable file.

## Privacy

Nothing leaves your computer. The tool makes no network calls.

## Limits and known caveats

- Rejected rows may show up as numbering gaps.
- Benford on small ledgers: a ledger that follows Benford's law can still be flagged. In our own simulation of 2000 runs per size, 2.25% were flagged at 1000 rows, 1.0% at 1200 and none at 5000. This is a simulation, not a published result.

<!-- TODO (U7): complete the list of limits. -->

## Licence

MIT. See `LICENSE`.
