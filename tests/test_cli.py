"""Tests of the analyze command, from spec/TESTS.xml and the plan of unit U6.

Each test calls main() in-process, except the ones that need the installed script.
"""

import contextlib
import csv
import io
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import openpyxl
import pytest

from journal_entry_tests import content, excel_writer
from journal_entry_tests.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
PLANTED = str(FIXTURES / "ledger_planted.csv")
CLEAN = str(FIXTURES / "ledger_clean.csv")
HOLIDAYS = str(FIXTURES / "holidays.csv")
HEADER = "entry_id,document_number,posting_date,account_code,amount"
GOOD_ROW = "E1,1,2025-01-15,6100,10.50"
BAD_ROW = "E2,2,not-a-date,6100,10.50"
SATURDAY_ROW = "E3,3,2025-01-18,6100,10.50"
ROUND_ROW = "E4,4,2025-01-15,6100,1500.00"
TEST_SHEETS = {
    "duplicates": content.SHEET_DUPLICATES,
    "round": content.SHEET_ROUND,
    "weekend": content.SHEET_WEEKEND,
    "gaps": content.SHEET_GAPS,
}
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
RUNTIME_LIMIT_SECONDS = 60
RUNTIME_ROWS = 100_000


def write_csv(tmp_path, *lines, name="ledger.csv"):
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def good_ledger(tmp_path):
    return write_csv(tmp_path, HEADER, GOOD_ROW)


def run(capsys, *argv):
    """Return (exit code, stdout, stderr), with the trailing newline removed."""
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out.rstrip("\n"), captured.err.rstrip("\n")


def analyze(capsys, ledger, out_dir, *options):
    return run(capsys, "analyze", ledger, "--out-dir", str(out_dir), *options)


def script():
    """The installed entry point, next to the interpreter running the tests."""
    path = shutil.which("journal-entry-tests", path=str(Path(sys.executable).parent))
    assert path, "journal-entry-tests is not installed in this environment"
    return path


def sheet_rows(sheet):
    """The data rows below the header at row 3, or nothing when the sheet has its empty state."""
    return list(sheet.iter_rows(min_row=4, values_only=True))


def done(alerts, rejected, path):
    return content.MSG_DONE.format(alerts=alerts, rejected=rejected, path=path)


def block_touch(monkeypatch):
    def refuse(self, *args, **kwargs):
        raise PermissionError(str(self))

    monkeypatch.setattr(Path, "touch", refuse)


# test.exit_codes


def test_exit_codes_valid_missing_and_no_columns(tmp_path, capsys):
    no_columns = write_csv(tmp_path, "a,b", "1,2", name="no_columns.csv")
    assert analyze(capsys, good_ledger(tmp_path), tmp_path / "ok")[0] == 0
    assert analyze(capsys, str(tmp_path / "absent.csv"), tmp_path / "missing")[0] == 1
    assert analyze(capsys, no_columns, tmp_path / "columns")[0] == 2


def test_exit_codes_through_the_installed_script(tmp_path):
    no_columns = write_csv(tmp_path, "a,b", "1,2", name="no_columns.csv")
    cases = (
        (good_ledger(tmp_path), "ok", 0),
        (str(tmp_path / "absent.csv"), "missing", 1),
        (no_columns, "columns", 2),
    )
    for ledger, folder, expected in cases:
        command = [script(), "analyze", ledger, "--out-dir", str(tmp_path / folder)]
        assert subprocess.run(command, capture_output=True).returncode == expected


# test.overwrite


def test_existing_file_is_kept_without_overwrite(tmp_path, capsys):
    results = tmp_path / "results.xlsx"
    results.write_bytes(b"previous")
    code, out, err = analyze(capsys, good_ledger(tmp_path), tmp_path)
    assert code == 1
    assert out == ""
    assert err == content.ERR_EXISTS.format(path=results)
    assert results.read_bytes() == b"previous"


def test_existing_file_is_replaced_with_overwrite(tmp_path, capsys):
    results = tmp_path / "results.xlsx"
    results.write_bytes(b"previous")
    assert analyze(capsys, good_ledger(tmp_path), tmp_path, "--overwrite")[0] == 0
    assert openpyxl.load_workbook(results).sheetnames == SHEETS


# test.states_analyze


def test_state_empty_header_only(tmp_path, capsys):
    ledger = write_csv(tmp_path, HEADER)
    results = tmp_path / "out" / "results.xlsx"
    assert analyze(capsys, ledger, tmp_path / "out") == (
        0,
        content.MSG_EMPTY.format(path=results),
        "",
    )
    workbook = openpyxl.load_workbook(results)
    assert workbook[content.SHEET_DUPLICATES]["A3"].value == content.NO_ALERTS
    assert workbook[content.SHEET_REJECTED]["A3"].value == content.NO_REJECTED
    assert workbook[content.SHEET_BENFORD]["A3"].value == content.BENFORD_SKIP


def test_state_empty_every_row_rejected(tmp_path, capsys):
    ledger = write_csv(tmp_path, HEADER, BAD_ROW)
    results = tmp_path / "out" / "results.xlsx"
    assert analyze(capsys, ledger, tmp_path / "out") == (
        0,
        content.MSG_EMPTY.format(path=results),
        "",
    )
    rows = sheet_rows(openpyxl.load_workbook(results)[content.SHEET_REJECTED])
    assert rows == [(2, content.REJ_BAD_DATE, BAD_ROW)]


def test_state_success(tmp_path, capsys):
    ledger = write_csv(tmp_path, HEADER, SATURDAY_ROW)
    results = tmp_path / "out" / "results.xlsx"
    assert analyze(capsys, ledger, tmp_path / "out") == (0, done(1, 0, results), "")


def test_state_success_with_no_alerts(tmp_path, capsys):
    results = tmp_path / "out" / "results.xlsx"
    assert analyze(capsys, good_ledger(tmp_path), tmp_path / "out") == (
        0,
        done(0, 0, results),
        "",
    )


@pytest.mark.parametrize("text", ["a,b\n1,2\n", ""])
def test_state_error_missing_columns(tmp_path, capsys, text):
    ledger = tmp_path / "ledger.csv"
    ledger.write_text(text, encoding="utf-8")
    message = content.ERR_MISSING_COLUMNS.format(columns=", ".join(HEADER.split(",")))
    assert analyze(capsys, str(ledger), tmp_path / "out") == (2, "", message)


def test_state_error_unreadable(tmp_path, capsys):
    ledger = tmp_path / "ledger.csv"
    ledger.write_bytes(b"\xff\xfe\x00binary")
    assert analyze(capsys, str(ledger), tmp_path / "out") == (
        2,
        "",
        content.ERR_UNREADABLE.format(path=ledger),
    )


def test_state_error_missing_file(tmp_path, capsys):
    absent = tmp_path / "absent.csv"
    assert analyze(capsys, str(absent), tmp_path / "out") == (
        1,
        "",
        content.ERR_MISSING_FILE.format(path=absent),
    )


def test_state_partial(tmp_path, capsys):
    ledger = write_csv(tmp_path, HEADER, SATURDAY_ROW, BAD_ROW)
    results = tmp_path / "out" / "results.xlsx"
    assert analyze(capsys, ledger, tmp_path / "out") == (0, done(1, 1, results), "")
    rows = sheet_rows(openpyxl.load_workbook(results)[content.SHEET_REJECTED])
    assert rows == [(3, content.REJ_BAD_DATE, BAD_ROW)]


def test_state_no_permission_out_dir_is_a_file(tmp_path, capsys):
    not_a_folder = tmp_path / "file.txt"
    not_a_folder.write_text("x", encoding="utf-8")
    assert analyze(capsys, good_ledger(tmp_path), not_a_folder) == (
        1,
        "",
        content.ERR_OUT_DIR.format(path=not_a_folder),
    )


# test.runtime


def test_runtime_100000_rows(tmp_path, capsys):
    rng = np.random.default_rng(6)
    dates = np.datetime64("2025-01-01") + rng.integers(0, 365, RUNTIME_ROWS)
    accounts = rng.integers(1000, 9999, RUNTIME_ROWS)
    cents = rng.integers(1, 10_000_000, RUNTIME_ROWS)
    lines = [HEADER]
    for number, (date, account, amount) in enumerate(zip(dates, accounts, cents, strict=True)):
        lines.append(f"E{number},{number},{date},{account},{amount // 100}.{amount % 100:02d}")
    ledger = write_csv(tmp_path, *lines)

    start = time.perf_counter()
    code, _, err = analyze(capsys, ledger, tmp_path / "out")
    elapsed = time.perf_counter() - start

    assert (code, err) == (0, "")
    assert elapsed <= RUNTIME_LIMIT_SECONDS


# test.no_network


def test_no_network(tmp_path, capsys, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network used")

    for name in ("socket", "getaddrinfo", "gethostbyname", "create_connection"):
        monkeypatch.setattr(socket, name, refuse)
    code, _, err = analyze(capsys, PLANTED, tmp_path / "out", "--holidays", HOLIDAYS)
    assert (code, err) == (0, "")


# test.holidays


def test_invalid_holidays_line_gives_code_1_and_names_the_line(tmp_path, capsys):
    holidays = write_csv(tmp_path, "2025-01-01", "not a date", name="holidays.csv")
    assert analyze(capsys, good_ledger(tmp_path), tmp_path / "out", "--holidays", holidays) == (
        1,
        "",
        content.ERR_HOLIDAYS.format(line=2),
    )


# test.excel_writing


def test_failed_replace_gives_code_1_and_keeps_the_previous_file(tmp_path, capsys, monkeypatch):
    results = tmp_path / "results.xlsx"
    results.write_bytes(b"previous")

    def refuse(*args, **kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr(os, "replace", refuse)
    ledger_dir = tmp_path / "input"
    ledger_dir.mkdir()
    code, out, err = analyze(capsys, good_ledger(ledger_dir), tmp_path, "--overwrite")
    assert (code, out) == (1, "")
    assert err == content.ERR_OUT_DIR.format(path=tmp_path)
    assert results.read_bytes() == b"previous"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input", "results.xlsx"]


# End to end: test.fixture_recall, test.fixture_clean, test.workbook_sheets


def test_fixture_recall_read_from_the_workbook(tmp_path, capsys):
    code, _, _ = analyze(capsys, PLANTED, tmp_path, "--holidays", HOLIDAYS)
    assert code == 0
    workbook = openpyxl.load_workbook(tmp_path / "results.xlsx", data_only=True)

    with open(FIXTURES / "ground_truth.csv", encoding="utf-8", newline="") as file:
        truth = list(csv.DictReader(file))
    assert truth
    for problem in truth:
        test_id = problem["test_id"]
        if test_id == "benford":
            summary = {row[0]: row[1] for row in sheet_rows(workbook[content.SHEET_SUMMARY])}
            assert summary[content.SHEET_BENFORD] == 1
            classification = workbook[content.SHEET_BENFORD]["B18"].value
            assert classification in ("marginal", "non_conforming")
            continue
        rows = sheet_rows(workbook[TEST_SHEETS[test_id]])
        if test_id == "gaps":
            assert int(problem["document_number"]) in [row[2] for row in rows]
        else:
            assert int(problem["source_row"]) in [row[0] for row in rows]


def test_fixture_clean_read_from_the_workbook(tmp_path, capsys):
    assert analyze(capsys, CLEAN, tmp_path)[0] == 0
    workbook = openpyxl.load_workbook(tmp_path / "results.xlsx", data_only=True)
    for name in TEST_SHEETS.values():
        assert workbook[name]["A3"].value == content.NO_ALERTS
        assert sheet_rows(workbook[name]) == []


def test_workbook_sheets_of_the_written_file(tmp_path, capsys):
    assert analyze(capsys, PLANTED, tmp_path)[0] == 0
    assert openpyxl.load_workbook(tmp_path / "results.xlsx").sheetnames == SHEETS


# End to end: the options reach the checks


def test_round_base_reaches_the_check(tmp_path, capsys):
    ledger = write_csv(tmp_path, HEADER, ROUND_ROW)
    assert analyze(capsys, ledger, tmp_path / "default")[0] == 0
    assert analyze(capsys, ledger, tmp_path / "base", "--round-base", "500")[0] == 0
    default = openpyxl.load_workbook(tmp_path / "default" / "results.xlsx")
    base = openpyxl.load_workbook(tmp_path / "base" / "results.xlsx")
    assert default[content.SHEET_ROUND]["A3"].value == content.NO_ALERTS
    assert sheet_rows(base[content.SHEET_ROUND])[0][3] == content.REASON_ROUND.format(base=500)


def test_benford_min_rows_reaches_the_check(tmp_path, capsys):
    ledger = write_csv(tmp_path, HEADER, GOOD_ROW)
    assert analyze(capsys, ledger, tmp_path / "default")[0] == 0
    assert analyze(capsys, ledger, tmp_path / "low", "--benford-min-rows", "1")[0] == 0
    default = openpyxl.load_workbook(tmp_path / "default" / "results.xlsx")
    low = openpyxl.load_workbook(tmp_path / "low" / "results.xlsx")
    assert default[content.SHEET_BENFORD]["A3"].value == content.BENFORD_SKIP
    assert low[content.SHEET_BENFORD]["A14"].value == content.BF_N_ROWS
    assert low[content.SHEET_BENFORD]["B14"].value == 1


def test_holidays_reach_the_check(tmp_path, capsys):
    ledger = good_ledger(tmp_path)
    holidays = write_csv(tmp_path, "2025-01-15", name="holidays.csv")
    assert analyze(capsys, ledger, tmp_path / "none")[0] == 0
    assert analyze(capsys, ledger, tmp_path / "with", "--holidays", holidays)[0] == 0
    without = openpyxl.load_workbook(tmp_path / "none" / "results.xlsx")
    with_file = openpyxl.load_workbook(tmp_path / "with" / "results.xlsx")
    assert without[content.SHEET_WEEKEND]["A3"].value == content.NO_ALERTS
    assert sheet_rows(with_file[content.SHEET_WEEKEND])[0][3] == content.REASON_HOLIDAY


def test_out_dir_creates_nested_folders(tmp_path, capsys):
    out_dir = tmp_path / "a" / "b" / "c"
    assert analyze(capsys, good_ledger(tmp_path), out_dir)[0] == 0
    assert (out_dir / "results.xlsx").is_file()


def test_default_out_dir_is_out(tmp_path, capsys, monkeypatch):
    ledger = good_ledger(tmp_path)
    monkeypatch.chdir(tmp_path)
    code, out, _ = run(capsys, "analyze", ledger)
    assert code == 0
    assert out == done(0, 0, Path("out") / "results.xlsx")
    assert (tmp_path / "out" / "results.xlsx").is_file()


# The first error in the order of rule.exit_codes wins: one test per adjacent pair


def test_order_usage_before_missing_file(tmp_path, capsys):
    absent = str(tmp_path / "absent.csv")
    assert analyze(capsys, absent, tmp_path, "--round-base", "0") == (1, "", content.ERR_USAGE)


def test_order_ledger_missing_before_holidays_missing(tmp_path, capsys):
    absent = tmp_path / "absent.csv"
    other = tmp_path / "other.csv"
    assert analyze(capsys, str(absent), tmp_path, "--holidays", str(other)) == (
        1,
        "",
        content.ERR_MISSING_FILE.format(path=absent),
    )


def test_order_missing_file_before_existing_output(tmp_path, capsys):
    (tmp_path / "results.xlsx").write_bytes(b"previous")
    absent = tmp_path / "absent.csv"
    assert analyze(capsys, str(absent), tmp_path) == (
        1,
        "",
        content.ERR_MISSING_FILE.format(path=absent),
    )


def test_order_existing_output_before_unwritable_folder(tmp_path, capsys, monkeypatch):
    ledger = good_ledger(tmp_path)
    results = tmp_path / "results.xlsx"
    results.write_bytes(b"previous")
    block_touch(monkeypatch)
    assert analyze(capsys, ledger, tmp_path) == (1, "", content.ERR_EXISTS.format(path=results))


def test_order_unwritable_folder_before_invalid_holidays(tmp_path, capsys):
    not_a_folder = tmp_path / "file.txt"
    not_a_folder.write_text("x", encoding="utf-8")
    holidays = write_csv(tmp_path, "not a date", name="holidays.csv")
    assert analyze(capsys, good_ledger(tmp_path), not_a_folder, "--holidays", holidays) == (
        1,
        "",
        content.ERR_OUT_DIR.format(path=not_a_folder),
    )


def test_order_invalid_holidays_before_unreadable_ledger(tmp_path, capsys):
    ledger = tmp_path / "ledger.csv"
    ledger.write_bytes(b"\xff\xfe\x00binary")
    holidays = write_csv(tmp_path, "not a date", name="holidays.csv")
    assert analyze(capsys, str(ledger), tmp_path / "out", "--holidays", holidays) == (
        1,
        "",
        content.ERR_HOLIDAYS.format(line=1),
    )


def test_order_unreadable_before_missing_columns(tmp_path, capsys):
    ledger = write_csv(tmp_path, "entry_id,entry_id")
    assert analyze(capsys, ledger, tmp_path / "out") == (
        2,
        "",
        content.ERR_UNREADABLE.format(path=ledger),
    )


# Writable check


def test_folder_that_refuses_a_file_gives_the_output_directory_error(
    tmp_path, capsys, monkeypatch
):
    ledger = good_ledger(tmp_path)
    block_touch(monkeypatch)
    out_dir = tmp_path / "out"
    assert analyze(capsys, ledger, out_dir) == (1, "", content.ERR_OUT_DIR.format(path=out_dir))


def test_failure_after_the_writable_check_leaves_the_folder_empty(tmp_path, capsys):
    ledger = write_csv(tmp_path, "a,b", "1,2")
    out_dir = tmp_path / "out"
    assert analyze(capsys, ledger, out_dir)[0] == 2
    assert list(out_dir.iterdir()) == []


def test_success_leaves_only_the_results_in_the_folder(tmp_path, capsys):
    out_dir = tmp_path / "out"
    assert analyze(capsys, good_ledger(tmp_path), out_dir)[0] == 0
    assert [path.name for path in out_dir.iterdir()] == ["results.xlsx"]


# Paths that exist but are folders (decision 2 of the plan for holidays)


def test_folder_as_ledger_is_unreadable(tmp_path, capsys):
    folder = tmp_path / "folder"
    folder.mkdir()
    assert analyze(capsys, str(folder), tmp_path / "out") == (
        2,
        "",
        content.ERR_UNREADABLE.format(path=folder),
    )


def test_folder_as_holidays_uses_the_missing_file_error(tmp_path, capsys):
    folder = tmp_path / "folder"
    folder.mkdir()
    assert analyze(
        capsys, good_ledger(tmp_path), tmp_path / "out", "--holidays", str(folder)
    ) == (1, "", content.ERR_MISSING_FILE.format(path=folder))


def test_empty_holidays_value_is_a_missing_file(tmp_path, capsys):
    assert analyze(capsys, good_ledger(tmp_path), tmp_path / "out", "--holidays", "") == (
        1,
        "",
        content.ERR_MISSING_FILE.format(path=""),
    )


# Usage errors


@pytest.mark.parametrize("option", ["--round-base", "--benford-min-rows"])
@pytest.mark.parametrize("value", ["0", "-5", "1_000", "١٢", "1.5", " 5", ""])
def test_bad_number_gives_only_the_usage_error(tmp_path, capsys, option, value):
    ledger = good_ledger(tmp_path)
    assert run(capsys, "analyze", ledger, f"{option}={value}") == (1, "", content.ERR_USAGE)


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["unknown"],
        ["analyze"],
        ["analyze", "ledger.csv", "--round-base"],
        ["analyze", "ledger.csv", "--unknown"],
        ["analyze", "ledger.csv", "--over"],
        ["--he"],
        ["analyze", "ledger.csv", "extra.csv"],
    ],
)
def test_bad_arguments_give_only_the_usage_error(capsys, argv):
    assert run(capsys, *argv) == (1, "", content.ERR_USAGE)


@pytest.mark.parametrize("argv", [["--help"], ["analyze", "--help"]])
def test_help_gives_code_0(capsys, monkeypatch, argv):
    monkeypatch.setenv("COLUMNS", "200")
    code, out, err = run(capsys, *argv)
    assert (code, err) == (0, "")
    assert content.HELP_ANALYZE in out


def test_analyze_help_lists_every_option(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    _, out, _ = run(capsys, "analyze", "--help")
    for option in ("--out-dir", "--round-base", "--holidays", "--benford-min-rows", "--overwrite"):
        assert option in out


# Output encoding


def test_path_the_console_cannot_encode_does_not_crash_a_finished_run(tmp_path):
    out_dir = tmp_path / "saída"
    finished = subprocess.run(
        [script(), "analyze", good_ledger(tmp_path), "--out-dir", str(out_dir)],
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "ascii:strict"},
    )
    assert finished.returncode == 0
    assert b"sa\\xedda" in finished.stdout
    assert (out_dir / "results.xlsx").is_file()


def test_stream_with_no_reconfigure_does_not_stop_the_run(tmp_path):
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        code = main(["analyze", good_ledger(tmp_path), "--out-dir", str(tmp_path / "out")])
    assert code == 0
    assert stream.getvalue().rstrip("\n") == done(0, 0, tmp_path / "out" / "results.xlsx")


def test_no_stdout_does_not_stop_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    assert main(["analyze", good_ledger(tmp_path), "--out-dir", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "results.xlsx").is_file()


# Broken quoting (rule.file_structure)


def test_unclosed_quote_gives_code_2_and_no_workbook(tmp_path, capsys):
    ledger = write_csv(
        tmp_path,
        HEADER + ",description",
        'E1,1,2025-01-15,6100,10.50,"unclosed',
        "E2,2,2025-01-18,6100,1000.00,a",
        "E3,9,2025-01-18,6100,1000.00,b",
    )
    assert analyze(capsys, ledger, tmp_path / "out") == (
        2,
        "",
        content.ERR_UNREADABLE.format(path=ledger),
    )
    assert not (tmp_path / "out" / "results.xlsx").exists()


# Too many rows for one sheet (rule.excel_writing)


def test_too_many_rows_gives_code_1_and_no_workbook(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(excel_writer, "MAX_TABLE_ROWS", 1)
    ledger = write_csv(tmp_path, HEADER, SATURDAY_ROW, SATURDAY_ROW)
    assert analyze(capsys, ledger, tmp_path / "out") == (
        1,
        "",
        content.ERR_TOO_MANY_ROWS.format(sheet=content.SHEET_DUPLICATES),
    )
    assert not (tmp_path / "out" / "results.xlsx").exists()
