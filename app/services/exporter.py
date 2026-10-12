from __future__ import annotations

import csv
import io
import json
from typing import Iterable

from ..schemas import ExtractedItem


_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _csv_safe(value: object) -> object:
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def flatten_result(result: dict[str, list[ExtractedItem]]) -> list[dict]:
    rows = []
    for category, items in result.items():
        for item in items:
            row = item.model_dump(mode="json")
            row["category"] = category
            row["location"] = item.location.label if item.location else "出处待核验"
            rows.append(row)
    return rows


def result_json(result: dict[str, list[ExtractedItem]]) -> str:
    return json.dumps({key: [item.model_dump(mode="json") for item in items] for key, items in result.items()}, ensure_ascii=False, indent=2)


def result_csv(result: dict[str, list[ExtractedItem]]) -> str:
    rows = flatten_result(result)
    fields = ["category", "title", "requirement", "evidence", "location", "severity", "confidence", "verified", "ambiguity", "time_type", "normalized_time"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows({key: _csv_safe(value) for key, value in row.items()} for row in rows)
    return output.getvalue()
