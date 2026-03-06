#!/usr/bin/env python3
"""Stage 0 config and contract validation checks."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


class ValidationError(Exception):
    pass


def load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_schema(doc_path: Path, schema_path: Path) -> None:
    doc = load_yaml(doc_path)
    schema = load_json(schema_path)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: e.path)
    if errors:
        details = "; ".join([e.message for e in errors])
        raise ValidationError(f"Schema validation failed for {doc_path}: {details}")


def assert_unique(values: list[str], label: str) -> None:
    duplicates = sorted({v for v in values if values.count(v) > 1})
    if duplicates:
        raise ValidationError(f"Duplicate {label} found: {', '.join(duplicates)}")


def validate_universe() -> None:
    path = ROOT / "config/universe.yml"
    data = load_yaml(path)
    tickers = [item["ticker"] for item in data["tracked_companies"]]
    assert_unique(tickers, "tickers")


def validate_sources() -> None:
    path = ROOT / "config/sources.yml"
    data = load_yaml(path)
    source_ids = [item["source_id"] for item in data["sources"]]
    assert_unique(source_ids, "source_id values")


def validate_sentiment_sources() -> None:
    path = ROOT / "config/sentiment_sources.yml"
    data = load_yaml(path)
    source_ids = [item["source_id"] for item in data["sources"]]
    assert_unique(source_ids, "sentiment source_id values")


def validate_announcement_types() -> None:
    path = ROOT / "config/announcement_types.yml"
    data = load_yaml(path)
    types = set(data["announcement_types"])
    classifier_keys = set(data["classifier_keywords"].keys())

    if types != classifier_keys:
        missing = sorted(types - classifier_keys)
        extra = sorted(classifier_keys - types)
        raise ValidationError(
            "announcement type map mismatch: "
            f"missing keys={missing or 'none'}, extra keys={extra or 'none'}"
        )

    for key, terms in data["classifier_keywords"].items():
        if not isinstance(terms, list) or not terms:
            raise ValidationError(f"classifier keyword list must be non-empty for type: {key}")


def extract_task_contract_names(interface_doc: Path) -> set[str]:
    text = interface_doc.read_text(encoding="utf-8")
    return set(re.findall(r"`((?:agent_[a-z_]+\.[a-z_]+)|(?:ops\.[a-z_]+\.[a-z_]+))`", text))


def validate_schedule_to_task_contract() -> None:
    schedule_data = load_yaml(ROOT / "config/schedules.yml")
    tasks_in_schedule = [item["task_name"] for item in schedule_data["schedules"]]
    assert_unique([item["schedule_key"] for item in schedule_data["schedules"]], "schedule_key values")

    task_contracts = extract_task_contract_names(ROOT / "docs/canonical/INTERFACE_CONTRACT.md")
    if not task_contracts:
        raise ValidationError("No task contracts found in docs/canonical/INTERFACE_CONTRACT.md")

    unknown_tasks = sorted(set(tasks_in_schedule) - task_contracts)
    if unknown_tasks:
        raise ValidationError(
            "Schedule entries map to undefined task contracts: " + ", ".join(unknown_tasks)
        )


def main() -> int:
    try:
        validate_schema(ROOT / "config/universe.yml", ROOT / "config/schemas/universe.schema.json")
        validate_schema(ROOT / "config/sources.yml", ROOT / "config/schemas/sources.schema.json")
        validate_schema(ROOT / "config/sentiment_sources.yml", ROOT / "config/schemas/sentiment_sources.schema.json")
        validate_schema(ROOT / "config/schedules.yml", ROOT / "config/schemas/schedules.schema.json")

        validate_universe()
        validate_sources()
        validate_sentiment_sources()
        validate_announcement_types()
        validate_schedule_to_task_contract()

        print("Stage 0 config validation passed")
        return 0

    except ValidationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
