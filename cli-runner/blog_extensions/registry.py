"""Trusted manifest discovery and validation for browser blog extensions."""
from __future__ import annotations

from functools import lru_cache
import importlib
import os
from pathlib import Path
import re
import sys
import tomllib
from typing import Iterable

from .contracts import (
    PROTOCOL_VERSION,
    BlogExtension,
    BlogOperationsAdapter,
    BrowserLoginAdapter,
    Capability,
    ExtensionManifest,
)


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$")
_BUILTIN_MANIFESTS = Path(__file__).with_name("manifests")


class ExtensionConfigurationError(RuntimeError):
    pass


def _manifest_files(paths: Iterable[Path]) -> list[Path]:
    manifests: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved.is_file() and resolved.name == "bloghub_extension.toml":
            manifests.append(resolved)
        elif resolved.is_dir():
            direct = resolved / "bloghub_extension.toml"
            if direct.is_file():
                manifests.append(direct)
            manifests.extend(sorted(resolved.glob("*/bloghub_extension.toml")))
    return manifests


def _entrypoint(value: object, *, field: str, source: Path) -> tuple[str, str]:
    if not isinstance(value, str) or value.count(":") != 1:
        raise ExtensionConfigurationError(
            f"{source}: {field} must use module:Class syntax"
        )
    module_name, symbol_name = value.split(":", 1)
    if not module_name or not symbol_name:
        raise ExtensionConfigurationError(f"{source}: invalid {field}")
    return module_name, symbol_name


def _load_symbol(value: str, *, field: str, source: Path):
    module_name, symbol_name = _entrypoint(value, field=field, source=source)
    try:
        module = importlib.import_module(module_name)
        return getattr(module, symbol_name)
    except (ImportError, AttributeError) as exc:
        raise ExtensionConfigurationError(
            f"{source}: cannot load {field} {value}"
        ) from exc


def _parse_manifest(source: Path) -> ExtensionManifest:
    try:
        document = tomllib.loads(source.read_text(encoding="utf-8"))
        extension = document["extension"]
        entrypoints = document["entrypoints"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise ExtensionConfigurationError(f"Invalid extension manifest: {source}") from exc

    protocol_version = extension.get("protocol_version")
    if protocol_version != PROTOCOL_VERSION:
        raise ExtensionConfigurationError(
            f"{source}: protocol {protocol_version!r} is incompatible with {PROTOCOL_VERSION}"
        )

    extension_id = extension.get("id")
    platform = extension.get("platform")
    version = extension.get("version")
    display_name = extension.get("display_name")
    for label, value in (("id", extension_id), ("platform", platform)):
        if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
            raise ExtensionConfigurationError(f"{source}: invalid extension {label}")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ExtensionConfigurationError(f"{source}: version must be semantic")
    if not isinstance(display_name, str) or not display_name.strip():
        raise ExtensionConfigurationError(f"{source}: display_name is required")

    raw_capabilities = extension.get("capabilities", [])
    if not isinstance(raw_capabilities, list):
        raise ExtensionConfigurationError(f"{source}: capabilities must be a list")
    try:
        capabilities = frozenset(Capability(item) for item in raw_capabilities)
    except (TypeError, ValueError) as exc:
        raise ExtensionConfigurationError(f"{source}: unknown capability") from exc

    return ExtensionManifest(
        protocol_version=protocol_version,
        extension_id=extension_id,
        platform=platform,
        display_name=display_name.strip(),
        version=version,
        login_entrypoint=str(entrypoints.get("login", "")),
        operations_entrypoint=str(entrypoints.get("operations", "")),
        capabilities=capabilities,
        source=source,
    )


def _instantiate(manifest: ExtensionManifest) -> BlogExtension:
    login_type = _load_symbol(
        manifest.login_entrypoint, field="login entrypoint", source=manifest.source
    )
    operations_type = _load_symbol(
        manifest.operations_entrypoint,
        field="operations entrypoint",
        source=manifest.source,
    )
    login = login_type()
    operations = operations_type()
    if not isinstance(login, BrowserLoginAdapter):
        raise ExtensionConfigurationError(
            f"{manifest.source}: login adapter does not implement BrowserLoginAdapter"
        )
    if not isinstance(operations, BlogOperationsAdapter):
        raise ExtensionConfigurationError(
            f"{manifest.source}: operations adapter does not implement BlogOperationsAdapter"
        )
    if login.platform != manifest.platform or operations.platform != manifest.platform:
        raise ExtensionConfigurationError(
            f"{manifest.source}: adapter platform does not match manifest"
        )
    if operations.capabilities != manifest.capabilities:
        raise ExtensionConfigurationError(
            f"{manifest.source}: adapter capabilities do not match manifest"
        )
    if not login.login_url.startswith("https://"):
        raise ExtensionConfigurationError(
            f"{manifest.source}: login URL must use HTTPS"
        )
    return BlogExtension(manifest=manifest, login=login, operations=operations)


class ExtensionRegistry:
    def __init__(
        self,
        extension_paths: Iterable[Path] = (),
        enabled: set[str] | None = None,
    ) -> None:
        paths = [_BUILTIN_MANIFESTS, *extension_paths]
        self._extensions: dict[str, BlogExtension] = {}
        for source in _manifest_files(paths):
            # External modules are trusted administrator-installed code. Their
            # directory is added explicitly, never inferred from user input.
            module_root = source.parent
            if str(module_root) not in sys.path:
                sys.path.insert(0, str(module_root))
            manifest = _parse_manifest(source)
            if enabled is not None and not (
                manifest.extension_id in enabled or manifest.platform in enabled
            ):
                continue
            if manifest.platform in self._extensions:
                raise ExtensionConfigurationError(
                    f"Duplicate extension platform: {manifest.platform}"
                )
            self._extensions[manifest.platform] = _instantiate(manifest)

    def get(self, platform: str) -> BlogExtension:
        try:
            return self._extensions[platform]
        except KeyError as exc:
            raise KeyError(f"Unknown browser blog extension: {platform}") from exc

    def descriptors(self) -> list[dict]:
        return [
            extension.descriptor()
            for extension in sorted(
                self._extensions.values(), key=lambda item: item.manifest.platform
            )
        ]


def _configured_paths() -> list[Path]:
    value = os.environ.get("BLOGHUB_EXTENSION_PATHS", "")
    return [Path(item) for item in value.split(os.pathsep) if item]


def _enabled_extensions() -> set[str] | None:
    value = os.environ.get("BLOGHUB_ENABLED_EXTENSIONS")
    if value is None:
        return None
    return {item.strip() for item in value.split(",") if item.strip()}


@lru_cache(maxsize=1)
def get_registry() -> ExtensionRegistry:
    return ExtensionRegistry(_configured_paths(), _enabled_extensions())
