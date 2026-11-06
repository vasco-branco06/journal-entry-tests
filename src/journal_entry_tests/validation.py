"""Read a ledger CSV into a table of valid rows and a table of rejected rows."""

import csv
import datetime as dt
import io
import re
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import pandas as pd

from . import content

REQUIRED_COLUMNS = ("entry_id", "document_number", "posting_date", "account_code", "amount")
OPTIONAL_COLUMNS = ("description", "user_id", "entry_type")
VALID_COLUMNS = (
    "source_row",
    "entry_id",
    "document_number",
    "posting_date",
    "account_code",
    "amount_cents",
    "description",
    "user_id",
    "entry_type",
)
REJECTED_COLUMNS = ("source_row", "reason", "raw_line")
ENTRY_TYPES = ("manual", "automatic")
MAX_TEXT = 255
# Rows above the csv default limit must reach the length check instead of failing the file.
CSV_FIELD_LIMIT = 2**31 - 1

# Explicit [0-9]: int(), Decimal() and date.fromisoformat() accept forms the spec rejects.
INTEGER = re.compile(r"[+-]?[0-9]+")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
AMOUNT = re.compile(r"([+-]?)([0-9]+)(?:\.([0-9]+))?")


class LedgerError(Exception):
    """The file cannot be analysed at all: exit code 2. The message is ready to show."""


class ValidatedLedger(NamedTuple):
    valid: pd.DataFrame
    rejected: pd.DataFrame


class _Rejected(Exception):
    """A single row failed validation. The message is the reason."""


def read_ledger(path: str | Path) -> ValidatedLedger:
    """Validate the CSV at path. A missing file raises FileNotFoundError for the caller."""
    try:
        text = Path(path).read_bytes().decode("utf-8-sig")
    except FileNotFoundError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise LedgerError(content.ERR_UNREADABLE.format(path=path)) from exc
    if "\0" in text:
        raise LedgerError(content.ERR_UNREADABLE.format(path=path))
    try:
        return _validate(text, path)
    except csv.Error as exc:
        raise LedgerError(content.ERR_UNREADABLE.format(path=path)) from exc


def _validate(text: str, path: str | Path) -> ValidatedLedger:
    records = _records(text)
    _, _, header = next(records, (0, "", []))
    if any(header.count(column) > 1 for column in REQUIRED_COLUMNS):
        raise LedgerError(content.ERR_UNREADABLE.format(path=path))
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        raise LedgerError(content.ERR_MISSING_COLUMNS.format(columns=", ".join(missing)))
    positions = {
        column: header.index(column)
        for column in REQUIRED_COLUMNS + OPTIONAL_COLUMNS
        if column in header
    }

    valid, rejected = [], []
    for source_row, raw_line, fields in records:
        try:
            if len(fields) != len(header):
                raise _Rejected(
                    content.REJ_FIELD_COUNT.format(found=len(fields), expected=len(header))
                )
            values = {column: fields[position] for column, position in positions.items()}
            valid.append((source_row, *_parse_row(values)))
        except _Rejected as exc:
            rejected.append((source_row, str(exc), raw_line))
    return ValidatedLedger(
        pd.DataFrame(valid, columns=VALID_COLUMNS),
        pd.DataFrame(rejected, columns=REJECTED_COLUMNS),
    )


def _records(text: str) -> Iterator[tuple[int, str, list[str]]]:
    """Yield (line where the row starts, original text, fields), skipping blank lines."""
    consumed: list[str] = []

    def lines() -> Iterator[str]:
        for line in io.StringIO(text, newline=""):
            consumed.append(line)
            yield line

    csv.field_size_limit(CSV_FIELD_LIMIT)
    # strict: otherwise an unclosed quote swallows the next rows and "10"00 is read as 1000.
    reader = csv.reader(lines(), strict=True)
    for fields in reader:
        start = reader.line_num - len(consumed) + 1
        raw_line = "".join(consumed).rstrip("\r\n")
        consumed.clear()
        if len(fields) > 1 or (fields and fields[0].strip()):
            yield start, raw_line, fields


def _parse_row(values: dict[str, str]) -> tuple:
    """Return the row in VALID_COLUMNS order, without source_row, or raise _Rejected."""
    for column in REQUIRED_COLUMNS + OPTIONAL_COLUMNS:
        value = values.get(column, "")
        if column in REQUIRED_COLUMNS and not value.strip():
            raise _Rejected(content.REJ_MISSING_VALUE.format(column=column))
        # Checked first: it also keeps int() below its limit on the number of digits.
        if len(value) > MAX_TEXT:
            raise _Rejected(content.REJ_TOO_LONG.format(column=column))

    if not INTEGER.fullmatch(values["document_number"]):
        raise _Rejected(content.REJ_BAD_INTEGER)
    entry_type = values.get("entry_type", "")
    if not entry_type.strip():
        entry_type = ""
    elif entry_type not in ENTRY_TYPES:
        raise _Rejected(content.REJ_BAD_ENTRY_TYPE)
    return (
        values["entry_id"],
        int(values["document_number"]),
        _parse_date(values["posting_date"]),
        values["account_code"],
        amount_to_cents(values["amount"]),
        values.get("description", ""),
        values.get("user_id", ""),
        entry_type,
    )


def _parse_date(value: str) -> dt.date:
    if not DATE.fullmatch(value):
        raise _Rejected(content.REJ_BAD_DATE)
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise _Rejected(content.REJ_BAD_DATE) from exc


def amount_to_cents(value: str) -> int:
    """Convert an amount to integer cents using only integer arithmetic."""
    match = AMOUNT.fullmatch(value)
    if not match:
        raise _Rejected(content.REJ_BAD_AMOUNT)
    sign, whole, decimals = match.groups(default="")
    if len(decimals) > 2:
        raise _Rejected(content.REJ_DECIMALS)
    cents = int(whole) * 100 + int(decimals.ljust(2, "0"))
    return -cents if sign == "-" else cents
