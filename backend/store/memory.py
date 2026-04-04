"""
In-memory store — seeds the same 6 articles visible in screens/overview/v1.html.
All state lives in module-level dicts; tests can reset via `reset()`.
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime, timezone

from backend.schemas.overview import (
    GateStatus,
    JobResponse,
    JobStatus,
    JobType,
    Platform,
    PlatformConnection,
    PlatformStatus,
    PlatformSummary,
    TimelineEvent,
)

# ─── helpers ──────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _ts(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def _dest(status: str, label: str, url: str | None = None, error: str | None = None) -> dict:
    return {
        "status": status,
        "label": label,
        "url": url,
        "error": error,
    }


def _seed_body(title: str) -> str:
    return (
        f"# {title}\n\n"
        f"This article is managed by BlogHub as canonical markdown source.\n\n"
        "## Overview\n\n"
        f"A working draft for {title}.\n"
    )


# ─── Seed data ────────────────────────────────────────────────────────────────

_SEED_ARTICLES: list[dict] = [
    {
        "id":
            "art_001",
        "title":
            "Building a Vector DB from Scratch with pgvector",
        "updated_at":
            _ts("2026-04-02T12:00:00+00:00"),
        "word_count":
            1820,
        "body":
            _seed_body("Building a Vector DB from Scratch with pgvector"),
        "gate":
            "pass",
        "destinations": {
            "medium": _dest("draft", "Draft v2"),
            "hashnode": _dest("pending", "Pending"),
            "devto": _dest("draft", "Draft v1"),
        },
        "recent_timeline": [
            {
                "timestamp": _ts("2026-04-02T14:02:00+00:00"),
                "event": "Draft pushed to Medium"
            },
            {
                "timestamp": _ts("2026-04-02T14:05:00+00:00"),
                "event": "Inspection passed (gate: pass)"
            },
            {
                "timestamp": _ts("2026-04-02T15:30:00+00:00"),
                "event": "Hashnode queued for 09:00 tomorrow"
            },
        ],
    },
    {
        "id":
            "art_002",
        "title":
            "RAG Pipeline with Neo4j and LangChain",
        "updated_at":
            _ts("2026-04-01T10:00:00+00:00"),
        "word_count":
            2100,
        "body":
            _seed_body("RAG Pipeline with Neo4j and LangChain"),
        "gate":
            "warn",
        "destinations": {
            "medium": _dest("review", "Needs review"),
            "hashnode": _dest("draft", "Draft v1"),
            "devto": _dest("error", "Error", error="code block split"),
        },
        "recent_timeline": [
            {
                "timestamp": _ts("2026-04-01T09:00:00+00:00"),
                "event": "Draft created (Medium, Hashnode)"
            },
            {
                "timestamp": _ts("2026-04-01T09:10:00+00:00"),
                "event": "Dev.to push failed — code block split"
            },
            {
                "timestamp": _ts("2026-04-01T09:15:00+00:00"),
                "event": "Inspection flagged: 2 issues"
            },
        ],
    },
    {
        "id":
            "art_003",
        "title":
            "Dockerised Postgres: Production Checklist",
        "updated_at":
            _ts("2026-03-30T08:00:00+00:00"),
        "word_count":
            1540,
        "body":
            _seed_body("Dockerised Postgres: Production Checklist"),
        "gate":
            "pass",
        "destinations": {
            "medium":
                _dest("published",
                      "Published",
                      url="https://medium.com/@acisse/dockerised-postgres"),
            "hashnode":
                _dest("published",
                      "Published",
                      url="https://acisse.hashnode.dev/dockerised-postgres"),
            "devto":
                _dest("published", "Published", url="https://dev.to/acisse/dockerised-postgres"),
        },
        "recent_timeline": [
            {
                "timestamp": _ts("2026-03-30T09:00:00+00:00"),
                "event": "Published to Medium"
            },
            {
                "timestamp": _ts("2026-03-30T09:05:00+00:00"),
                "event": "Published to Hashnode"
            },
            {
                "timestamp": _ts("2026-03-31T09:00:00+00:00"),
                "event": "Published to Dev.to"
            },
        ],
    },
    {
        "id":
            "art_004",
        "title":
            "Graph Neural Networks: A Practical Intro",
        "updated_at":
            _ts("2026-03-28T14:00:00+00:00"),
        "word_count":
            980,
        "body":
            _seed_body("Graph Neural Networks: A Practical Intro"),
        "gate":
            "pending",
        "destinations": {
            "medium": _dest("draft", "Draft v1"),
            "hashnode": _dest("none", "—"),
            "devto": _dest("none", "—"),
        },
        "recent_timeline": [
            {
                "timestamp": _ts("2026-03-28T14:00:00+00:00"),
                "event": "Article created"
            },
            {
                "timestamp": _ts("2026-03-28T14:10:00+00:00"),
                "event": "Draft pushed to Medium"
            },
        ],
    },
    {
        "id":
            "art_005",
        "title":
            "Zero-downtime Postgres Migrations",
        "updated_at":
            _ts("2026-03-25T11:00:00+00:00"),
        "word_count":
            2350,
        "body":
            _seed_body("Zero-downtime Postgres Migrations"),
        "gate":
            "pass",
        "destinations": {
            "medium": _dest("ready", "Ready"),
            "hashnode": _dest("ready", "Ready"),
            "devto": _dest("ready", "Ready"),
        },
        "recent_timeline": [
            {
                "timestamp": _ts("2026-03-25T10:00:00+00:00"),
                "event": "All drafts validated"
            },
            {
                "timestamp": _ts("2026-03-25T10:05:00+00:00"),
                "event": "Scheduled: Apr 4 09:00"
            },
        ],
    },
    {
        "id":
            "art_006",
        "title":
            "Embedding Models Compared: OpenAI vs Cohere vs BGE",
        "updated_at":
            _ts("2026-03-24T16:00:00+00:00"),
        "word_count":
            3100,
        "body":
            _seed_body("Embedding Models Compared: OpenAI vs Cohere vs BGE"),
        "gate":
            "fail",
        "destinations": {
            "medium": _dest("error", "Error", error="auth expired"),
            "hashnode": _dest("draft", "Draft v1"),
            "devto": _dest("none", "—"),
        },
        "recent_timeline": [
            {
                "timestamp": _ts("2026-03-24T15:00:00+00:00"),
                "event": "Medium push failed (auth expired)"
            },
            {
                "timestamp": _ts("2026-03-24T15:05:00+00:00"),
                "event": "Gate check: FAIL — missing tail section"
            },
        ],
    },
]

_SEED_PLATFORMS: list[dict] = [
    {
        "id": "medium",
        "connected": True,
        "label": "Medium",
        "username": "@acisse"
    },
    {
        "id": "hashnode",
        "connected": True,
        "label": "Hashnode",
        "username": "acisse.hashnode.dev"
    },
    {
        "id": "devto",
        "connected": True,
        "label": "Dev.to",
        "username": "acisse"
    },
]

# ─── Live state ───────────────────────────────────────────────────────────────

# Keyed by article id
_articles: dict[str, dict] = {a["id"]: deepcopy(a) for a in _SEED_ARTICLES}
_jobs: dict[str, dict] = {}
_platforms: list[dict] = deepcopy(_SEED_PLATFORMS)


def reset() -> None:
    """Reset to seed state — call from test fixtures."""
    global _articles, _jobs, _platforms
    _articles = {a["id"]: deepcopy(a) for a in _SEED_ARTICLES}
    _jobs = {}
    _platforms = deepcopy(_SEED_PLATFORMS)


# ─── Articles ─────────────────────────────────────────────────────────────────


def list_articles(
    q: str | None = None,
    gate: str | None = None,
    status: str | None = None,
    platform: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "updatedAt",
    sort_dir: str = "desc",
) -> tuple[list[dict], int]:
    items = list(_articles.values())

    if q:
        q_lower = q.lower()
        items = [a for a in items if q_lower in a["title"].lower()]

    if gate:
        items = [a for a in items if a["gate"] == gate]

    if status and platform:
        items = [a for a in items if a["destinations"].get(platform, {}).get("status") == status]
    elif status:
        items = [a for a in items if any(d["status"] == status for d in a["destinations"].values())]
    elif platform:
        items = [a for a in items if a["destinations"].get(platform, {}).get("status") != "none"]

    _SORT_KEY = {
        "updatedAt": lambda a: a["updated_at"],
        "createdAt": lambda a: a["updated_at"],  # no separate createdAt in seed
        "title": lambda a: a["title"].lower(),
    }
    key_fn = _SORT_KEY.get(sort_by, _SORT_KEY["updatedAt"])
    items.sort(key=key_fn, reverse=(sort_dir == "desc"))

    total = len(items)
    start = (page - 1) * page_size
    return items[start:start + page_size], total


def get_article(article_id: str) -> dict | None:
    return _articles.get(article_id)


def create_article(title: str) -> dict:
    article_id = f"art_{uuid.uuid4().hex[:8]}"
    now = _now()
    article = {
        "id": article_id,
        "title": title,
        "body": _seed_body(title),
        "updated_at": now,
        "word_count": len(title.split()) + 11,
        "gate": "pending",
        "destinations": {
            "medium": _dest("none", "—"),
            "hashnode": _dest("none", "—"),
            "devto": _dest("none", "—"),
        },
        "recent_timeline": [{
            "timestamp": now,
            "event": "Article created"
        },],
    }
    _articles[article_id] = article
    return article


def delete_articles(ids: list[str], force: bool = False) -> list[str]:
    """
    Returns list of ids that could NOT be deleted (published + force=False).
    Raises nothing — caller checks return value.
    """
    blocked = []
    for aid in ids:
        article = _articles.get(aid)
        if article is None:
            continue
        is_published = any(d["status"] == "published" for d in article["destinations"].values())
        if is_published and not force:
            blocked.append(aid)
        else:
            del _articles[aid]
    return blocked


def set_destinations_pending(article_id: str, platforms: list[str]) -> None:
    article = _articles[article_id]
    for p in platforms:
        if p in article["destinations"]:
            article["destinations"][p]["status"] = "pending"
    article["updated_at"] = _now()


def apply_push_result(article_id: str,
                      platform: str,
                      success: bool,
                      url: str | None = None,
                      error: str | None = None,
                      label: str | None = None,
                      draft_id: str | None = None) -> None:
    article = _articles[article_id]
    dest = article["destinations"][platform]
    if success:
        dest["status"] = "draft"
        dest["label"] = label or "Draft"
        dest["url"] = url
        dest["error"] = None
        if draft_id is not None:
            dest["draft_id"] = draft_id
        article["recent_timeline"].insert(0, {
            "timestamp": _now(),
            "event": f"Draft pushed to {platform.title()}"
        })
    else:
        dest["status"] = "error"
        dest["label"] = label or "Error"
        dest["error"] = error
        article["recent_timeline"].insert(0, {
            "timestamp": _now(),
            "event": f"{platform.title()} push failed — {error}"
        })
    # Keep only last 5 in recent_timeline
    article["recent_timeline"] = article["recent_timeline"][:5]
    article["updated_at"] = _now()


def apply_inspect_result(article_id: str, gate: str) -> None:
    article = _articles[article_id]
    article["gate"] = gate
    article["recent_timeline"].insert(0, {
        "timestamp": _now(),
        "event": f"Inspection completed (gate: {gate})"
    })
    article["recent_timeline"] = article["recent_timeline"][:5]
    article["updated_at"] = _now()


# ─── Jobs ─────────────────────────────────────────────────────────────────────


def create_job(job_type: str, article_id: str) -> dict:
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    job = {
        "job_id": job_id,
        "type": job_type,
        "status": "running",
        "article_id": article_id,
        "result": None,
        "error": None,
    }
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def complete_job(job_id: str, result: dict | None = None, error: str | None = None) -> None:
    job = _jobs[job_id]
    job["status"] = "error" if error else "done"
    job["result"] = result
    job["error"] = error


# ─── Platforms ────────────────────────────────────────────────────────────────


def list_platforms() -> list[dict]:
    return deepcopy(_platforms)


# ─── Connections (blog platforms + AI providers) ───────────────────────────────
# Connections survive reset() — they hold user secrets, not article state.

_CONNECTION_META: dict[str, dict] = {
    "medium": {
        "label": "Medium",
        "type": "blog",
        "auth": "oauth_or_token"
    },
    "hashnode": {
        "label": "Hashnode",
        "type": "blog",
        "auth": "token"
    },
    "devto": {
        "label": "Dev.to",
        "type": "blog",
        "auth": "token"
    },
    "anthropic": {
        "label": "Claude (Anthropic)",
        "type": "ai",
        "auth": "token"
    },
    "openai": {
        "label": "OpenAI",
        "type": "ai",
        "auth": "token"
    },
}

_connections: dict[str, dict] = {}


def list_connections() -> list[dict]:
    result = []
    for conn_id, meta in _CONNECTION_META.items():
        conn = _connections.get(conn_id, {})
        result.append({
            "id": conn_id,
            "label": meta["label"],
            "type": meta["type"],
            "auth_method": meta["auth"],
            "status": conn.get("status", "disconnected"),
            "username": conn.get("username"),
            "connected_at": conn.get("connected_at"),
            "error_message": conn.get("error_message"),
        })
    return result


def save_connection(
    conn_id: str,
    token: str,
    status: str = "connected",
    username: str | None = None,
    error: str | None = None,
) -> dict:
    if conn_id not in _CONNECTION_META:
        raise KeyError(f"Unknown connection: {conn_id}")
    _connections[conn_id] = {
        "token": token,
        "status": status,
        "username": username,
        "connected_at": _now(),
        "error_message": error,
    }
    meta = _CONNECTION_META[conn_id]
    return {
        "id": conn_id,
        "label": meta["label"],
        "type": meta["type"],
        "auth_method": meta["auth"],
        **_connections[conn_id],
    }


def delete_connection(conn_id: str) -> None:
    _connections.pop(conn_id, None)


def get_connection_token(conn_id: str) -> str | None:
    return _connections.get(conn_id, {}).get("token")


def count_connected() -> int:
    """Number of blog + AI connections currently marked connected."""
    return sum(1 for c in _connections.values() if c.get("status") == "connected")
