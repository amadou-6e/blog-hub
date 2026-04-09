"""
Test configuration for blog-hub/blogs/medium tests.

Sets up:
  - sys.path so ``blogs.*`` and ``backend.*`` can be imported from blog-hub root
  - Shared fixtures: reset_store, client, all_articles
"""
from __future__ import annotations

import os
import sys

# --- Path setup -----------------------------------------------------------

# blog-hub root (parent of this file's great-grandparent: blogs/medium/tests/)
_blogs_medium_tests = os.path.dirname(os.path.abspath(__file__))  # tests/
_blogs_medium = os.path.dirname(_blogs_medium_tests)  # medium/
_blogs = os.path.dirname(_blogs_medium)  # blogs/
_blog_hub_root = os.path.dirname(_blogs)  # blog-hub/

if _blog_hub_root not in sys.path:
    sys.path.insert(0, _blog_hub_root)

# --- Fixtures -------------------------------------------------------------

import pytest
from fastapi.testclient import TestClient
from backend.main import app
import backend.store.memory as store


@pytest.fixture(autouse=True)
def reset_store():
    """Reset in-memory store before and after every test."""
    store.reset()
    yield
    store.reset()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def all_articles():
    """Return all seed articles (list of dicts)."""
    items, _ = store.list_articles()
    return items
