"""
Layer B — TS contracts/*.ts  ↔  Spec swagger.yaml

Each TS interface/type/enum is mapped to the corresponding spec schema and
the field names are compared as sets. Type compatibility is not checked here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]  # blog-hub/
SPEC_DIR = ROOT / ".spec" / "backend"
CONTRACTS_DIR = ROOT / "contracts"


def _resolve_spec_schemas(swagger: dict) -> dict[str, dict]:
    return swagger.get("components", {}).get("schemas", {}) or {}


def _load_swagger_files() -> list[tuple[str, dict]]:
    results = []
    for path in sorted(SPEC_DIR.rglob("swagger.yaml")):
        service = path.parent.name
        with path.open(encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        results.append((service, doc))
    return results


def _extract_ts_fields(ts_source: str) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}

    for m in re.finditer(
            r"export\s+interface\s+(\w+)\s*(?:extends\s+\w+\s*)?\{([^}]*)\}",
            ts_source,
            re.DOTALL,
    ):
        name = m.group(1)
        body = m.group(2)
        fields = {
            line.strip().rstrip(";").split(":")[0].strip().rstrip("?")
            for line in body.splitlines()
            if line.strip() and not line.strip().startswith("//") and ":" in line
        }
        result[name] = fields

    for m in re.finditer(
            r"export\s+type\s+(\w+)\s*=\s*([^;]+);",
            ts_source,
            re.DOTALL,
    ):
        name = m.group(1)
        body = m.group(2)
        members = re.findall(r"'([^']+)'", body)
        if members:
            result[f"type:{name}"] = set(members)

    return result


class TestLayerB:
    """TypeScript contract fields must match spec swagger schema properties."""

    _ALIAS: dict[str, str] = {
        "ArticleListResponse": "ArticleListResponse",
        "ArticleSummary": "ArticleSummary",
        "PlatformSummary": "PlatformSummary",
        "TimelineEvent": "TimelineEvent",
    }

    @pytest.fixture(scope="class")
    def ts_interfaces(self) -> dict[str, set[str]]:
        all_fields: dict[str, set[str]] = {}
        for ts_file in CONTRACTS_DIR.glob("*.ts"):
            all_fields.update(_extract_ts_fields(ts_file.read_text(encoding="utf-8")))
        return all_fields

    @pytest.fixture(scope="class")
    def spec_schemas(self) -> dict[str, dict]:
        merged: dict[str, dict] = {}
        for _, swagger in _load_swagger_files():
            merged.update(_resolve_spec_schemas(swagger))
        return merged

    def test_ts_interfaces_have_all_spec_required_fields(self, ts_interfaces, spec_schemas):
        errors = []
        for ts_name, ts_fields in ts_interfaces.items():
            if ts_name.startswith("type:"):
                continue
            schema_name = self._ALIAS.get(ts_name, ts_name)
            if schema_name not in spec_schemas:
                continue
            spec_req = set(spec_schemas[schema_name].get("required", []))
            missing = spec_req - ts_fields
            if missing:
                errors.append(f"[{ts_name}] required in spec but missing from TS: {missing}")
        assert not errors, "\n".join(errors)

    def test_ts_fields_exist_in_spec(self, ts_interfaces, spec_schemas):
        errors = []
        for ts_name, ts_fields in ts_interfaces.items():
            if ts_name.startswith("type:"):
                continue
            schema_name = self._ALIAS.get(ts_name, ts_name)
            if schema_name not in spec_schemas:
                continue
            spec_props = set(spec_schemas[schema_name].get("properties", {}).keys())
            extra = ts_fields - spec_props
            if extra:
                errors.append(f"[{ts_name}] in TS but not in spec: {extra}")
        assert not errors, "\n".join(errors)

    def test_ts_enum_values_match_spec(self, ts_interfaces, spec_schemas):
        errors = []
        for ts_key, ts_values in ts_interfaces.items():
            if not ts_key.startswith("type:"):
                continue
            ts_name = ts_key[len("type:"):]
            if ts_name not in spec_schemas:
                continue
            spec_enum = set(spec_schemas[ts_name].get("enum", []))
            if not spec_enum:
                continue
            missing = spec_enum - ts_values
            extra = ts_values - spec_enum
            if missing or extra:
                errors.append(f"[{ts_name}] enum mismatch — "
                              f"missing from TS: {missing}, extra in TS: {extra}")
        assert not errors, "\n".join(errors)
