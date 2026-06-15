from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from caregap.health_access_validation import (
    print_validation_report,
    read_health_access_csv,
    validate_health_access_records,
    write_quarantine_csv,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a health_access_records CSV before CareGap extraction.")
    parser.add_argument("--input", required=True, help="CSV export of public.health_access_records.")
    parser.add_argument("--max-examples", type=int, default=12, help="Maximum validation examples to print.")
    parser.add_argument("--quarantine-output", help="Optional CSV path for rows with blocking validation errors.")
    parser.add_argument("--warnings-fail", action="store_true", help="Exit non-zero when warnings are present.")
    args = parser.parse_args()

    records = read_health_access_csv(args.input)
    report = validate_health_access_records(records)
    print_validation_report(report, max_examples=args.max_examples)

    if args.quarantine_output:
        write_quarantine_csv(args.quarantine_output, records, report.issues)
        print(f"\nWrote quarantine rows to {args.quarantine_output}")

    if report.error_count or (args.warnings_fail and report.warning_count):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
