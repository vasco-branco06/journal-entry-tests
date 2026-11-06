"""Tests test.amount_cents, test.validation_rows and test.file_structure from spec/TESTS.xml."""

import datetime as dt

import pytest

from journal_entry_tests import content
from journal_entry_tests.validation import LedgerError, read_ledger

HEADER = "entry_id,document_number,posting_date,account_code,amount"
GOOD = "E1,1,2025-01-15,6100,10.00"


def write(tmp_path, text, encoding="utf-8"):
    path = tmp_path / "ledger.csv"
    path.write_bytes(text.encode(encoding))
    return path


def ledger(tmp_path, *rows, header=HEADER):
    return read_ledger(write(tmp_path, "\n".join((header, *rows)) + "\n"))


def row_with(entry_id="E1", number="1", date="2025-01-15", account="6100", amount="10.00"):
    return f"{entry_id},{number},{date},{account},{amount}"


# test.amount_cents


@pytest.mark.parametrize(
    ("amount", "cents"),
    [
        ("0.10", 10),
        ("0.20", 20),
        ("1250.4", 125040),
        ("7", 700),
        ("-2000", -200000),
        ("+3.05", 305),
        ("-0.01", -1),
        ("0", 0),
        # Binary floats would lose these.
        ("1.15", 115),
        ("90071992547409.93", 9007199254740993),
    ],
)
def test_amount_converts_to_exact_cents(tmp_path, amount, cents):
    result = ledger(tmp_path, row_with(amount=amount))
    assert result.rejected.empty
    assert result.valid.loc[0, "amount_cents"] == cents


@pytest.mark.parametrize("amount", ["1.000", "0.125"])
def test_amount_with_three_decimals_is_rejected(tmp_path, amount):
    result = ledger(tmp_path, row_with(amount=amount))
    assert result.valid.empty
    assert result.rejected.loc[0, "reason"] == content.REJ_DECIMALS


@pytest.mark.parametrize(
    "amount",
    ["1_000", "1E+3", "NaN", "Infinity", '"1250,40"', ".5", "5.", " 5", "5 ", "abc", "١٢", "--5"],
)
def test_amount_in_other_formats_is_rejected(tmp_path, amount):
    result = ledger(tmp_path, row_with(amount=amount))
    assert result.valid.empty
    assert result.rejected.loc[0, "reason"] == content.REJ_BAD_AMOUNT


def test_amount_above_int64_keeps_its_value(tmp_path):
    result = ledger(tmp_path, row_with(amount="99999999999999999999"))
    assert result.valid.loc[0, "amount_cents"] == 9999999999999999999900


# test.validation_rows


@pytest.mark.parametrize(
    "date", ["2025-02-30", "20240131", "2024-W05-3", "2025-1-5", "15/01/2025", " 2025-01-15"]
)
def test_invalid_date_is_rejected(tmp_path, date):
    result = ledger(tmp_path, row_with(date=date))
    assert result.valid.empty
    assert result.rejected.loc[0, "reason"] == content.REJ_BAD_DATE


@pytest.mark.parametrize("number", ["1_000", "١٢", "1.5", " 7", "abc"])
def test_invalid_document_number_is_rejected(tmp_path, number):
    result = ledger(tmp_path, row_with(number=number))
    assert result.valid.empty
    assert result.rejected.loc[0, "reason"] == content.REJ_BAD_INTEGER


@pytest.mark.parametrize("entry_id", ["", "   "])
def test_empty_id_is_rejected(tmp_path, entry_id):
    result = ledger(tmp_path, row_with(entry_id=entry_id))
    assert result.rejected.loc[0, "reason"] == content.REJ_MISSING_VALUE.format(column="entry_id")


@pytest.mark.parametrize(
    ("row", "column"),
    [
        (row_with(entry_id="x" * 300) + ",d", "entry_id"),
        (row_with(amount="1" * 5000) + ",d", "amount"),
        (row_with(number="1" * 5000) + ",d", "document_number"),
        (row_with() + ",y" + "z" * 300, "description"),
    ],
)
def test_text_above_255_is_rejected(tmp_path, row, column):
    result = ledger(tmp_path, row, header=HEADER + ",description")
    assert result.rejected.loc[0, "reason"] == content.REJ_TOO_LONG.format(column=column)


def test_text_of_exactly_255_is_valid(tmp_path):
    result = ledger(tmp_path, row_with(entry_id="x" * 255))
    assert result.rejected.empty


@pytest.mark.parametrize(
    ("entry_type", "accepted", "stored"),
    [
        ("manual", True, "manual"),
        ("automatic", True, "automatic"),
        ("", True, ""),
        ("   ", True, ""),
        ("Manual", False, None),
        (" manual", False, None),
        ("other", False, None),
    ],
)
def test_entry_type(tmp_path, entry_type, accepted, stored):
    result = ledger(tmp_path, f"{GOOD},{entry_type}", header=HEADER + ",entry_type")
    if accepted:
        assert result.valid.loc[0, "entry_type"] == stored
    else:
        assert result.rejected.loc[0, "reason"] == content.REJ_BAD_ENTRY_TYPE


def test_bad_rows_do_not_stop_the_analysis(tmp_path):
    bad_date, no_id = row_with(date="bad"), row_with(entry_id="")
    result = ledger(tmp_path, GOOD, bad_date, no_id, "E4,4,2025-01-16,1,5")
    assert list(result.valid["source_row"]) == [2, 5]
    assert list(result.rejected["source_row"]) == [3, 4]
    assert result.rejected.loc[0, "raw_line"] == row_with(date="bad")


def test_valid_row_values(tmp_path):
    row = ledger(tmp_path, GOOD).valid.iloc[0]
    assert row["entry_id"] == "E1"
    assert row["document_number"] == 1
    assert row["posting_date"] == dt.date(2025, 1, 15)
    assert row["account_code"] == "6100"
    assert row["description"] == ""


def test_text_is_not_trimmed(tmp_path):
    row = ledger(tmp_path, row_with(account=" 6100 ")).valid.iloc[0]
    assert row["account_code"] == " 6100 "


def test_repeated_entry_id_gives_distinct_rows(tmp_path):
    result = ledger(tmp_path, GOOD, GOOD)
    assert list(result.valid["source_row"]) == [2, 3]


# test.file_structure


def test_extra_and_reordered_columns(tmp_path):
    header = "extra,amount,account_code,posting_date,document_number,entry_id"
    result = ledger(tmp_path, "z" * 300 + ",10.00,6100,2025-01-15,1,E1", header=header)
    assert result.rejected.empty
    assert result.valid.loc[0, "amount_cents"] == 1000
    assert result.valid.loc[0, "entry_id"] == "E1"


@pytest.mark.parametrize(
    ("row", "found"), [("E1,1,2025-01-15,6100", 4), ("E1,1,2025-01-15,6100,10.00,more", 6)]
)
def test_wrong_number_of_fields_is_rejected(tmp_path, row, found):
    result = ledger(tmp_path, row)
    reason = content.REJ_FIELD_COUNT.format(found=found, expected=5)
    assert result.rejected.loc[0, "reason"] == reason
    assert result.rejected.loc[0, "raw_line"] == row


def test_blank_lines_are_skipped_but_counted(tmp_path):
    result = ledger(tmp_path, GOOD, "", "", GOOD)
    assert result.rejected.empty
    assert list(result.valid["source_row"]) == [2, 5]


def test_source_row_of_a_multi_line_field_is_where_the_row_starts(tmp_path):
    multi = 'E2,2,2025-01-15,6100,10.00,"first\nsecond"'
    result = ledger(tmp_path, GOOD + ",a", multi, GOOD + ",c", header=HEADER + ",description")
    assert list(result.valid["source_row"]) == [2, 3, 5]
    assert result.valid.loc[1, "description"] == "first\nsecond"


def test_raw_line_of_a_rejected_multi_line_row(tmp_path):
    multi = 'E2,2,bad,6100,10.00,"first\nsecond"'
    result = ledger(tmp_path, multi, header=HEADER + ",description")
    assert result.rejected.loc[0, "source_row"] == 2
    assert result.rejected.loc[0, "raw_line"] == multi


def test_windows_line_endings(tmp_path):
    result = read_ledger(write(tmp_path, f"{HEADER}\r\n{GOOD}\r\n{row_with(date='bad')}\r\n"))
    assert list(result.valid["source_row"]) == [2]
    assert result.rejected.loc[0, "source_row"] == 3
    assert result.rejected.loc[0, "raw_line"] == row_with(date="bad")


def test_field_above_the_csv_default_limit_rejects_only_its_row(tmp_path):
    result = ledger(tmp_path, row_with(entry_id="x" * 200_000), GOOD)
    assert list(result.valid["source_row"]) == [3]
    assert len(result.rejected.loc[0, "raw_line"]) > 200_000


def test_bom_is_accepted(tmp_path):
    result = read_ledger(write(tmp_path, f"{HEADER}\n{GOOD}\n", encoding="utf-8-sig"))
    assert len(result.valid) == 1


def test_header_only_is_a_ledger_with_no_rows(tmp_path):
    result = read_ledger(write(tmp_path, HEADER + "\n"))
    assert result.valid.empty
    assert result.rejected.empty
    assert "amount_cents" in result.valid.columns
    assert "raw_line" in result.rejected.columns


@pytest.mark.parametrize("text", ["", "\n\n"])
def test_file_with_no_header_is_missing_all_columns(tmp_path, text):
    with pytest.raises(LedgerError) as error:
        read_ledger(write(tmp_path, text))
    columns = "entry_id, document_number, posting_date, account_code, amount"
    assert str(error.value) == content.ERR_MISSING_COLUMNS.format(columns=columns)


def test_missing_required_column_is_named(tmp_path):
    with pytest.raises(LedgerError) as error:
        read_ledger(write(tmp_path, "entry_id,document_number,posting_date,account_code\n"))
    assert str(error.value) == content.ERR_MISSING_COLUMNS.format(columns="amount")


def test_semicolon_file_is_a_file_error(tmp_path):
    with pytest.raises(LedgerError):
        read_ledger(write(tmp_path, HEADER.replace(",", ";") + "\n"))


def test_required_column_named_twice_is_a_file_error(tmp_path):
    path = write(tmp_path, HEADER + ",amount\n")
    with pytest.raises(LedgerError) as error:
        read_ledger(path)
    assert str(error.value) == content.ERR_UNREADABLE.format(path=path)


def test_required_column_named_twice_wins_over_a_missing_column(tmp_path):
    path = write(tmp_path, "entry_id,entry_id,document_number,posting_date,account_code\n")
    with pytest.raises(LedgerError) as error:
        read_ledger(path)
    assert str(error.value) == content.ERR_UNREADABLE.format(path=path)


@pytest.mark.parametrize(
    "data", [b"\xff\xfe\x00\x01binary", b"entry_id\x00,amount\n", "é".encode("latin-1")]
)
def test_binary_or_other_encoding_is_a_file_error(tmp_path, data):
    path = tmp_path / "ledger.csv"
    path.write_bytes(data)
    with pytest.raises(LedgerError) as error:
        read_ledger(path)
    assert str(error.value) == content.ERR_UNREADABLE.format(path=path)


def test_folder_is_a_file_error(tmp_path):
    with pytest.raises(LedgerError):
        read_ledger(tmp_path)


def test_missing_file_is_left_to_the_caller(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_ledger(tmp_path / "absent.csv")


def test_text_of_exactly_256_characters_is_rejected(tmp_path):
    result = ledger(tmp_path, row_with(entry_id="x" * 256))
    assert result.valid.empty
    assert result.rejected.loc[0, "reason"] == content.REJ_TOO_LONG.format(column="entry_id")


# Broken quoting and lines with only spaces (rule.file_structure)

DESCRIBED = HEADER + ",description"


@pytest.mark.parametrize(
    "rows",
    [
        # An unclosed quote would swallow the following rows into one field.
        ('E1,1,2025-01-15,6100,10.00,"unclosed', "E2,2,2025-01-18,6100,10.00,a"),
        ("E1,1,2025-01-15,6100,10.00,a", 'E2,2,2025-01-15,6100,"3.33,b', "E3,3,2025-01-15,6,1,c"),
        # Text after a closing quote would be joined to the value.
        ('E1,1,2025-01-15,6100,"10"00.00,a',),
        ('E1,"1"2,2025-01-15,6100,10.00,a',),
    ],
)
def test_broken_quoting_makes_the_file_unreadable(tmp_path, rows):
    path = write(tmp_path, "\n".join((DESCRIBED, *rows)) + "\n")
    with pytest.raises(LedgerError) as error:
        read_ledger(path)
    assert str(error.value) == content.ERR_UNREADABLE.format(path=path)


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ('"ok, comma"', "ok, comma"),
        ('"multi\nline"', "multi\nline"),
        ('"say ""hi"""', 'say "hi"'),
        ('he said "hi"', 'he said "hi"'),
    ],
)
def test_correct_quoting_is_still_read(tmp_path, description, expected):
    result = ledger(tmp_path, f"E1,1,2025-01-15,6100,10.00,{description}", header=DESCRIBED)
    assert result.rejected.empty
    assert result.valid.loc[0, "description"] == expected


def test_fully_quoted_numbers_are_still_read(tmp_path):
    result = ledger(tmp_path, 'E1,"12",2025-01-15,6100,"1000.00"')
    assert result.rejected.empty
    assert result.valid.loc[0, "document_number"] == 12
    assert result.valid.loc[0, "amount_cents"] == 100000


def test_quote_inside_an_unquoted_number_is_still_a_rejected_row(tmp_path):
    result = ledger(tmp_path, row_with(number='1"2'), GOOD)
    assert list(result.rejected["reason"]) == [content.REJ_BAD_INTEGER]
    assert len(result.valid) == 1


def test_lines_with_only_spaces_are_skipped_but_counted(tmp_path):
    result = ledger(tmp_path, GOOD, "   ", "\t", GOOD)
    assert result.rejected.empty
    assert list(result.valid["source_row"]) == [2, 5]


def test_header_after_a_line_with_only_spaces_is_found(tmp_path):
    result = read_ledger(write(tmp_path, f"   \n{HEADER}\n{GOOD}\n"))
    assert list(result.valid["source_row"]) == [3]


def test_several_fields_with_only_spaces_are_still_a_rejected_row(tmp_path):
    result = ledger(tmp_path, "  ,  ")
    assert result.valid.empty
    assert result.rejected.loc[0, "reason"] == content.REJ_FIELD_COUNT.format(found=2, expected=5)
