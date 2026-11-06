# journal-entry-tests

![CI](https://github.com/vasco-branco06/journal-entry-tests/actions/workflows/ci.yml/badge.svg)
![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)
![Python 3.11 and 3.14](https://img.shields.io/badge/python-3.11%20%7C%203.14-blue.svg)

A command-line tool that reads an accounting ledger CSV, applies five journal entry tests and writes the alerts to an Excel workbook.

> **An alert is a suspicion to be reviewed by a person. It is not proof of fraud.**

You give it one CSV file. It gives you `results.xlsx` with one sheet per test, a summary, and a sheet with the rows it could not read. Everything runs on your computer. Each alert carries the line of your CSV it came from, so a reviewer can go straight to the entry.

## What it does

Five tests for fraud-risk triage of journal entries:

1. **Duplicates.** Two or more rows with the same `account_code`, the same signed `amount` and the same `posting_date`. Every row of the group gets an alert.
2. **Round values.** The absolute amount is at least the round base and a multiple of it. The base is 1000 unless you change it with `--round-base`. Amounts below the base and zero amounts are skipped.
3. **Weekend and holiday.** The `posting_date` is a Saturday or a Sunday, or it is listed in the holidays file you pass with `--holidays`. Without that file only weekends count. When a date is both, the reason says holiday.
4. **Numbering gaps.** Looks at the distinct `document_number` values and reports each range of integers missing between the smallest and the largest. One alert per range; the first missing number goes in the Document number column. Repeated numbers are ignored.
5. **Benford first digit.** Compares the first significant digit of the absolute amounts with Benford's law, using the mean absolute deviation (MAD) over the nine digits. Below 0.006 is close, from 0.006 up to 0.012 acceptable, from 0.012 up to 0.015 marginal, and 0.015 or more non-conforming. Only marginal and non-conforming raise an alert, a single one for the whole ledger. The chi-square and p-value are shown for information only. The test needs at least 1000 rows with a non-zero amount (`--benford-min-rows`); with fewer, it does not run and the Benford sheet says so. The thresholds are Nigrini's (2012), confirmed in two secondary sources, not in the original text.

The ISA 240 reference is by topic only. The official text was not verified and no paragraph numbers are cited.

## Install

You need Python 3.11 or later. Use a virtual environment and the pinned versions in `constraints.txt`:

```
git clone https://github.com/vasco-branco06/journal-entry-tests.git
cd journal-entry-tests
python -m venv .venv
```

Activate it (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate` on Linux and macOS), then:

```
pip install -c constraints.txt .
```

This installs the `journal-entry-tests` command. The dependencies are pandas, NumPy, SciPy and XlsxWriter.

## Usage

```
journal-entry-tests analyze LEDGER [--out-dir out] [--round-base 1000] [--holidays FILE] [--benford-min-rows 1000] [--overwrite]
```

| Argument | Default | What it does |
|---|---|---|
| `LEDGER` | required | Path of the input CSV. |
| `--out-dir DIR` | `out` | Folder where `results.xlsx` is written. Created if it does not exist. |
| `--round-base N` | `1000` | Base of the round values test. A positive whole number. |
| `--holidays FILE` | none | CSV with one date per line (`YYYY-MM-DD`), no header. UTF-8, with or without BOM. Blank lines are ignored and repeated dates are allowed. A line that is not a date stops the run with code 1 and names the line. |
| `--benford-min-rows N` | `1000` | Minimum number of rows with a non-zero amount for the Benford test. A positive whole number. |
| `--overwrite` | off | Replace `results.xlsx` if it already exists. Without it, an existing file stops the run with code 1. |

Example on the synthetic files of this repository:

```
journal-entry-tests analyze tests/fixtures/ledger_planted.csv --holidays tests/fixtures/holidays.csv --out-dir out
```

```
Done: 63 alerts, 0 rejected rows. Results saved to out\results.xlsx
```

That file has 1200 rows with problems planted on purpose: 19 duplicates, 20 round values, 20 weekend or holiday rows, 3 numbering gaps and 1 Benford alert. `tests/fixtures/ledger_clean.csv` is the same size with no planted problems.

## Input CSV format

One row per entry line. UTF-8 (with or without BOM), comma separated, dot decimal. The header is line 1. Column order is free and extra columns are ignored.

| Column | Required | Format | Example |
|---|---|---|---|
| `entry_id` | yes | Text, up to 255 characters. May repeat across rows of the same entry. | `JE000072` |
| `document_number` | yes | Whole number, optional `+` or `-` sign. Used by the numbering gaps test. | `72` |
| `posting_date` | yes | `YYYY-MM-DD`, and a real calendar date. | `2025-01-24` |
| `account_code` | yes | Text, up to 255 characters. | `6100` |
| `amount` | yes | Optional `+` or `-`, digits, then optionally a dot and up to 2 decimals. Debit positive, credit negative. | `287.32` or `-71.38` |
| `description` | no | Text, up to 255 characters. | `Synthetic posting 72` |
| `user_id` | no | Text, up to 255 characters. | `U01` |
| `entry_type` | no | Exactly `manual` or `automatic`. | `manual` |

How values are read:

- Values are read exactly as written and never trimmed. Forms such as `1_000`, `1E+3`, `NaN`, `Infinity`, `.5`, `5.`, `20240131` or a decimal comma (`1250,40`), and numbers or dates with surrounding spaces, send the row to Rejected rows. So does an amount with more than 2 decimals, an empty required value, an unknown `entry_type`, text over 255 characters, or a row with a different number of fields from the header.
- A rejected row never stops the analysis. It is listed with its reason and left out of the five tests.
- Blank lines, including lines with only spaces, are skipped.
- A quoted field may span several lines. The Source row of a row is the line where it starts.
- Broken quoting (an unclosed quote, or text after a closing quote) makes the whole file unreadable: exit code 2, and the message names the file, not a line.
- A file with no header, a 0-byte file, a missing required column or a required column named twice also gives code 2.

## Output sheets

`results.xlsx` has 8 sheets. Rows with an alert are shaded light red, and the reason is also written in text. Text from your CSV is always written as literal text, so a description that starts with `=`, `+`, `-` or `@` never runs as a formula.

| # | Sheet | Columns and content |
|---|---|---|
| 1 | README | The warning, a short intro and one line about each sheet. |
| 2 | Summary | `Test`, `Alerts`: the number of alerts per test, zeros included. |
| 3 | Duplicates | `Source row`, `Entry ID`, `Document number`, `Reason`, `Detail`. Detail holds account, amount and date. |
| 4 | Round values | Same columns. Detail holds the amount. |
| 5 | Weekend and holiday | Same columns. Detail holds the date. |
| 6 | Numbering gaps | Same columns. `Source row` and `Entry ID` stay empty, `Document number` holds the first missing number and `Reason` gives the whole range. |
| 7 | Benford | Table `First digit`, `Count`, `Expected`, `Observed` for digits 1 to 9, then `Rows used`, `MAD`, `Chi-square (information only)`, `p-value (information only)`, `Classification`, the reason or the reason the test did not run, a note about small samples, and a column chart of expected against observed. |
| 8 | Rejected rows | `Source row`, `Reason`, `Raw line` (the original row). |

A sheet with nothing to show says so (for example, "No alerts for this test."). The Summary counts are Excel formulas.

## Exit codes

- `0`: success (also when there are alerts, and when the ledger has no valid rows).
- `1`: incorrect usage, missing file, unwritable or locked output (for example, `results.xlsx` open in Excel), existing output file, invalid holidays file, or more rows than one Excel sheet can hold.
- `2`: missing required columns or unreadable file.

Errors go to stderr as one short line.

## Privacy

Nothing leaves your computer. The tool makes no network calls. The repository holds only synthetic data.

## Limits and known caveats

- Rejected rows may show up as numbering gaps, because the gaps test never sees them.
- Benford on small ledgers: a ledger that follows Benford's law can still be flagged. In our own simulation of 2000 runs per size, 2.25% were flagged at 1000 rows, 1.0% at 1200 and none at 5000. This is a simulation, not a published result.
- Amounts have a decimal point and at most 2 decimals. A decimal comma is not accepted. One currency only; nothing is converted.
- Tested size: 100000 rows, which the test suite requires to finish within 60 seconds. There is no enforced limit, but the whole ledger is held in memory.
- One Excel sheet holds at most 1048573 table rows, because the table starts at row 3. Above that the run stops with code 1, names the sheet and writes nothing.
- An Excel cell holds 32767 characters; longer text is cut.
- An existing `results.xlsx` is never replaced without `--overwrite`. If Excel holds it open, the run ends with code 1 and the previous file stays. The output folder is created before the files are read, so a run that fails can leave an empty folder.
- An unclosed quote that is followed later by a quote next to a comma (`x,",y"`) still closes the field, because it cannot be told apart from a quoted field that spans lines. If the swallowed text is over 255 characters it shows up as a rejected row; otherwise it passes.
- Only CSV input and only the `analyze` command.

## Licence

MIT. See `LICENSE`.
