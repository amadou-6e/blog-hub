"""Test configuration for Hashnode blog integration tests."""

from __future__ import annotations

import os
import sys


_test_dir = os.path.dirname(os.path.abspath(__file__))
_hashnode_dir = os.path.dirname(_test_dir)
_blogs_dir = os.path.dirname(_hashnode_dir)
_blog_hub_root = os.path.dirname(_blogs_dir)

if _blog_hub_root not in sys.path:
    sys.path.insert(0, _blog_hub_root)

import pytest
from fastapi.testclient import TestClient

from backend.main import app
import backend.store as store


@pytest.fixture(autouse=True)
def reset_store():
    store.reset()
    yield
    store.reset()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def all_articles():
    items, _ = store.list_articles()
    return items
