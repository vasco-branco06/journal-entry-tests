"""The five journal entry tests and the aggregator that joins their alerts.

amount_cents and document_number can exceed 64 bits, so pandas may hold them as int64, uint64 or
object. Arithmetic on them therefore uses Python integers, never vectorised operations.
"""

import codecs
import datetime as dt
from collections.abc import Collection
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd
from scipy import stats

from . import content
from .validation import DATE

ALERT_COLUMNS = ("test_id", "source_row", "entry_id", "document_number", "reason", "detail")
DEFAULT_ROUND_BASE = 1000
DEFAULT_BENFORD_MIN_ROWS = 1000
CENTS_PER_UNIT = 100
SATURDAY = 5
# Proportion of each first digit, 1 to 9, under Benford's law.
BENFORD_EXPECTED = np.log10(1 + 1 / np.arange(1, 10))


class HolidaysError(Exception):
    """The holidays file has an invalid line: exit code 1. The message is ready to show."""


class BenfordResult(NamedTuple):
    """Everything except n_rows is None when the test did not run."""

    n_rows: int
    mad: float | None = None
    chi2: float | None = None
    p_value: float | None = None
    classification: str | None = None
    digit_counts: list[int] | None = None


def read_holidays(path: str | Path) -> set[dt.date]:
    """Read one date per line. A missing file raises FileNotFoundError for the caller."""
    holidays = set()
    data = Path(path).read_bytes().removeprefix(codecs.BOM_UTF8)
    # Decoded line by line: a line that is not valid UTF-8 is an invalid line, not a bad file.
    for number, line in enumerate(data.splitlines(), start=1):
        if line.strip():
            holidays.add(_parse_holiday(line, number))
    return holidays


def _parse_holiday(line: bytes, number: int) -> dt.date:
    try:
        text = line.decode("utf-8")
        if not DATE.fullmatch(text):
            raise ValueError(text)
        return dt.date.fromisoformat(text)
    except ValueError as exc:  # UnicodeDecodeError is a ValueError too.
        raise HolidaysError(content.ERR_HOLIDAYS.format(line=number)) from exc


def check_duplicates(valid: pd.DataFrame) -> pd.DataFrame:
    """Alert on every row sharing account_code, signed amount and posting_date with another."""
    repeated = valid.duplicated(["account_code", "amount_cents", "posting_date"], keep=False)
    return _table(
        _alert(
            "duplicates",
            row,
            content.REASON_DUPLICATE,
            f"{row['account_code']} {_format_cents(row['amount_cents'])} {row['posting_date']}",
        )
        for row in valid[repeated].to_dict("records")
    )


def check_round(valid: pd.DataFrame, base: int = DEFAULT_ROUND_BASE) -> pd.DataFrame:
    """Alert on absolute amounts of at least base that are a multiple of base (in units)."""
    base_cents = base * CENTS_PER_UNIT
    reason = content.REASON_ROUND.format(base=base)
    return _table(
        _alert("round", row, reason, _format_cents(row["amount_cents"]))
        for row in valid.to_dict("records")
        if abs(row["amount_cents"]) >= base_cents and row["amount_cents"] % base_cents == 0
    )


def check_weekend(valid: pd.DataFrame, holidays: Collection[dt.date] = frozenset()) -> pd.DataFrame:
    """Alert once per row posted on a weekend or holiday; holiday wins when it is both."""
    alerts = []
    for row in valid.to_dict("records"):
        date = row["posting_date"]
        if date in holidays:
            alerts.append(_alert("weekend", row, content.REASON_HOLIDAY, date.isoformat()))
        elif date.weekday() >= SATURDAY:
            alerts.append(_alert("weekend", row, content.REASON_WEEKEND, date.isoformat()))
    return _table(alerts)


def check_gaps(valid: pd.DataFrame) -> pd.DataFrame:
    """Alert once per missing range between the distinct document numbers."""
    numbers = sorted(set(valid["document_number"].tolist()))
    return _table(
        (
            "gaps",
            None,
            None,
            low + 1,
            content.REASON_GAP.format(first=low + 1, last=high - 1),
            None,
        )
        for low, high in zip(numbers, numbers[1:], strict=False)
        if high - low > 1
    )


def check_benford(
    valid: pd.DataFrame, min_rows: int = DEFAULT_BENFORD_MIN_ROWS
) -> tuple[pd.DataFrame, BenfordResult]:
    """Compare first digits with Benford's law; the MAD alone decides the classification."""
    digits = [str(abs(cents))[0] for cents in valid["amount_cents"].tolist() if cents != 0]
    n_rows = len(digits)
    if n_rows < min_rows:
        return _table([]), BenfordResult(n_rows)

    counts = np.array([digits.count(str(digit)) for digit in range(1, 10)])
    mad = float(np.abs(counts / n_rows - BENFORD_EXPECTED).mean())
    chi2, p_value = stats.chisquare(counts, n_rows * BENFORD_EXPECTED)
    classification = classify_mad(mad)
    result = BenfordResult(
        n_rows, mad, float(chi2), float(p_value), classification, counts.tolist()
    )
    if classification in ("marginal", "non_conforming"):
        alert = ("benford", None, None, None, content.REASON_BENFORD, classification)
        return _table([alert]), result
    return _table([]), result


def classify_mad(mad: float) -> str:
    """Nigrini thresholds; a value equal to a threshold belongs to the higher class."""
    if mad < 0.006:
        return "close"
    if mad < 0.012:
        return "acceptable"
    if mad < 0.015:
        return "marginal"
    return "non_conforming"


def aggregate(*tables: pd.DataFrame) -> pd.DataFrame:
    """Join alert tables, sorted by test_id and source_row, with empty source_row last."""
    rows = [row for table in tables for row in table.itertuples(index=False, name=None)]
    return _table(sorted(rows, key=lambda row: (row[0], row[1] is None, row[1] or 0)))


def _alert(test_id: str, row: dict, reason: str, detail: str) -> tuple:
    return (test_id, row["source_row"], row["entry_id"], row["document_number"], reason, detail)


def _table(rows) -> pd.DataFrame:
    # dtype=object keeps big integers exact and None as None.
    return pd.DataFrame(list(rows), columns=ALERT_COLUMNS, dtype=object)


def _format_cents(cents: int) -> str:
    units, remainder = divmod(abs(cents), CENTS_PER_UNIT)
    return f"{'-' if cents < 0 else ''}{units}.{remainder:02d}"
