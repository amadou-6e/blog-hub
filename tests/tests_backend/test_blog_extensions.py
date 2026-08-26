from __future__ import annotations

import importlib
from pathlib import Path
import sys

import pytest


RUNNER = Path(__file__).resolve().parents[2] / "cli-runner"
if str(RUNNER) not in sys.path:
    sys.path.insert(0, str(RUNNER))

from blog_extensions import (
    Capability,
    ExtensionRegistry,
    OperationNotSupported,
    OperationRequest,
)
from blog_extensions.registry import ExtensionConfigurationError
from blog_extensions.testing import assert_extension_contract, article_from_fixture


FIXTURE = Path(__file__).with_name("fixtures") / "blog_extension_article.json"


def test_builtin_extensions_satisfy_the_versioned_contract():
    registry = ExtensionRegistry()

    hashnode = registry.get("hashnode")
    medium = registry.get("medium")
    assert_extension_contract(hashnode)
    assert_extension_contract(medium)

    assert hashnode.manifest.capabilities == frozenset({
        Capability.LIST_ARTICLES, Capability.CREATE_DRAFT, Capability.PUBLISH,
    })
    assert medium.manifest.capabilities == frozenset({
        Capability.LIST_ARTICLES, Capability.GET_ARTICLE,
        Capability.CREATE_DRAFT, Capability.UPDATE_ARTICLE, Capability.PUBLISH,
    })
    assert [item["platform"] for item in registry.descriptors()] == [
        "hashnode", "medium",
    ]


def test_fixture_loader_builds_normalized_article_input():
    article = article_from_fixture(FIXTURE)

    assert article.title == "A fixture-backed extension article"
    assert article.tags == ("bloghub", "extensions")
    assert article.metadata == {"language": "en"}


def test_medium_update_requires_a_remote_id():
    extension = ExtensionRegistry().get("medium")

    with pytest.raises(ValueError, match="requires a remote_id"):
        extension.operations.execute(
            object(),
            Capability.UPDATE_ARTICLE,
            OperationRequest(article=article_from_fixture(FIXTURE)),
        )


def test_external_extension_is_loaded_from_an_admin_path(tmp_path, monkeypatch):
    module_name = "fixture_blog_extension"
    (tmp_path / f"{module_name}.py").write_text(
        """
from blog_extensions import BrowserLoginAdapter, BlogOperationsAdapter, Capability
class Login(BrowserLoginAdapter):
    platform = 'fixture-blog'
    login_url = 'https://example.com/login'
    def verify_profile(self, profile_dir):
        return {'authenticated': True, 'status': 'connected'}
class Operations(BlogOperationsAdapter):
    platform = 'fixture-blog'
    capabilities = frozenset({Capability.GET_ARTICLE})
    def execute(self, page, operation, article=None):
        return {'success': True, 'remote_id': 'fixture'}
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "bloghub_extension.toml").write_text(
        f"""
[extension]
protocol_version = 1
id = "fixture.blog"
platform = "fixture-blog"
display_name = "Fixture Blog"
version = "1.2.3"
capabilities = ["get_article"]
[entrypoints]
login = "{module_name}:Login"
operations = "{module_name}:Operations"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    importlib.invalidate_caches()

    registry = ExtensionRegistry([tmp_path], enabled={"fixture.blog"})

    assert registry.get("fixture-blog").manifest.version == "1.2.3"


def test_incompatible_protocol_is_rejected(tmp_path):
    (tmp_path / "bloghub_extension.toml").write_text(
        """
[extension]
protocol_version = 99
id = "fixture.bad"
platform = "fixture-bad"
display_name = "Bad Fixture"
version = "1.0.0"
capabilities = []
[entrypoints]
login = "missing:Login"
operations = "missing:Operations"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ExtensionConfigurationError, match="incompatible"):
        ExtensionRegistry([tmp_path])
