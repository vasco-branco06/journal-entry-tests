"""Tests of unit U5 from spec/TESTS.xml: the Excel writer.

There is no CLI yet, so tests that say "run analyze" call the functions directly. openpyxl does
not recalculate, so the formulas are checked against the cells they count.
"""

import io
import os
import zipfile
from pathlib import Path

import openpyxl
import pandas as pd
import pytest
import xlsxwriter

from journal_entry_tests import content, excel_writer
from journal_entry_tests.checks import (
    ALERT_COLUMNS,
    BENFORD_EXPECTED,
    BenfordResult,
    aggregate,
    check_benford,
    check_duplicates,
    check_gaps,
    check_round,
    check_weekend,
    read_holidays,
)
from journal_entry_tests.excel_writer import WorkbookError, write_workbook
from journal_entry_tests.validation import REJECTED_COLUMNS, read_ledger

FIXTURES = Path(__file__).parent / "fixtures"
SHEETS = [
    content.SHEET_README,
    content.SHEET_SUMMARY,
    content.SHEET_DUPLICATES,
    content.SHEET_ROUND,
    content.SHEET_WEEKEND,
    content.SHEET_GAPS,
    content.SHEET_BENFORD,
    content.SHEET_REJECTED,
]
TEST_SHEETS = {
    "duplicates": content.SHEET_DUPLICATES,
    "round": content.SHEET_ROUND,
    "weekend": content.SHEET_WEEKEND,
    "gaps": content.SHEET_GAPS,
}
HEADER = "description,entry_id,document_number,posting_date,account_code,amount"
SKIPPED = BenfordResult(3)
COUNTS = [301, 176, 125, 97, 79, 67, 58, 51, 46]
FLAGGED = BenfordResult(1000, 0.02, 40.0, 0.001, "non_conforming", COUNTS)
ACCEPTED = BenfordResult(1000, 0.008, 5.0, 0.7, "acceptable", COUNTS)
NO_ALERTS = aggregate()
NO_REJECTED = pd.DataFrame(columns=REJECTED_COLUMNS)
BIG = 2**70


def alert(test_id, source_row=2, entry_id="E1", document_number=7, reason="r", detail="d"):
    return (test_id, source_row, entry_id, document_number, reason, detail)


def alerts_frame(*rows):
    return pd.DataFrame(list(rows), columns=ALERT_COLUMNS, dtype=object)


def rejected_frame(*raw_lines):
    rows = [(line, "bad row", raw) for line, raw in enumerate(raw_lines, start=2)]
    return pd.DataFrame(rows, columns=REJECTED_COLUMNS)


def write(tmp_path, alerts=NO_ALERTS, benford=SKIPPED, rejected=NO_REJECTED):
    path = tmp_path / "results.xlsx"
    write_workbook(path, alerts, benford, rejected)
    return path


def analyze(tmp_path, ledger, holidays=frozenset()):
    """Run everything the future analyze command runs, except for the argument handling."""
    valid, rejected = read_ledger(ledger)
    benford_alerts, benford = check_benford(valid)
    alerts = aggregate(
        check_duplicates(valid),
        check_round(valid),
        check_weekend(valid, holidays),
        check_gaps(valid),
        benford_alerts,
    )
    return write(tmp_path, alerts, benford, rejected), alerts, benford


def write_csv(tmp_path, *rows):
    path = tmp_path / "ledger.csv"
    path.write_text("\n".join((HEADER, *rows)) + "\n", encoding="utf-8")
    return path


def column_values(sheet, column):
    return [cell.value for cell in sheet[column][3:] if cell.value is not None]


def summary_values(path):
    sheet = openpyxl.load_workbook(path, data_only=True)[content.SHEET_SUMMARY]
    return {sheet.cell(row, 1).value: sheet.cell(row, 2).value for row in range(4, 9)}


# test.workbook_sheets


def test_exactly_eight_sheets_with_the_names_of_the_content_file(tmp_path):
    assert openpyxl.load_workbook(write(tmp_path)).sheetnames == SHEETS


# test.formula_neutralize


@pytest.mark.parametrize("text", ["=SUM(A1)", "+1+1", "-1+1", "@SUM(A1)"])
def test_description_in_a_raw_line_is_literal_text(tmp_path, text):
    # Too few fields: the row is rejected, and its raw line starts with the description.
    path, _, _ = analyze(tmp_path, write_csv(tmp_path, f"{text},E1,1"))
    cell = openpyxl.load_workbook(path)[content.SHEET_REJECTED]["C4"]
    assert cell.value == f"{text},E1,1"
    assert cell.data_type == "s"


def test_entry_id_and_account_code_in_alert_tables_are_literal_text(tmp_path):
    row = "plain,=1+1,1,2025-01-15,=2+2,10.50"
    path, _, _ = analyze(tmp_path, write_csv(tmp_path, row, row))
    sheet = openpyxl.load_workbook(path)[content.SHEET_DUPLICATES]
    assert (sheet["B4"].value, sheet["B4"].data_type) == ("=1+1", "s")
    assert sheet["E4"].value == "=2+2 10.50 2025-01-15"
    assert sheet["E4"].data_type == "s"


def test_only_summary_has_formulas(tmp_path):
    row = "=SUM(A1),=1+1,1,2025-01-18,=2+2,1000"
    path, _, _ = analyze(tmp_path, write_csv(tmp_path, row, row, "=SUM(A1),E2"))
    workbook = openpyxl.load_workbook(path)
    formula_sheets = {
        sheet.title
        for sheet in workbook
        for line in sheet.iter_rows()
        for cell in line
        if cell.data_type == "f"
    }
    assert formula_sheets == {content.SHEET_SUMMARY}


# test.excel_writing


def test_url_is_plain_text_with_no_hyperlink(tmp_path):
    url = "https://example.com/a,E1,1"
    path, _, _ = analyze(tmp_path, write_csv(tmp_path, url))
    sheet = openpyxl.load_workbook(path)[content.SHEET_REJECTED]
    assert (sheet["C4"].value, sheet["C4"].data_type) == (url, "s")
    assert sheet["C4"].hyperlink is None
    assert not sheet._hyperlinks


def test_raw_line_of_40000_characters_becomes_32767(tmp_path):
    path, _, _ = analyze(tmp_path, write_csv(tmp_path, "a" * 40000))
    sheet = openpyxl.load_workbook(path)[content.SHEET_REJECTED]
    assert sheet["C4"].value == "a" * 32767


@pytest.mark.parametrize(
    ("raw", "kept"),
    [
        ("a" * 32765 + "\U0001f600", "a" * 32765 + "\U0001f600"),
        ("a" * 32766 + "\U0001f600", "a" * 32766),
        ("\U0001f600" * 20000, "\U0001f600" * 16383),
    ],
)
def test_text_limit_counts_utf16_units_and_keeps_characters_whole(tmp_path, raw, kept):
    path = write(tmp_path, rejected=rejected_frame(raw))
    assert openpyxl.load_workbook(path)[content.SHEET_REJECTED]["C4"].value == kept


def test_summary_stores_the_computed_values(tmp_path):
    alerts = alerts_frame(
        alert("duplicates"),
        alert("duplicates", 3),
        alert("gaps", None, None, 9, "gap", None),
        alert("benford", None, None, None, content.REASON_BENFORD, "non_conforming"),
    )
    assert summary_values(write(tmp_path, alerts, FLAGGED)) == {
        content.SHEET_DUPLICATES: 2,
        content.SHEET_ROUND: 0,
        content.SHEET_WEEKEND: 0,
        content.SHEET_GAPS: 1,
        content.SHEET_BENFORD: 1,
    }


def test_summary_formulas_point_at_the_cells_they_count(tmp_path):
    alerts = alerts_frame(alert("round"), alert("gaps", None, None, 9, "gap", None))
    workbook = openpyxl.load_workbook(write(tmp_path, alerts, FLAGGED))
    summary = workbook[content.SHEET_SUMMARY]
    assert summary["B5"].value == f"=COUNTA('{content.SHEET_ROUND}'!$D$4:$D$1048576)"
    assert summary["B8"].value == (
        "=IF(OR('Benford'!$B$18=\"marginal\",'Benford'!$B$18=\"non_conforming\"),1,0)"
    )
    # The Reason header is in D3, and a gap has its reason even with an empty source row.
    gaps = workbook[content.SHEET_GAPS]
    assert gaps["D3"].value == content.COL_REASON
    assert column_values(gaps, "D") == ["gap"]
    assert workbook[content.SHEET_BENFORD]["A18"].value == content.BF_CLASSIFICATION
    assert workbook[content.SHEET_BENFORD]["B18"].value == "non_conforming"


def test_summary_is_zero_when_there_is_nothing_to_count(tmp_path):
    assert set(summary_values(write(tmp_path)).values()) == {0}


def test_acceptable_benford_counts_zero_in_the_summary(tmp_path):
    assert summary_values(write(tmp_path, benford=ACCEPTED))[content.SHEET_BENFORD] == 0


def test_failed_replace_keeps_the_previous_file_and_leaves_no_temporary(tmp_path, monkeypatch):
    path = tmp_path / "results.xlsx"
    path.write_bytes(b"previous")

    def locked(*_):
        raise PermissionError("locked by Excel")

    monkeypatch.setattr(os, "replace", locked)
    with pytest.raises(WorkbookError) as error:
        write_workbook(path, NO_ALERTS, SKIPPED, NO_REJECTED)
    assert str(error.value) == content.ERR_OUT_DIR.format(path=tmp_path)
    assert path.read_bytes() == b"previous"
    assert os.listdir(tmp_path) == ["results.xlsx"]


def test_missing_output_folder_raises_the_output_directory_error(tmp_path):
    folder = tmp_path / "missing"
    with pytest.raises(WorkbookError) as error:
        write_workbook(folder / "results.xlsx", NO_ALERTS, SKIPPED, NO_REJECTED)
    assert str(error.value) == content.ERR_OUT_DIR.format(path=folder)


def test_success_replaces_the_previous_file_and_leaves_no_temporary(tmp_path):
    path = tmp_path / "results.xlsx"
    path.write_bytes(b"previous")
    write_workbook(path, NO_ALERTS, SKIPPED, NO_REJECTED)
    assert openpyxl.load_workbook(path).sheetnames == SHEETS
    assert os.listdir(tmp_path) == ["results.xlsx"]


# test.states_sheets


def test_readme_shows_the_warning_box_the_intro_and_the_explanations(tmp_path):
    sheet = openpyxl.load_workbook(write(tmp_path))[content.SHEET_README]
    assert [sheet.cell(row, 1).value for row in range(1, 12)] == [
        content.SHEET_README,
        None,
        content.WARNING,
        content.README_INTRO,
        content.EXPLAIN_SUMMARY,
        content.EXPLAIN_DUPLICATES,
        content.EXPLAIN_ROUND,
        content.EXPLAIN_WEEKEND,
        content.EXPLAIN_GAPS,
        content.EXPLAIN_BENFORD,
        content.EXPLAIN_REJECTED,
    ]
    assert sheet["A3"].fill.fgColor.rgb == "FFFFF1D6"
    assert sheet["A3"].font.color.rgb == "FF333333"
    assert sheet["A4"].alignment.wrap_text
    assert sheet.column_dimensions["A"].width == pytest.approx(60, abs=1)


@pytest.mark.parametrize("test_id", TEST_SHEETS)
def test_test_sheet_success_lists_only_its_alerts(tmp_path, test_id):
    others = [alert(other, 99) for other in TEST_SHEETS if other != test_id]
    alerts = alerts_frame(alert(test_id, 5, "E5", 8, "why", "more"), *others)
    sheet = openpyxl.load_workbook(write(tmp_path, alerts))[TEST_SHEETS[test_id]]
    assert sheet["A1"].value == TEST_SHEETS[test_id]
    assert [cell.value for cell in sheet[3]] == [
        content.COL_SOURCE_ROW,
        content.COL_ENTRY_ID,
        content.COL_DOCUMENT_NUMBER,
        content.COL_REASON,
        content.COL_DETAIL,
    ]
    assert [cell.value for cell in sheet[4]] == [5, "E5", 8, "why", "more"]
    assert sheet.max_row == 4


@pytest.mark.parametrize("name", TEST_SHEETS.values())
def test_test_sheet_empty_shows_the_message_and_no_table(tmp_path, name):
    sheet = openpyxl.load_workbook(write(tmp_path))[name]
    assert sheet["A1"].value == name
    assert sheet["A3"].value == content.NO_ALERTS
    assert not sheet.tables


def test_rejected_sheet_success_and_empty(tmp_path):
    path = write(tmp_path, rejected=rejected_frame("raw text"))
    sheet = openpyxl.load_workbook(path)[content.SHEET_REJECTED]
    assert [cell.value for cell in sheet[3]] == [
        content.COL_SOURCE_ROW,
        content.COL_REASON,
        content.COL_RAW_LINE,
    ]
    assert [cell.value for cell in sheet[4]] == [2, "bad row", "raw text"]

    sheet = openpyxl.load_workbook(write(tmp_path))[content.SHEET_REJECTED]
    assert sheet["A3"].value == content.NO_REJECTED
    assert not sheet.tables


def test_benford_did_not_run_shows_the_text_and_no_chart(tmp_path):
    # Closes test.benford_min_rows: U3 proved the test does not run with 999 rows.
    rows = (
        f"plain,E{number},{number},2025-01-15,6100,{number + 100}.25" for number in range(1, 1000)
    )
    path, _, benford = analyze(tmp_path, write_csv(tmp_path, *rows))
    assert benford.n_rows == 999
    sheet = openpyxl.load_workbook(path)[content.SHEET_BENFORD]
    assert sheet["A3"].value == content.BENFORD_SKIP
    assert sheet["B18"].value is None
    assert not sheet.tables
    assert not any(name.startswith("xl/charts") for name in zipfile.ZipFile(path).namelist())


def test_benford_success_shows_the_table_the_results_and_the_caveat(tmp_path):
    sheet = openpyxl.load_workbook(write(tmp_path, benford=ACCEPTED))[content.SHEET_BENFORD]
    assert [cell.value for cell in sheet[3]][:4] == [
        content.COL_DIGIT,
        content.COL_COUNT,
        content.COL_EXPECTED,
        content.COL_OBSERVED,
    ]
    for digit, (count, expected) in enumerate(zip(COUNTS, BENFORD_EXPECTED, strict=True), start=1):
        row = 3 + digit
        assert sheet.cell(row, 1).value == digit
        assert sheet.cell(row, 2).value == count
        assert sheet.cell(row, 3).value == pytest.approx(expected)
        assert sheet.cell(row, 4).value == pytest.approx(count / 1000)
    assert [(sheet.cell(row, 1).value, sheet.cell(row, 2).value) for row in range(14, 19)] == [
        (content.BF_N_ROWS, 1000),
        (content.BF_MAD, 0.008),
        (content.BF_CHI2, 5.0),
        (content.BF_P_VALUE, 0.7),
        (content.BF_CLASSIFICATION, "acceptable"),
    ]
    assert sheet["A19"].value is None
    assert sheet["A20"].value == content.BENFORD_CAVEAT


def test_benford_flagged_shows_the_reason(tmp_path):
    sheet = openpyxl.load_workbook(write(tmp_path, benford=FLAGGED))[content.SHEET_BENFORD]
    assert sheet["A19"].value == content.REASON_BENFORD
    assert sheet["A20"].value == content.BENFORD_CAVEAT


def test_chart_is_present_with_its_titles_and_two_series(tmp_path):
    path = write(tmp_path, benford=ACCEPTED)
    assert len(openpyxl.load_workbook(path)[content.SHEET_BENFORD]._charts) == 1
    chart = zipfile.ZipFile(path).read("xl/charts/chart1.xml").decode("utf-8")
    assert chart.count("<c:ser>") == 2
    assert "<c:barChart>" in chart
    for text in (content.CHART_TITLE, content.CHART_X, content.CHART_Y):
        assert f"<a:t>{text}</a:t>" in chart


def test_every_sheet_of_the_planted_fixture_matches_the_alerts(tmp_path):
    holidays = read_holidays(FIXTURES / "holidays.csv")
    path, alerts, benford = analyze(tmp_path, FIXTURES / "ledger_planted.csv", holidays)
    workbook = openpyxl.load_workbook(path)
    summary = summary_values(path)
    for test_id, name in TEST_SHEETS.items():
        expected = alerts[alerts["test_id"] == test_id]
        assert not expected.empty
        assert summary[name] == len(expected)
        assert column_values(workbook[name], "D") == expected["reason"].tolist()
    assert summary[content.SHEET_BENFORD] == (alerts["test_id"] == "benford").sum() == 1
    assert workbook[content.SHEET_BENFORD]["B18"].value == benford.classification


# Extra checks the spec's test list does not name


def test_document_number_keeps_every_digit(tmp_path):
    alerts = alerts_frame(
        alert("gaps", None, None, BIG, "gap", None),
        alert("gaps", None, None, 10**15 - 1, "gap", None),
        alert("gaps", None, None, -(10**15), "gap", None),
    )
    sheet = openpyxl.load_workbook(write(tmp_path, alerts))[content.SHEET_GAPS]
    assert (sheet["C4"].value, sheet["C4"].data_type) == (str(BIG), "s")
    assert (sheet["C5"].value, sheet["C5"].data_type) == (10**15 - 1, "n")
    assert sheet["C5"].number_format == "0"
    assert (sheet["C6"].value, sheet["C6"].data_type) == (str(-(10**15)), "s")


def test_freeze_panes_sit_below_the_header_or_the_readme_title(tmp_path):
    alerts = alerts_frame(*(alert(test_id) for test_id in TEST_SHEETS))
    path = write(tmp_path, alerts, ACCEPTED, rejected_frame("raw"))
    workbook = openpyxl.load_workbook(path)
    assert workbook[content.SHEET_README].freeze_panes == "A2"
    for name in SHEETS[1:]:
        assert workbook[name].freeze_panes == "A4"


def test_design_tokens_table_filter_and_font(tmp_path):
    alerts = alerts_frame(alert("round"), alert("gaps", None, None, 9, "gap", None))
    workbook = openpyxl.load_workbook(write(tmp_path, alerts))
    sheet = workbook[content.SHEET_ROUND]
    assert sheet["A3"].fill.fgColor.rgb == "FF1F3A5F"
    assert sheet["A3"].font.color.rgb == "FFFFFFFF"
    assert sheet["A3"].font.bold
    assert sheet["D4"].fill.fgColor.rgb == "FFFBE3E1"
    assert sheet["D4"].font.color.rgb == "FF7A1F17"
    assert sheet["D4"].font.name == "Calibri"
    assert sheet["D4"].font.sz == 11
    assert next(iter(sheet.tables.values())).autoFilter is not None
    # A blank cell of an alert row keeps the colour of the row.
    assert workbook[content.SHEET_GAPS]["A4"].fill.fgColor.rgb == "FFFBE3E1"

    summary = workbook[content.SHEET_SUMMARY]
    assert summary["B5"].fill.fgColor.rgb == "FFFBE3E1"
    assert summary["B4"].fill.fgColor.rgb == "FFDCFCE7"
    assert summary["B4"].font.color.rgb == "FF14532D"


def test_column_widths_stay_between_12_and_60_and_no_cell_is_merged(tmp_path):
    alerts = alerts_frame(alert("round", 2, "E", 1, "r" * 500, "d"))
    path = write(tmp_path, alerts, ACCEPTED, rejected_frame("x" * 500))
    workbook = openpyxl.load_workbook(path)
    widths = {
        dimension.width
        for sheet in workbook
        for dimension in sheet.column_dimensions.values()
        if dimension.customWidth
    }
    # The file stores each width with its cell padding, less than 1 above the requested value.
    assert min(widths) >= 12
    assert max(widths) < 61
    assert not any(sheet.merged_cells.ranges for sheet in workbook)


# Too many rows for one sheet (rule.excel_writing)


def test_max_table_rows_is_the_last_table_excel_accepts():
    sheet = xlsxwriter.Workbook(io.BytesIO(), {"in_memory": True}).add_worksheet()
    columns = {"columns": [{"header": "a"}]}
    assert sheet.add_table(2, 0, 2 + excel_writer.MAX_TABLE_ROWS + 1, 0, columns) == -1
    assert sheet.add_table(2, 0, 2 + excel_writer.MAX_TABLE_ROWS, 0, columns) != -1


def test_one_row_above_the_limit_raises_before_writing(tmp_path):
    path = tmp_path / "results.xlsx"
    path.write_bytes(b"previous")
    count = excel_writer.MAX_TABLE_ROWS + 1
    rejected = pd.DataFrame(
        {"source_row": range(count), "reason": "r", "raw_line": "x"}, columns=REJECTED_COLUMNS
    )
    with pytest.raises(WorkbookError) as error:
        write_workbook(path, NO_ALERTS, SKIPPED, rejected)
    assert str(error.value) == content.ERR_TOO_MANY_ROWS.format(sheet=content.SHEET_REJECTED)
    assert path.read_bytes() == b"previous"
    assert os.listdir(tmp_path) == ["results.xlsx"]


@pytest.mark.parametrize("test_id", TEST_SHEETS)
def test_each_test_sheet_has_the_limit(tmp_path, monkeypatch, test_id):
    monkeypatch.setattr(excel_writer, "MAX_TABLE_ROWS", 2)
    with pytest.raises(WorkbookError) as error:
        write(tmp_path, alerts=alerts_frame(*[alert(test_id)] * 3))
    assert str(error.value) == content.ERR_TOO_MANY_ROWS.format(sheet=TEST_SHEETS[test_id])


def test_exactly_the_limit_is_written(tmp_path, monkeypatch):
    monkeypatch.setattr(excel_writer, "MAX_TABLE_ROWS", 2)
    path = write(tmp_path, alerts=alerts_frame(*[alert("gaps")] * 2))
    sheet = openpyxl.load_workbook(path)[content.SHEET_GAPS]
    assert column_values(sheet, "D") == ["r", "r"]
