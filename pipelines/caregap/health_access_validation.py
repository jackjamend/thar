from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


HEALTH_ACCESS_FIELDS = [
    "record_id",
    "record_type",
    "entity_name",
    "state",
    "district",
    "city",
    "pincode",
    "latitude",
    "longitude",
    "facility_type",
    "operator_type",
    "phone",
    "website",
    "description",
    "office_type",
    "delivery",
    "households_surveyed",
    "institutional_birth_pct",
    "stunting_pct",
    "anaemia_pct",
    "improved_water_pct",
    "improved_sanitation_pct",
    "health_insurance_pct",
]

KNOWN_FACILITY_TYPES = {"", "hospital", "clinic", "dentist", "doctor", "pharmacy", "farmacy", "null"}
KNOWN_OPERATOR_TYPES = {"", "private", "public", "government", "null"}
KNOWN_RECORD_TYPES = {"facility", "pincode", "district"}
FACILITY_ID_RE = re.compile(r"^facility:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
JSONISH_RE = re.compile(r"^\s*[\[{]")
MARKDOWNISH_RE = re.compile(r"^\s*(?:[*#>-]|__|\*\*)")
FACILITY_KIND_RE = re.compile(
    r"\b(?:hospital|clinic|centre|center|nursing home|dental|dentist|diagnostic|labs?|pathology|medical|health care|healthcare)\b",
    re.IGNORECASE,
)


@dataclass
class ValidationIssue:
    rule: str
    severity: str
    line_number: int
    record_id: str
    entity_name: str
    message: str


@dataclass
class ValidationReport:
    total_rows: int = 0
    record_type_counts: dict[str, int] = field(default_factory=dict)
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    def issues_by_rule(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.rule] = counts.get(issue.rule, 0) + 1
        return counts


def read_health_access_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def validate_health_access_records(records: Iterable[dict[str, str]], *, first_data_line: int = 2) -> ValidationReport:
    report = ValidationReport()
    for offset, row in enumerate(records):
        line_number = first_data_line + offset
        report.total_rows += 1
        record_type = _clean(row.get("record_type"))
        report.record_type_counts[record_type or "<blank>"] = report.record_type_counts.get(record_type or "<blank>", 0) + 1

        if record_type not in KNOWN_RECORD_TYPES:
            _add_issue(report, "invalid_record_type", "error", line_number, row, f"Unexpected record_type {record_type!r}.")
            continue

        if record_type == "facility":
            _validate_facility_row(report, line_number, row)

    return report


def write_quarantine_csv(path: str | Path, records: Iterable[dict[str, str]], issues: Iterable[ValidationIssue]) -> None:
    rows_by_id = {_row_key(issue): issue for issue in issues if issue.severity == "error"}
    quarantined: list[dict[str, str]] = []
    for offset, row in enumerate(records):
        line_number = 2 + offset
        key = (line_number, row.get("record_id", ""))
        issue = rows_by_id.get(key)
        if not issue:
            continue
        quarantined.append(
            {
                **{field: row.get(field, "") for field in HEALTH_ACCESS_FIELDS},
                "validation_rule": issue.rule,
                "validation_message": issue.message,
                "source_line_number": str(line_number),
            }
        )

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [*HEALTH_ACCESS_FIELDS, "validation_rule", "validation_message", "source_line_number"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(quarantined)


def print_validation_report(report: ValidationReport, *, max_examples: int = 10) -> None:
    print("health_access_records validation")
    print(f"Total rows: {report.total_rows:,}")
    for record_type, count in sorted(report.record_type_counts.items()):
        print(f"- {record_type}: {count:,}")
    print(f"Errors: {report.error_count:,}")
    print(f"Warnings: {report.warning_count:,}")

    if report.issues:
        print("\nIssues by rule")
        for rule, count in sorted(report.issues_by_rule().items()):
            print(f"- {rule}: {count:,}")

    examples = report.issues[:max_examples]
    if examples:
        print("\nExamples")
        for issue in examples:
            print(
                "- "
                f"line {issue.line_number} [{issue.severity}/{issue.rule}] "
                f"{issue.record_id or '<blank id>'} "
                f"{issue.entity_name or '<blank name>'}: {issue.message}"
            )


def _validate_facility_row(report: ValidationReport, line_number: int, row: dict[str, str]) -> None:
    record_id = _clean(row.get("record_id"))
    entity_name = _clean(row.get("entity_name"))
    facility_type = _clean(row.get("facility_type")).lower()
    operator_type = _clean(row.get("operator_type")).lower()
    website = _clean(row.get("website"))
    description = _clean(row.get("description"))

    if not FACILITY_ID_RE.match(record_id):
        _add_issue(report, "malformed_facility_id", "error", line_number, row, "Facility record_id is not facility:<uuid>.")

    if not entity_name:
        _add_issue(report, "blank_facility_name", "error", line_number, row, "Facility row has no entity_name.")
    elif _looks_like_drift_value(entity_name) or MARKDOWNISH_RE.match(entity_name):
        _add_issue(report, "facility_name_column_drift", "error", line_number, row, "Facility entity_name looks like JSON, markdown, or shifted prose.")

    if facility_type not in KNOWN_FACILITY_TYPES or _looks_like_drift_value(row.get("facility_type")):
        _add_issue(report, "facility_type_column_drift", "error", line_number, row, "facility_type contains an unexpected or shifted value.")

    if operator_type not in KNOWN_OPERATOR_TYPES or _looks_like_drift_value(row.get("operator_type")):
        _add_issue(report, "operator_type_column_drift", "error", line_number, row, "operator_type contains an unexpected or shifted value.")

    if _looks_like_coordinate_object(row.get("phone")):
        _add_issue(report, "phone_column_drift", "error", line_number, row, "phone contains a coordinate object.")

    if _looks_like_drift_value(website) and not website.startswith("http"):
        _add_issue(report, "website_column_drift", "error", line_number, row, "website contains JSON, a UUID, a date, or another shifted scalar.")

    if _looks_like_description_drift(description):
        _add_issue(report, "description_column_drift", "error", line_number, row, "description contains a coordinate, UUID, date, boolean, or JSON value.")

    if description and len(description) < 40:
        _add_issue(report, "short_facility_description", "warning", line_number, row, "Facility description is shorter than 40 characters.")

    if description and entity_name and _looks_like_other_facility_description(entity_name, description):
        _add_issue(report, "possible_description_mismatch", "warning", line_number, row, "Description appears to name a different facility.")


def _looks_like_drift_value(value: str | None) -> bool:
    text = _clean(value)
    if not text:
        return False
    return bool(JSONISH_RE.match(text) or UUID_RE.match(text) or DATE_RE.match(text) or _looks_like_coordinate_object(text))


def _looks_like_description_drift(value: str | None) -> bool:
    text = _clean(value)
    if not text:
        return False
    if text.lower() in {"true", "false", "null"}:
        return True
    return bool(JSONISH_RE.match(text) or UUID_RE.match(text) or DATE_RE.match(text) or NUMBER_RE.match(text))


def _looks_like_coordinate_object(value: str | None) -> bool:
    text = _clean(value)
    return text.startswith('{"coordinates":') or text.startswith("{'coordinates':")


def _looks_like_other_facility_description(entity_name: str, description: str) -> bool:
    if not FACILITY_KIND_RE.search(description):
        return False
    name_tokens = _name_tokens(entity_name)
    description_tokens = _name_tokens(description[:180])
    if not name_tokens:
        return False
    overlap = name_tokens & description_tokens
    return len(overlap) == 0


def _name_tokens(value: str) -> set[str]:
    stopwords = {
        "and",
        "the",
        "of",
        "in",
        "at",
        "for",
        "near",
        "road",
        "west",
        "east",
        "north",
        "south",
        "clinic",
        "hospital",
        "medical",
        "health",
        "care",
        "centre",
        "center",
        "dental",
        "doctor",
        "dr",
    }
    tokens = {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2}
    return tokens - stopwords


def _add_issue(report: ValidationReport, rule: str, severity: str, line_number: int, row: dict[str, str], message: str) -> None:
    report.issues.append(
        ValidationIssue(
            rule=rule,
            severity=severity,
            line_number=line_number,
            record_id=_clean(row.get("record_id")),
            entity_name=_clean(row.get("entity_name")),
            message=message,
        )
    )


def _row_key(issue: ValidationIssue) -> tuple[int, str]:
    return (issue.line_number, issue.record_id)


def _clean(value: str | None) -> str:
    return (value or "").strip()
