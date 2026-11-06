"""Command line: run the whole analysis and return the exit code of rule.exit_codes."""

import argparse
import io
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from . import checks, content
from .excel_writer import WorkbookError, write_workbook
from .validation import LedgerError, read_ledger

RESULTS_NAME = "results.xlsx"
DEFAULT_OUT_DIR = "out"
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_BAD_LEDGER = 2
# Explicit [0-9]: int() also accepts 1_000 and non-ASCII digits.
DIGITS = re.compile(r"[0-9]+")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        self.exit(EXIT_ERROR, content.ERR_USAGE + "\n")


def _positive_integer(value: str) -> int:
    if not DIGITS.fullmatch(value) or int(value) == 0:
        raise ValueError(value)
    return int(value)


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="journal-entry-tests", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser(
        "analyze",
        help=content.HELP_ANALYZE,
        description=content.HELP_ANALYZE,
        allow_abbrev=False,
    )
    analyze.add_argument("ledger", metavar="LEDGER")
    analyze.add_argument("--out-dir", metavar="DIR", default=DEFAULT_OUT_DIR)
    analyze.add_argument(
        "--round-base", metavar="N", type=_positive_integer, default=checks.DEFAULT_ROUND_BASE
    )
    analyze.add_argument("--holidays", metavar="FILE")
    analyze.add_argument(
        "--benford-min-rows",
        metavar="N",
        type=_positive_integer,
        default=checks.DEFAULT_BENFORD_MIN_ROWS,
    )
    analyze.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # stderr already uses this handler by default. A path the console cannot encode must not
    # crash a run that has finished.
    # A process with no console has no stdout, and callers can redirect it to other streams.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(errors="backslashreplace")
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code
    return _analyze(args)


def _analyze(args: argparse.Namespace) -> int:
    """Each step follows the order of rule.exit_codes, so the first error that applies wins."""
    # os.path.exists, because Path.exists raises PermissionError on Python 3.11.
    for path in (args.ledger, args.holidays):
        if path is not None and not os.path.exists(path):
            return _fail(content.ERR_MISSING_FILE.format(path=path))

    out_dir = Path(args.out_dir)
    results = out_dir / RESULTS_NAME
    if not args.overwrite and os.path.exists(results):
        return _fail(content.ERR_EXISTS.format(path=results))
    try:
        _check_writable(out_dir)
    except OSError:
        return _fail(content.ERR_OUT_DIR.format(path=out_dir))

    holidays = frozenset()
    if args.holidays is not None:
        try:
            holidays = checks.read_holidays(args.holidays)
        except checks.HolidaysError as exc:
            return _fail(str(exc))
        except OSError:
            return _fail(content.ERR_MISSING_FILE.format(path=args.holidays))

    try:
        valid, rejected = read_ledger(args.ledger)
    except FileNotFoundError:
        return _fail(content.ERR_MISSING_FILE.format(path=args.ledger))
    except LedgerError as exc:
        return _fail(str(exc), EXIT_BAD_LEDGER)

    benford_alerts, benford = checks.check_benford(valid, args.benford_min_rows)
    alerts = checks.aggregate(
        checks.check_duplicates(valid),
        checks.check_round(valid, args.round_base),
        checks.check_weekend(valid, holidays),
        checks.check_gaps(valid),
        benford_alerts,
    )
    try:
        write_workbook(results, alerts, benford, rejected)
    except WorkbookError as exc:
        return _fail(str(exc))

    if valid.empty:
        print(content.MSG_EMPTY.format(path=results))
    else:
        print(content.MSG_DONE.format(alerts=len(alerts), rejected=len(rejected), path=results))
    return EXIT_OK


def _check_writable(out_dir: Path) -> None:
    """Create the folder and a file in it. Raises OSError if either fails.

    Not os.access, which ignores permissions on Windows. Not tempfile either: on Python 3.11 on
    Windows it retries a PermissionError about 2 billion times, so a blocked folder would hang.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    probe = out_dir / f"{RESULTS_NAME}.{os.getpid()}.tmp"
    probe.touch()
    probe.unlink()


def _fail(message: str, code: int = EXIT_ERROR) -> int:
    print(message, file=sys.stderr)
    return code
