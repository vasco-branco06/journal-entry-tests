"""Tests of unit U3 from spec/TESTS.xml: the five tests, the aggregator and the fixtures.

There is no CLI yet, so tests that say "run analyze" call the functions directly.
"""

import csv
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from journal_entry_tests import content
from journal_entry_tests.checks import (
    ALERT_COLUMNS,
    BENFORD_EXPECTED,
    HolidaysError,
    aggregate,
    check_benford,
    check_duplicates,
    check_gaps,
    check_round,
    check_weekend,
    classify_mad,
    read_holidays,
)
from journal_entry_tests.validation import read_ledger

FIXTURES = Path(__file__).parent / "fixtures"
HEADER = "entry_id,document_number,posting_date,account_code,amount"
WEEKDAY = "2025-01-15"
SATURDAY = "2025-01-18"
SUNDAY = "2025-01-19"
BIG = 2**70


def ledger(tmp_path, *rows):
    path = tmp_path / "ledger.csv"
    path.write_text("\n".join((HEADER, *rows)) + "\n", encoding="utf-8")
    result = read_ledger(path)
    assert result.rejected.empty
    return result.valid


def row(number=1, date=WEEKDAY, account="6100", amount="10.50", entry_id=None):
    return f"{entry_id or f'E{number}'},{number},{date},{account},{amount}"


def amounts_ledger(tmp_path, *amounts):
    return ledger(tmp_path, *(row(i, amount=a) for i, a in enumerate(amounts, start=1)))


def source_rows(alerts):
    return alerts["source_row"].tolist()


def counts_frame(counts):
    """A table with only the column Benford reads; each amount starts with its digit."""
    cents = [
        digit * 100 for digit, count in zip(range(1, 10), counts, strict=True) for _ in range(count)
    ]
    return pd.DataFrame({"amount_cents": cents})


def counts_with_mad(target, n_rows=20000):
    """Move 1.5 * target from digits 7 to 9 to digits 1 to 3, which gives that MAD."""
    shift = 1.5 * target
    proportions = BENFORD_EXPECTED + shift * np.array([1, 1, 1, 0, 0, 0, -1, -1, -1])
    counts = np.rint(proportions * n_rows).astype(int)
    counts[0] += n_rows - counts.sum()
    return counts.tolist()


def run_all(path, holidays=frozenset()):
    valid = read_ledger(path).valid
    benford_alerts, benford = check_benford(valid)
    four = [
        check_duplicates(valid),
        check_round(valid),
        check_weekend(valid, holidays),
        check_gaps(valid),
    ]
    return four, benford_alerts, benford


# test.fixture_recall


def test_fixture_recall():
    holidays = read_holidays(FIXTURES / "holidays.csv")
    four, benford_alerts, _ = run_all(FIXTURES / "ledger_planted.csv", holidays)
    alerts = aggregate(*four, benford_alerts)

    with (FIXTURES / "ground_truth.csv").open(newline="", encoding="utf-8") as file:
        truth = list(csv.DictReader(file))
    assert truth
    for problem in truth:
        found = alerts[alerts["test_id"] == problem["test_id"]]
        if problem["test_id"] == "benford":
            assert len(found) == 1
        elif problem["test_id"] == "gaps":
            assert int(problem["document_number"]) in found["document_number"].tolist()
        else:
            assert int(problem["source_row"]) in found["source_row"].tolist()


# test.fixture_clean


def test_fixture_clean():
    four, _, _ = run_all(FIXTURES / "ledger_clean.csv")
    assert all(alerts.empty for alerts in four)


# test.benford_mad


@pytest.mark.parametrize(
    ("target", "classification"),
    [
        (0.005, "close"),
        (0.010, "acceptable"),
        (0.014, "marginal"),
        (0.020, "non_conforming"),
    ],
)
def test_benford_classifies_distributions(target, classification):
    alerts, result = check_benford(counts_frame(counts_with_mad(target)))
    assert result.mad == pytest.approx(target, abs=2e-4)
    assert result.classification == classification
    # rule.benford_alert: one population-level alert, only for the two higher classes.
    expected_alerts = 1 if classification in ("marginal", "non_conforming") else 0
    assert len(alerts) == expected_alerts
    if expected_alerts:
        alert = alerts.iloc[0]
        assert alert["test_id"] == "benford"
        assert alert["reason"] == content.REASON_BENFORD
        assert alert["source_row"] is None


@pytest.mark.parametrize(
    ("mad", "classification"),
    [
        (0.0, "close"),
        (0.0059999, "close"),
        (0.006, "acceptable"),
        (0.0119999, "acceptable"),
        (0.012, "marginal"),
        (0.0149999, "marginal"),
        (0.015, "non_conforming"),
    ],
)
def test_benford_exact_thresholds(mad, classification):
    assert classify_mad(mad) == classification


def test_benford_result_fields():
    counts = counts_with_mad(0.010)
    _, result = check_benford(counts_frame(counts))
    assert result.n_rows == sum(counts)
    assert result.digit_counts == counts
    assert result.chi2 > 0
    assert 0 <= result.p_value <= 1


# test.benford_min_rows


def test_benford_does_not_run_with_999_rows(tmp_path):
    alerts, result = check_benford(amounts_ledger(tmp_path, *["1.00"] * 999))
    assert alerts.empty
    assert result.n_rows == 999
    assert result[1:] == (None, None, None, None, None)


def test_benford_runs_with_1000_rows(tmp_path):
    alerts, result = check_benford(amounts_ledger(tmp_path, *["1.00"] * 1000))
    assert result.n_rows == 1000
    assert result.digit_counts == [1000, 0, 0, 0, 0, 0, 0, 0, 0]
    assert result.classification == "non_conforming"
    assert len(alerts) == 1


def test_benford_excludes_zero_from_the_minimum(tmp_path):
    _, result = check_benford(amounts_ledger(tmp_path, *["1.00"] * 999, "0.00"))
    assert result.n_rows == 999
    assert result.mad is None


def test_benford_min_rows_is_configurable(tmp_path):
    _, result = check_benford(amounts_ledger(tmp_path, "1.00", "2.00"), min_rows=2)
    assert result.digit_counts == [1, 1, 0, 0, 0, 0, 0, 0, 0]


def test_benford_uses_first_significant_digit_of_absolute_amount(tmp_path):
    valid = amounts_ledger(tmp_path, "0.05", "-0.70", "-3.00", "12.50")
    _, result = check_benford(valid, min_rows=1)
    assert result.digit_counts == [1, 0, 1, 0, 1, 0, 1, 0, 0]


# test.round_base


def test_round_base_1000(tmp_path):
    valid = amounts_ledger(tmp_path, "999.99", "1000", "5000", "-2000", "1500", "0", "1000.50")
    alerts = check_round(valid)
    assert source_rows(alerts) == [3, 4, 5]
    assert set(alerts["reason"]) == {content.REASON_ROUND.format(base=1000)}
    assert alerts["detail"].tolist() == ["1000.00", "5000.00", "-2000.00"]


def test_round_base_500(tmp_path):
    valid = amounts_ledger(tmp_path, "999.99", "1000", "5000", "-2000", "1500", "0", "500", "400")
    alerts = check_round(valid, base=500)
    assert source_rows(alerts) == [3, 4, 5, 6, 8]
    assert set(alerts["reason"]) == {content.REASON_ROUND.format(base=500)}


# rule.duplicate


def test_duplicates_alert_on_every_row_of_the_group(tmp_path):
    valid = ledger(
        tmp_path,
        row(1),
        row(2),
        row(3),
        row(4, account="6200"),
        row(5, amount="-10.50"),
        row(6, date="2025-01-16"),
    )
    alerts = check_duplicates(valid)
    assert source_rows(alerts) == [2, 3, 4]
    assert set(alerts["reason"]) == {content.REASON_DUPLICATE}
    assert alerts["detail"].tolist() == [f"6100 10.50 {WEEKDAY}"] * 3


def test_duplicates_keep_each_row_of_a_repeated_entry_id(tmp_path):
    valid = ledger(tmp_path, row(1, entry_id="E"), row(2, entry_id="E"))
    assert source_rows(check_duplicates(valid)) == [2, 3]


# rule.weekend_holiday and test.holidays


def test_weekend_without_holidays(tmp_path):
    valid = ledger(tmp_path, row(1), row(2, date=SATURDAY), row(3, date=SUNDAY))
    alerts = check_weekend(valid)
    assert source_rows(alerts) == [3, 4]
    assert set(alerts["reason"]) == {content.REASON_WEEKEND}
    assert alerts["detail"].tolist() == [SATURDAY, SUNDAY]


def test_holiday_on_weekday_and_on_weekend(tmp_path):
    valid = ledger(tmp_path, row(1), row(2, date=SATURDAY), row(3, date=SUNDAY))
    holidays = {dt.date.fromisoformat(WEEKDAY), dt.date.fromisoformat(SATURDAY)}
    alerts = check_weekend(valid, holidays)
    # One alert per row; a date that is both a weekend and a holiday gives the holiday reason.
    assert source_rows(alerts) == [2, 3, 4]
    assert alerts["reason"].tolist() == [
        content.REASON_HOLIDAY,
        content.REASON_HOLIDAY,
        content.REASON_WEEKEND,
    ]


def write_holidays(tmp_path, data: bytes):
    path = tmp_path / "holidays.csv"
    path.write_bytes(data)
    return path


def test_holidays_invalid_line_is_named(tmp_path):
    path = write_holidays(tmp_path, b"2025-01-01\nnot a date\n")
    with pytest.raises(HolidaysError) as error:
        read_holidays(path)
    assert str(error.value) == content.ERR_HOLIDAYS.format(line=2)


@pytest.mark.parametrize(
    "bad",
    [
        b"2025-02-30",
        b"20250101",
        b"2025-1-1",
        b" 2025-01-01",
        b"2025-01-01 ",
        b"2025-01-01,x",
        "2025-01-0١".encode(),
        b"\xff\xfe",
    ],
)
def test_holidays_rejects(tmp_path, bad):
    # Blank lines still count for the line number.
    path = write_holidays(tmp_path, b"2025-01-01\n\n" + bad + b"\n")
    with pytest.raises(HolidaysError) as error:
        read_holidays(path)
    assert str(error.value) == content.ERR_HOLIDAYS.format(line=3)


def test_holidays_accepts_bom_blank_lines_repeats_and_crlf(tmp_path):
    path = write_holidays(
        tmp_path, b"\xef\xbb\xbf2025-01-01\r\n\r\n   \r\n2025-01-01\r\n2025-12-25"
    )
    assert read_holidays(path) == {dt.date(2025, 1, 1), dt.date(2025, 12, 25)}


def test_holidays_empty_file_has_no_dates(tmp_path):
    assert read_holidays(write_holidays(tmp_path, b"")) == set()


# rule.gaps


def test_gaps_one_alert_per_range_ignoring_repeats_and_order(tmp_path):
    valid = ledger(tmp_path, *(row(n) for n in (10, 3, 1, 3, 2, 7)))
    alerts = check_gaps(valid)
    assert alerts["document_number"].tolist() == [4, 8]
    assert alerts["reason"].tolist() == [
        content.REASON_GAP.format(first=4, last=6),
        content.REASON_GAP.format(first=8, last=9),
    ]
    assert alerts["source_row"].tolist() == [None, None]
    assert alerts["entry_id"].tolist() == [None, None]


def test_gaps_negative_numbers(tmp_path):
    valid = ledger(tmp_path, row(-3), row(1))
    assert check_gaps(valid)["reason"].tolist() == [content.REASON_GAP.format(first=-2, last=0)]


def test_no_gaps_with_consecutive_or_single_number(tmp_path):
    assert check_gaps(ledger(tmp_path, row(1), row(2), row(2))).empty
    assert check_gaps(ledger(tmp_path, row(5))).empty


# Integers above 64 bits: pandas holds these columns as uint64 or object.


@pytest.mark.parametrize(
    "numbers",
    [
        (1, 2**63),  # uint64 column
        (1, BIG),  # object column
        (-1, 2**63),  # object column, mixed signs
        (-BIG, BIG),
    ],
)
def test_gaps_with_big_numbers_are_exact(tmp_path, numbers):
    low, high = numbers
    valid = ledger(tmp_path, row(low), row(high))
    alerts = check_gaps(valid)
    # A huge range is one alert, and must not be walked through.
    assert alerts["document_number"].tolist() == [low + 1]
    assert type(alerts["document_number"].iloc[0]) is int
    assert alerts["reason"].tolist() == [content.REASON_GAP.format(first=low + 1, last=high - 1)]


@pytest.mark.parametrize("big", [2**63, 2**64, BIG])
def test_big_amounts_in_every_test(tmp_path, big):
    units = 1000 * big
    amount = f"{units}.00"
    valid = ledger(
        tmp_path,
        row(1, amount=amount),
        row(2, amount=amount),
        row(3, amount=f"{units + 1}.00", date=SATURDAY),
        row(4, amount=f"-{units}.00"),
        row(5, amount=f"{units}.01"),
        row(big, amount="7.00"),
    )
    assert valid["amount_cents"].iloc[0] == units * 100

    assert source_rows(check_duplicates(valid)) == [2, 3]
    # Through a float, the amounts one unit or one cent away would also look like multiples.
    assert source_rows(check_round(valid)) == [2, 3, 5]
    assert check_round(valid)["detail"].tolist() == [amount, amount, f"-{amount}"]

    weekend = check_weekend(valid)
    assert source_rows(weekend) == [4]
    assert weekend["document_number"].tolist() == [3]

    gaps = check_gaps(valid)
    assert gaps["document_number"].tolist() == [6]
    assert gaps["reason"].tolist() == [content.REASON_GAP.format(first=6, last=big - 1)]

    benford_alerts, result = check_benford(valid, min_rows=6)
    first_digit = int(str(units)[0])
    assert result.digit_counts[first_digit - 1] >= 4
    assert sum(result.digit_counts) == 6

    joined = aggregate(check_round(valid), check_duplicates(valid), gaps, benford_alerts)
    assert joined[joined["test_id"] == "gaps"]["reason"].tolist() == gaps["reason"].tolist()


def test_big_document_number_survives_in_row_alerts(tmp_path):
    valid = ledger(tmp_path, row(BIG, amount="1000"), row(BIG + 1, amount="5.00"))
    alerts = aggregate(check_round(valid))
    assert alerts["document_number"].tolist() == [BIG]
    assert type(alerts["document_number"].iloc[0]) is int


# Ledger with only a header.


def test_header_only_ledger_gives_no_alerts(tmp_path):
    valid = ledger(tmp_path)
    assert check_duplicates(valid).empty
    assert check_round(valid).empty
    assert check_weekend(valid).empty
    assert check_gaps(valid).empty
    alerts, result = check_benford(valid)
    assert alerts.empty
    assert result.n_rows == 0
    assert result.mad is None
    joined = aggregate(check_duplicates(valid), alerts)
    assert joined.empty
    assert tuple(joined.columns) == ALERT_COLUMNS


# test.aggregator


def test_aggregator_common_format_and_order(tmp_path):
    valid = ledger(
        tmp_path,
        row(1, amount="1000", date=SATURDAY),
        row(2, date=SUNDAY),
        row(5, amount="2000"),
        row(9),
    )
    alerts = aggregate(check_weekend(valid), check_round(valid), check_gaps(valid))
    assert tuple(alerts.columns) == ALERT_COLUMNS
    assert alerts["test_id"].tolist() == ["gaps", "gaps", "round", "round", "weekend", "weekend"]
    assert alerts["source_row"].tolist() == [None, None, 2, 4, 2, 3]
    assert alerts["document_number"].tolist() == [3, 6, 1, 5, 1, 2]


def test_aggregator_sorts_rows_given_out_of_order_and_puts_empty_row_last():
    def table(*rows):
        return pd.DataFrame(list(rows), columns=ALERT_COLUMNS, dtype=object)

    first = table(
        ("round", 9, "E9", 9, "r", "d"),
        ("round", None, None, 8, "no row", None),
        ("round", 2, "E2", 2, "r", "d"),
    )
    second = table(("duplicates", 5, "E5", 5, "r", "d"))
    alerts = aggregate(first, second)
    assert alerts["test_id"].tolist() == ["duplicates", "round", "round", "round"]
    assert alerts["source_row"].tolist() == [5, 2, 9, None]
    assert alerts["reason"].iloc[3] == "no row"
