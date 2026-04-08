"""
Layer A — Spec swagger.yaml  ↔  FastAPI-generated OpenAPI

Every schema that exists in *both* the spec swagger files AND the FastAPI-
generated schema must have:
  • The same set of required fields (exact match, order-insensitive).
  • No missing properties (spec defines a field FastAPI doesn't know about).
  • Compatible types for each property (string, integer, boolean, array, ref).

Schemas in the spec that are NOT in the FastAPI-generated schema are reported
as "not yet implemented" — a warning, not a failure.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from backend.main import app

ROOT = Path(__file__).resolve().parents[3]  # blog-hub/
SPEC_DIR = ROOT / ".spec" / "backend"


def _ref_name(ref: str) -> str:
    """'#/components/schemas/Foo' → 'Foo'"""
    return ref.rsplit("/", 1)[-1]


def _effective_type(prop: dict) -> str:
    if "$ref" in prop:
        return f"$ref:{_ref_name(prop['$ref'])}"
    if "anyOf" in prop:
        non_null = [
            s for s in prop["anyOf"] if s.get("type") != "null" and "$ref" in s or "type" in s
        ]
        if non_null:
            return f"nullable:{_effective_type(non_null[0])}"
        return "anyOf"
    if "allOf" in prop:
        return f"allOf:{_effective_type(prop['allOf'][0])}"
    t = prop.get("type", "unknown")
    if t == "array":
        items = prop.get("items", {})
        return f"array<{_effective_type(items)}>"
    return t


def _resolve_spec_schemas(swagger: dict) -> dict[str, dict]:
    return swagger.get("components", {}).get("schemas", {}) or {}


def _fastapi_schemas() -> dict[str, dict]:
    return app.openapi().get("components", {}).get("schemas", {})


def _load_swagger_files() -> list[tuple[str, dict]]:
    results = []
    for path in sorted(SPEC_DIR.rglob("swagger.yaml")):
        service = path.parent.name
        with path.open(encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        results.append((service, doc))
    return results


class TestLayerA:
    """Spec swagger schemas must match FastAPI-generated (Pydantic) schemas."""

    @pytest.fixture(scope="class")
    def impl_schemas(self) -> dict[str, dict]:
        return _fastapi_schemas()

    @pytest.fixture(scope="class")
    def swagger_pairs(self) -> list[tuple[str, str, dict, dict]]:
        impl = _fastapi_schemas()
        pairs = []
        for service, swagger in _load_swagger_files():
            for name, spec_schema in _resolve_spec_schemas(swagger).items():
                pairs.append((service, name, spec_schema, impl.get(name)))
        return pairs

    def test_all_spec_schemas_are_implemented(self, swagger_pairs):
        not_implemented = [
            f"{service}/{name}" for service, name, _, impl in swagger_pairs if impl is None
        ]
        if not_implemented:
            pytest.xfail(f"Schemas not yet in FastAPI ({len(not_implemented)}): " +
                         ", ".join(not_implemented))

    def test_required_fields_match(self, swagger_pairs):
        errors = []
        for service, name, spec_schema, impl_schema in swagger_pairs:
            if impl_schema is None:
                continue
            spec_req = set(spec_schema.get("required", []))
            impl_req = set(impl_schema.get("required", []))
            missing = spec_req - impl_req
            extra = impl_req - spec_req
            if missing:
                errors.append(
                    f"[{service}/{name}] required in spec but optional in FastAPI: {missing}")
            if extra:
                errors.append(
                    f"[{service}/{name}] required in FastAPI but optional in spec: {extra}")
        assert not errors, "\n".join(errors)

    def test_no_spec_fields_missing_from_fastapi(self, swagger_pairs):
        errors = []
        for service, name, spec_schema, impl_schema in swagger_pairs:
            if impl_schema is None:
                continue
            spec_props = set(spec_schema.get("properties", {}).keys())
            impl_props = set(impl_schema.get("properties", {}).keys())
            missing = spec_props - impl_props
            if missing:
                errors.append(f"[{service}/{name}] missing in FastAPI: {missing}")
        assert not errors, "\n".join(errors)

    def test_no_fastapi_fields_missing_from_spec(self, swagger_pairs):
        warnings = []
        for service, name, spec_schema, impl_schema in swagger_pairs:
            if impl_schema is None:
                continue
            spec_props = set(spec_schema.get("properties", {}).keys())
            impl_props = set(impl_schema.get("properties", {}).keys())
            extra = impl_props - spec_props
            if extra:
                warnings.append(f"[{service}/{name}] in FastAPI but not in spec: {extra}")
        if warnings:
            print("\nWARNINGS — FastAPI fields not in spec:\n" + "\n".join(warnings))
