"""Write results.xlsx: eight sheets, with input text always stored as literal text."""

import contextlib
import os
from collections.abc import Iterable, Sequence
from pathlib import Path

import pandas as pd
import xlsxwriter
from xlsxwriter.exceptions import FileCreateError
from xlsxwriter.format import Format
from xlsxwriter.workbook import Workbook
from xlsxwriter.worksheet import Worksheet

from . import content
from .checks import ALERT_COLUMNS, BENFORD_EXPECTED, BenfordResult
from .validation import REJECTED_COLUMNS

TEST_SHEETS = (
    ("duplicates", content.SHEET_DUPLICATES),
    ("round", content.SHEET_ROUND),
    ("weekend", content.SHEET_WEEKEND),
    ("gaps", content.SHEET_GAPS),
)
ALERT_HEADERS = (
    content.COL_SOURCE_ROW,
    content.COL_ENTRY_ID,
    content.COL_DOCUMENT_NUMBER,
    content.COL_REASON,
    content.COL_DETAIL,
)
REJECTED_HEADERS = (content.COL_SOURCE_ROW, content.COL_REASON, content.COL_RAW_LINE)
BENFORD_HEADERS = (
    content.COL_DIGIT,
    content.COL_COUNT,
    content.COL_EXPECTED,
    content.COL_OBSERVED,
)
README_TEXTS = (
    content.README_INTRO,
    content.EXPLAIN_SUMMARY,
    content.EXPLAIN_DUPLICATES,
    content.EXPLAIN_ROUND,
    content.EXPLAIN_WEEKEND,
    content.EXPLAIN_GAPS,
    content.EXPLAIN_BENFORD,
    content.EXPLAIN_REJECTED,
)
# (font colour, background) of each token in spec/DESIGN.xml.
COLOURS = {
    "header": ("#FFFFFF", "#1F3A5F"),
    "alert": ("#7A1F17", "#FBE3E1"),
    "ok": ("#14532D", "#DCFCE7"),
    "body": ("#1B1B1B", "#FFFFFF"),
    "note": ("#333333", "#FFF1D6"),
}
FLAGGED = ("marginal", "non_conforming")
# Zero-based rows: tables and empty messages start at A3; on Benford the results follow the digits.
TABLE_ROW = 2
BENFORD_RESULTS_ROW = 13
# Excel has 1048576 rows and a table sheet uses the first three for the title and the header.
MAX_TABLE_ROWS = 1048576 - (TABLE_ROW + 1)
BENFORD_REASON_ROW = 18
BENFORD_CAVEAT_ROW = 19
# The Reason column of a test sheet, below its header. It has no text in the empty state.
REASON_RANGE = "$D$4:$D$1048576"
CLASSIFICATION_CELL = "$B$18"
# Excel keeps 15 significant digits, so a longer integer written as a number loses its last digits.
MAX_EXACT_INTEGER = 10**15
README_WIDTH = 60
MIN_WIDTH = 12
MAX_WIDTH = 60
# Room for the filter button of a header cell.
WIDTH_PADDING = 3


class WorkbookError(Exception):
    """The workbook cannot be written: exit code 1. The message is ready to show."""


def write_workbook(
    path: str | Path, alerts: pd.DataFrame, benford: BenfordResult, rejected: pd.DataFrame
) -> None:
    """Write the workbook and move it to path, keeping any previous file if that fails."""
    _check_sheet_sizes(alerts, rejected)
    path = Path(path)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        _write_sheets(temporary, alerts, benford, rejected)
        os.replace(temporary, path)
    except (OSError, FileCreateError) as exc:
        raise WorkbookError(content.ERR_OUT_DIR.format(path=path.parent)) from exc
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)


def _check_sheet_sizes(alerts: pd.DataFrame, rejected: pd.DataFrame) -> None:
    """XlsxWriter drops rows past the last one with no error, so refuse before writing."""
    sizes = [(name, (alerts["test_id"] == test_id).sum()) for test_id, name in TEST_SHEETS]
    for name, size in [*sizes, (content.SHEET_REJECTED, len(rejected))]:
        if size > MAX_TABLE_ROWS:
            raise WorkbookError(content.ERR_TOO_MANY_ROWS.format(sheet=name))


def _write_sheets(
    path: Path, alerts: pd.DataFrame, benford: BenfordResult, rejected: pd.DataFrame
) -> None:
    with xlsxwriter.Workbook(path) as workbook:
        formats = _formats(workbook)
        _write_readme(workbook, formats)
        _write_summary(workbook, formats, alerts, benford)
        alert_columns = list(ALERT_COLUMNS[1:])
        for test_id, name in TEST_SHEETS:
            selected = alerts.loc[alerts["test_id"] == test_id, alert_columns]
            rows = list(selected.itertuples(index=False, name=None))
            _write_table_sheet(
                workbook, formats, name, ALERT_HEADERS, rows, content.NO_ALERTS, "alert"
            )
        _write_benford(workbook, formats, benford)
        rows = list(rejected[list(REJECTED_COLUMNS)].itertuples(index=False, name=None))
        _write_table_sheet(
            workbook,
            formats,
            content.SHEET_REJECTED,
            REJECTED_HEADERS,
            rows,
            content.NO_REJECTED,
            "body",
        )


def _formats(workbook: Workbook) -> dict[str, Format]:
    def token(name: str, **extra) -> Format:
        font_colour, background = COLOURS[name]
        return workbook.add_format({"font_color": font_colour, "bg_color": background, **extra})

    # num_format "0" shows long integers in full; it does not change how text looks.
    return {
        "title": token("body", bold=True),
        "header": token("header", bold=True),
        "body": token("body", num_format="0"),
        "alert": token("alert", num_format="0"),
        "ok": token("ok", num_format="0"),
        "note": token("note", text_wrap=True),
        "wrapped": token("body", text_wrap=True),
        "two_places": token("body", num_format="0.00"),
        "three_places": token("body", num_format="0.000"),
        "four_places": token("body", num_format="0.0000"),
    }


def _add_sheet(workbook: Workbook, formats: dict[str, Format], name: str) -> Worksheet:
    sheet = workbook.add_worksheet(name)
    sheet.write_string(0, 0, name, formats["title"])
    return sheet


def _add_table(
    sheet: Worksheet, formats: dict[str, Format], headers: Sequence[str], n_rows: int
) -> None:
    # Headers only: with data, add_table uses write(), which turns text into formulas and links.
    columns = [{"header": header, "header_format": formats["header"]} for header in headers]
    sheet.add_table(
        TABLE_ROW, 0, TABLE_ROW + n_rows, len(headers) - 1, {"style": None, "columns": columns}
    )
    sheet.freeze_panes(TABLE_ROW + 1, 0)


def _write_cell(sheet: Worksheet, row: int, column: int, value, cell_format: Format) -> None:
    # write_string also cuts text at the cell limit of 32767 UTF-16 units, keeping characters whole.
    if value is None:
        sheet.write_blank(row, column, None, cell_format)
    elif isinstance(value, str):
        sheet.write_string(row, column, value, cell_format)
    elif abs(value) < MAX_EXACT_INTEGER:
        sheet.write_number(row, column, value, cell_format)
    else:
        sheet.write_string(row, column, str(value), cell_format)


def _fit_columns(sheet: Worksheet, rows: Iterable[Sequence]) -> None:
    widths: dict[int, int] = {}
    for row in rows:
        for column, value in enumerate(row):
            length = 0 if value is None else len(str(value))
            widths[column] = max(widths.get(column, 0), length)
    for column, width in widths.items():
        sheet.set_column(column, column, min(max(width + WIDTH_PADDING, MIN_WIDTH), MAX_WIDTH))


def _write_readme(workbook: Workbook, formats: dict[str, Format]) -> None:
    sheet = _add_sheet(workbook, formats, content.SHEET_README)
    sheet.set_column(0, 0, README_WIDTH)
    sheet.freeze_panes(1, 0)
    sheet.write_string(TABLE_ROW, 0, content.WARNING, formats["note"])
    for row, text in enumerate(README_TEXTS, start=TABLE_ROW + 1):
        sheet.write_string(row, 0, text, formats["wrapped"])


def _write_summary(
    workbook: Workbook, formats: dict[str, Format], alerts: pd.DataFrame, benford: BenfordResult
) -> None:
    sheet = _add_sheet(workbook, formats, content.SHEET_SUMMARY)
    rows = [
        (name, f"=COUNTA('{name}'!{REASON_RANGE})", int((alerts["test_id"] == test_id).sum()))
        for test_id, name in TEST_SHEETS
    ]
    classification = f"'{content.SHEET_BENFORD}'!{CLASSIFICATION_CELL}"
    tests = ",".join(f'{classification}="{value}"' for value in FLAGGED)
    rows.append(
        (content.SHEET_BENFORD, f"=IF(OR({tests}),1,0)", int(benford.classification in FLAGGED))
    )

    headers = (content.COL_TEST, content.COL_ALERTS)
    _add_table(sheet, formats, headers, len(rows))
    for row, (name, formula, value) in enumerate(rows, start=TABLE_ROW + 1):
        cell_format = formats["alert" if value else "ok"]
        sheet.write_string(row, 0, name, cell_format)
        # XlsxWriter stores 0 unless it is given the value of the formula.
        sheet.write_formula(row, 1, formula, cell_format, value)
    _fit_columns(sheet, [headers, *(row[:1] for row in rows)])


def _write_table_sheet(
    workbook: Workbook,
    formats: dict[str, Format],
    name: str,
    headers: Sequence[str],
    rows: list[tuple],
    empty_message: str,
    row_format: str,
) -> None:
    sheet = _add_sheet(workbook, formats, name)
    if not rows:
        sheet.write_string(TABLE_ROW, 0, empty_message, formats["body"])
        _fit_columns(sheet, [(empty_message,)])
        return
    _add_table(sheet, formats, headers, len(rows))
    for row, values in enumerate(rows, start=TABLE_ROW + 1):
        for column, value in enumerate(values):
            _write_cell(sheet, row, column, value, formats[row_format])
    _fit_columns(sheet, [headers, *rows])


def _write_benford(workbook: Workbook, formats: dict[str, Format], benford: BenfordResult) -> None:
    sheet = _add_sheet(workbook, formats, content.SHEET_BENFORD)
    if benford.classification is None:
        sheet.write_string(TABLE_ROW, 0, content.BENFORD_SKIP, formats["body"])
        _fit_columns(sheet, [(content.BENFORD_SKIP,)])
        return

    _add_table(sheet, formats, BENFORD_HEADERS, len(BENFORD_EXPECTED))
    for digit, (count, expected) in enumerate(
        zip(benford.digit_counts, BENFORD_EXPECTED, strict=True), start=1
    ):
        row = TABLE_ROW + digit
        sheet.write_number(row, 0, digit, formats["body"])
        sheet.write_number(row, 1, count, formats["body"])
        sheet.write_number(row, 2, float(expected), formats["three_places"])
        sheet.write_number(row, 3, count / benford.n_rows, formats["three_places"])

    results = (
        (content.BF_N_ROWS, benford.n_rows, "body"),
        (content.BF_MAD, benford.mad, "four_places"),
        (content.BF_CHI2, benford.chi2, "two_places"),
        (content.BF_P_VALUE, benford.p_value, "four_places"),
        (content.BF_CLASSIFICATION, benford.classification, "body"),
    )
    for row, (label, value, cell_format) in enumerate(results, start=BENFORD_RESULTS_ROW):
        sheet.write_string(row, 0, label, formats["body"])
        _write_cell(sheet, row, 1, value, formats[cell_format])
    if benford.classification in FLAGGED:
        sheet.write_string(BENFORD_REASON_ROW, 0, content.REASON_BENFORD, formats["alert"])
    sheet.write_string(BENFORD_CAVEAT_ROW, 0, content.BENFORD_CAVEAT, formats["body"])
    _fit_columns(
        sheet, [BENFORD_HEADERS, *(row[:1] for row in results), (None, benford.classification)]
    )
    sheet.insert_chart("F3", _benford_chart(workbook))


def _benford_chart(workbook: Workbook):
    chart = workbook.add_chart({"type": "column"})
    first_row, last_row = TABLE_ROW + 1, TABLE_ROW + len(BENFORD_EXPECTED)
    for column in (2, 3):
        chart.add_series(
            {
                "name": [content.SHEET_BENFORD, TABLE_ROW, column],
                "categories": [content.SHEET_BENFORD, first_row, 0, last_row, 0],
                "values": [content.SHEET_BENFORD, first_row, column, last_row, column],
            }
        )
    chart.set_title({"name": content.CHART_TITLE})
    chart.set_x_axis({"name": content.CHART_X})
    chart.set_y_axis({"name": content.CHART_Y})
    return chart
