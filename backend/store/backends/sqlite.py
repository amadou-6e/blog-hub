"""
SQLiteStore — durable implementation of the ArticleStore Protocol.

All state persists in a single SQLite file (WAL mode).
BLOGHUB_DB_PATH env var overrides the default path; use ':memory:' for tests.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.store.backups import (
    BackupError,
    create_backup as create_verified_backup,
    create_backup_if_due as create_verified_backup_if_due,
)
from backend.store.crypto import (
    CredentialDecryptionError,
    decrypt_token,
    encrypt_token,
    needs_reencryption,
)
from backend.store.locking import WorkspaceLock
from backend.store.agent_sessions import AgentSessionStoreMixin
from backend.store.job_queue import DurableJobStoreMixin
from backend.store.article_revisions import ArticleRevisionStoreMixin
from backend.store.connection_auth import ConnectionAuthStoreMixin
from backend.store.browser_publish import BrowserPublishStoreMixin
from backend.store.browser_connections import BrowserConnectionStoreMixin
from backend.store.remote_articles import RemoteArticleStoreMixin
from backend.store.reconciliation import ReconciliationStoreMixin
from backend.store.schema import (
    SEED_USER_EMAIL as DEFAULT_SEED_USER_EMAIL,
    SEED_USER_HASH as DEFAULT_SEED_USER_HASH,
    SEED_USER_ID as DEFAULT_SEED_USER_ID,
    apply_schema,
)

logger = logging.getLogger(__name__)

# ─── Static metadata ──────────────────────────────────────────────────────────

_PLATFORMS = ["medium", "hashnode", "devto"]

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

_PLATFORM_META: list[dict] = [
    {
        "id": "medium",
        "label": "Medium",
        "username": "@acisse"
    },
    {
        "id": "hashnode",
        "label": "Hashnode",
        "username": "acisse.hashnode.dev"
    },
    {
        "id": "devto",
        "label": "Dev.to",
        "username": "acisse"
    },
]

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _ts(dt: datetime) -> str:
    return dt.isoformat()


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _seed_body(title: str) -> str:
    return (f"# {title}\n\n"
            "This article is managed by BlogHub as canonical markdown source.\n\n"
            "## Overview\n\n"
            f"A working draft for {title}.\n")


# ─── Seed data ────────────────────────────────────────────────────────────────


def _seed_articles() -> list[dict]:
    """Return the 6 canonical seed articles as insertion-ready dicts."""

    def a(id_, title, updated, wc, gate, dests, timeline):
        now_s = updated
        return {
            "id": id_,
            "title": title,
            "body": _seed_body(title),
            "word_count": wc,
            "gate": gate,
            "source": "native",
            "source_platform": None,
            "canonical_url": None,
            "created_at": now_s,
            "updated_at": now_s,
            "destinations": dests,
            "timeline": timeline,
        }

    def d(status, label, url=None, error=None, draft_id=None):
        return {"status": status, "label": label, "url": url, "error": error, "draft_id": draft_id}

    def e(ts, event):
        return {"timestamp": ts, "event": event}

    return [
        a(
            "art_001", "Building a Vector DB from Scratch with pgvector",
            "2026-04-02T12:00:00+00:00", 1820, "pass", {
                "medium": d("draft", "Draft v2"),
                "hashnode": d("pending", "Pending"),
                "devto": d("draft", "Draft v1")
            }, [
                e("2026-04-02T14:02:00+00:00", "Draft pushed to Medium"),
                e("2026-04-02T14:05:00+00:00", "Inspection passed (gate: pass)"),
                e("2026-04-02T15:30:00+00:00", "Hashnode queued for 09:00 tomorrow")
            ]),
        a(
            "art_002", "RAG Pipeline with Neo4j and LangChain", "2026-04-01T10:00:00+00:00", 2100,
            "warn", {
                "medium": d("review", "Needs review"),
                "hashnode": d("draft", "Draft v1"),
                "devto": d("error", "Error", error="code block split")
            }, [
                e("2026-04-01T09:00:00+00:00", "Draft created (Medium, Hashnode)"),
                e("2026-04-01T09:10:00+00:00", "Dev.to push failed — code block split"),
                e("2026-04-01T09:15:00+00:00", "Inspection flagged: 2 issues")
            ]),
        a(
            "art_003", "Dockerised Postgres: Production Checklist", "2026-03-30T08:00:00+00:00",
            1540, "pass", {
                "medium":
                    d("published",
                      "Published",
                      url="https://medium.com/@acisse/dockerised-postgres"),
                "hashnode":
                    d("published",
                      "Published",
                      url="https://acisse.hashnode.dev/dockerised-postgres"),
                "devto":
                    d("published", "Published", url="https://dev.to/acisse/dockerised-postgres")
            }, [
                e("2026-03-30T09:00:00+00:00", "Published to Medium"),
                e("2026-03-30T09:05:00+00:00", "Published to Hashnode"),
                e("2026-03-31T09:00:00+00:00", "Published to Dev.to")
            ]),
        a("art_004", "Graph Neural Networks: A Practical Intro", "2026-03-28T14:00:00+00:00", 980,
          "pending", {
              "medium": d("draft", "Draft v1"),
              "hashnode": d("none", "—"),
              "devto": d("none", "—")
          }, [
              e("2026-03-28T14:00:00+00:00", "Article created"),
              e("2026-03-28T14:10:00+00:00", "Draft pushed to Medium")
          ]),
        a(
            "art_005", "Zero-downtime Postgres Migrations", "2026-03-25T11:00:00+00:00", 2350,
            "pass", {
                "medium": d("ready", "Ready"),
                "hashnode": d("ready", "Ready"),
                "devto": d("ready", "Ready")
            }, [
                e("2026-03-25T10:00:00+00:00", "All drafts validated"),
                e("2026-03-25T10:05:00+00:00", "Scheduled: Apr 4 09:00")
            ]),
        a(
            "art_006", "Embedding Models Compared: OpenAI vs Cohere vs BGE",
            "2026-03-24T16:00:00+00:00", 3100, "fail", {
                "medium": d("error", "Error", error="auth expired"),
                "hashnode": d("draft", "Draft v1"),
                "devto": d("none", "—")
            }, [
                e("2026-03-24T15:00:00+00:00", "Medium push failed (auth expired)"),
                e("2026-03-24T15:05:00+00:00", "Gate check: FAIL — missing tail section")
            ]),
    ]


# ─── SQLiteStore ──────────────────────────────────────────────────────────────


class SQLiteStore(
    DurableJobStoreMixin,
    ReconciliationStoreMixin,
    RemoteArticleStoreMixin,
    BrowserConnectionStoreMixin,
    BrowserPublishStoreMixin,
    ConnectionAuthStoreMixin,
    AgentSessionStoreMixin,
    ArticleRevisionStoreMixin,
):

    def __init__(self, db_path: str, blobs_dir: str = "data/blobs") -> None:
        self._db_path = db_path
        self._blobs_dir = Path(blobs_dir).resolve()
        self._blobs_dir.mkdir(parents=True, exist_ok=True)
        self._workspace_lock = WorkspaceLock(
            self._blobs_dir.parent
            / f".{self._blobs_dir.name}.bloghub-workspace.lock"
        )
        if db_path != ":memory:":
            Path(db_path).resolve().parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(db_path, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA foreign_keys=ON")
        with self._workspace_lock.acquire():
            apply_schema(self._con)
            self.reencrypt_connection_credentials()
            self.reencrypt_browser_connection_credentials()
            self._seed_if_empty()
            self._ensure_initial_article_revisions()
            self._ensure_patch_revision_links()
        # Ephemeral — no need to persist across restarts
        self._oauth_pending: dict[str, dict] = {}

    # ── Seed ─────────────────────────────────────────────────────────────────

    # Known seed credentials — used by tests to log in without re-registering.
    SEED_USER_ID = DEFAULT_SEED_USER_ID
    SEED_USER_EMAIL = DEFAULT_SEED_USER_EMAIL
    SEED_USER_HASH = DEFAULT_SEED_USER_HASH

    def _seed_if_empty(self) -> None:
        # Always ensure the seed user exists (safe with INSERT OR IGNORE).
        now_s = _ts(_now())
        self._con.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, created_at) VALUES (?,?,?,?)",
            (self.SEED_USER_ID, self.SEED_USER_EMAIL, self.SEED_USER_HASH, now_s),
        )
        count = self._con.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        if count > 0:
            self._con.commit()
            return
        for art in _seed_articles():
            self._insert_article(art, user_id=self.SEED_USER_ID)
        self._con.commit()

    def _insert_article(self, art: dict, user_id: str | None = None) -> None:
        body_path = self._write_body(art["id"], art["body"])
        self._con.execute(
            """INSERT OR IGNORE INTO articles
               (id, title, body, body_path, word_count, gate, source, source_platform,
                canonical_url, created_at, updated_at, user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (art["id"], art["title"], "", body_path,
             art["word_count"], art["gate"], art["source"], art["source_platform"],
             art.get("canonical_url"), art["created_at"], art["updated_at"], user_id),
        )
        for platform, dest in art["destinations"].items():
            self._con.execute(
                """INSERT OR IGNORE INTO article_destinations
                   (article_id, platform, status, label, url, draft_id, error)
                   VALUES (?,?,?,?,?,?,?)""",
                (art["id"], platform, dest["status"], dest["label"], dest.get("url"),
                 dest.get("draft_id"), dest.get("error")),
            )
        for entry in art.get("timeline", []):
            self._con.execute(
                "INSERT INTO article_timeline (article_id, timestamp, event) VALUES (?,?,?)",
                (art["id"], entry["timestamp"], entry["event"]),
            )

    # ── Blob helpers ─────────────────────────────────────────────────────────

    def _body_path_for(self, article_id: str) -> Path:
        return self._blobs_dir / "articles" / article_id / "body.md"

    def _write_body(self, article_id: str, body: str) -> str:
        """Write body to disk. Returns the path relative to blobs_dir."""
        p = self._body_path_for(article_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        (p.parent / "assets").mkdir(exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return str(p.relative_to(self._blobs_dir))

    def _read_body(self, row: sqlite3.Row) -> str:
        """Read body from disk if body_path set, else fall back to body column."""
        body_path = row["body_path"]
        if body_path:
            full = self._blobs_dir / body_path
            if full.exists():
                return full.read_text(encoding="utf-8")
        return row["body"]

    def _local_preview_image_url(self, article_id: str) -> str | None:
        row = self._con.execute(
            """SELECT rai.cover_asset_id
               FROM remote_article_identities rai
               JOIN article_assets aa
                 ON aa.id=rai.cover_asset_id AND aa.article_id=rai.article_id
               WHERE rai.article_id=? AND rai.cover_asset_id IS NOT NULL
               ORDER BY rai.updated_at DESC, rai.platform, rai.remote_id
               LIMIT 1""",
            (article_id,),
        ).fetchone()
        if row is None:
            return None
        return f"/api/articles/{article_id}/assets/{row['cover_asset_id']}"

    # ── Article assembly ─────────────────────────────────────────────────────

    def _load_article(self, row: sqlite3.Row) -> dict:
        aid = row["id"]
        dest_rows = self._con.execute(
            "SELECT platform, status, label, url, draft_id, error "
            "FROM article_destinations WHERE article_id=?", (aid,)).fetchall()
        tl_rows = self._con.execute(
            "SELECT timestamp, event FROM article_timeline "
            "WHERE article_id=? ORDER BY id DESC LIMIT 5", (aid,)).fetchall()
        destinations = {
            p: {
                "status": "none",
                "label": "—",
                "url": None,
                "error": None,
                "draft_id": None
            } for p in _PLATFORMS
        }
        for dr in dest_rows:
            destinations[dr["platform"]] = {
                "status": dr["status"],
                "label": dr["label"],
                "url": dr["url"],
                "draft_id": dr["draft_id"],
                "error": dr["error"],
            }
        return {
            "id":
                row["id"],
            "title":
                row["title"],
            "body":
                self._read_body(row),
            "word_count":
                row["word_count"],
            "gate":
                row["gate"],
            "source":
                row["source"],
            "source_platform":
                row["source_platform"],
            "canonical_url":
                row["canonical_url"],
            "preview_image_url":
                self._local_preview_image_url(aid),
            "created_at":
                _dt(row["created_at"]),
            "updated_at":
                _dt(row["updated_at"]),
            "destinations":
                destinations,
            "recent_timeline": [{
                "timestamp": _dt(r["timestamp"]),
                "event": r["event"]
            } for r in tl_rows],
        }

    def _add_timeline(self, article_id: str, event: str) -> None:
        self._con.execute(
            "INSERT INTO article_timeline (article_id, timestamp, event) VALUES (?,?,?)",
            (article_id, _ts(_now()), event),
        )
        # Keep only the last 5 entries
        self._con.execute(
            """DELETE FROM article_timeline WHERE article_id=? AND id NOT IN (
               SELECT id FROM article_timeline WHERE article_id=?
               ORDER BY id DESC LIMIT 5)""",
            (article_id, article_id),
        )

    def _touch(self, article_id: str) -> None:
        self._con.execute(
            "UPDATE articles SET updated_at=? WHERE id=?",
            (_ts(_now()), article_id),
        )

    # ── Articles ─────────────────────────────────────────────────────────────

    def list_articles(
        self,
        user_id: str,
        q: str | None = None,
        gate: str | None = None,
        status: str | None = None,
        platform: str | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "updatedAt",
        sort_dir: str = "desc",
    ) -> tuple[list[dict], int]:
        params: list = []
        joins = ""
        wheres: list[str] = ["a.user_id=?"]
        params.append(user_id)

        if status and platform:
            joins = "JOIN article_destinations ad ON a.id=ad.article_id"
            wheres.append("ad.platform=?")
            params.append(platform)
            wheres.append("ad.status=?")
            params.append(status)
        elif status:
            joins = "JOIN article_destinations ad ON a.id=ad.article_id"
            wheres.append("ad.status=?")
            params.append(status)
        elif platform:
            joins = "JOIN article_destinations ad ON a.id=ad.article_id"
            wheres.append("ad.platform=?")
            params.append(platform)
            wheres.append("ad.status != 'none'")

        if q:
            wheres.append("LOWER(a.title) LIKE ?")
            params.append(f"%{q.lower()}%")

        if gate:
            wheres.append("a.gate=?")
            params.append(gate)

        where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        col_map = {"updatedAt": "a.updated_at", "createdAt": "a.created_at", "title": "a.title"}
        order_col = col_map.get(sort_by, "a.updated_at")
        order_dir = "DESC" if sort_dir == "desc" else "ASC"

        count_sql = f"SELECT COUNT(DISTINCT a.id) FROM articles a {joins} {where_clause}"
        total = self._con.execute(count_sql, params).fetchone()[0]

        offset = (page - 1) * page_size
        rows_sql = (f"SELECT DISTINCT a.* FROM articles a {joins} {where_clause} "
                    f"ORDER BY {order_col} {order_dir} LIMIT ? OFFSET ?")
        rows = self._con.execute(rows_sql, params + [page_size, offset]).fetchall()
        return [self._load_article(r) for r in rows], total

    def get_article(self, user_id: str, article_id: str) -> dict | None:
        row = self._con.execute("SELECT * FROM articles WHERE id=? AND user_id=?", (article_id, user_id)).fetchone()
        return self._load_article(row) if row else None

    def create_article(
        self,
        user_id: str,
        title: str,
        source: str = "native",
        source_platform: str | None = None,
        canonical_url: str | None = None,
    ) -> dict:
        with self._workspace_lock.acquire():
            article_id = f"art_{uuid.uuid4().hex[:8]}"
            now_s = _ts(_now())
            body = _seed_body(title)
            body_path = self._write_body(article_id, body)
            self._con.execute(
                """INSERT INTO articles
                   (id, title, body, body_path, word_count, gate, source, source_platform,
                    canonical_url, created_at, updated_at, user_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (article_id, title, "", body_path, len(title.split()) + 11, "pending",
                 source, source_platform, canonical_url, now_s, now_s, user_id),
            )
            for p in _PLATFORMS:
                self._con.execute(
                    "INSERT INTO article_destinations "
                    "(article_id, platform, status, label) VALUES (?,?,?,?)",
                    (article_id, p, "none", "—"),
                )
            self._con.execute(
                "INSERT INTO article_timeline "
                "(article_id, timestamp, event) VALUES (?,?,?)",
                (article_id, now_s, "Article created"),
            )
            self._insert_article_revision(
                article_id,
                1,
                title,
                body,
                source="user",
                description="Article created",
                created_by=user_id,
                created_at=now_s,
            )
            self._con.commit()
            return self.get_article(user_id, article_id)  # type: ignore[return-value]

    def create_imported_article(
        self,
        user_id: str,
        title: str,
        body: str,
        source_platform: str,
        canonical_url: str | None = None,
        remote_updated_at: str | None = None,
    ) -> dict:
        with self._workspace_lock.acquire():
            article_id = f"art_{uuid.uuid4().hex[:8]}"
            timestamp = remote_updated_at or _ts(_now())
            body_path = self._write_body(article_id, body)
            self._con.execute(
                """INSERT INTO articles
                   (id, title, body, body_path, word_count, gate, source, source_platform,
                    canonical_url, created_at, updated_at, user_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    article_id,
                    title,
                    "",
                    body_path,
                    len(body.split()),
                    "pending",
                    "remote",
                    source_platform,
                    canonical_url,
                    timestamp,
                    timestamp,
                    user_id,
                ),
            )
            for platform in _PLATFORMS:
                self._con.execute(
                    "INSERT INTO article_destinations "
                    "(article_id, platform, status, label) VALUES (?,?,?,?)",
                    (article_id, platform, "none", "—"),
                )
            self._add_timeline(article_id, f"Imported from {source_platform.title()}")
            self._insert_article_revision(
                article_id,
                1,
                title,
                body,
                source="remote-sync",
                description=f"Imported from {source_platform.title()}",
                created_by=user_id,
                created_at=timestamp,
            )
            self._con.commit()
            return self.get_article(user_id, article_id)  # type: ignore[return-value]

    def get_or_create_remote_article(
        self,
        user_id: str,
        platform: str,
        remote_id: str,
        *,
        title: str,
        body: str,
        canonical_url: str | None = None,
        remote_updated_at: str | None = None,
    ) -> tuple[dict, bool]:
        """Fetch the local article mapped to (platform, remote_id), creating both
        the article and its identity mapping if no mapping exists yet.

        The identity lookup, article creation, and identity insert all happen
        inside a single workspace-lock acquisition so that two concurrent sync
        calls for the same remote article cannot each create a separate local
        article (see PR #69 review: the previous two-step
        get_remote_article_identity + create_imported_article sequence left a
        check-then-act race window between separate lock acquisitions).
        """
        platform = platform.strip().lower()
        remote_id = remote_id.strip()
        with self._workspace_lock.acquire():
            existing = self._con.execute(
                """SELECT article_id FROM remote_article_identities
                   WHERE user_id=? AND platform=? AND remote_id=?""",
                (user_id, platform, remote_id),
            ).fetchone()
            if existing is not None:
                article = self.get_article(user_id, existing["article_id"])
                if article is not None:
                    return article, False

            article_id = f"art_{uuid.uuid4().hex[:8]}"
            timestamp = remote_updated_at or _ts(_now())
            body_path = self._write_body(article_id, body)
            self._con.execute(
                """INSERT INTO articles
                   (id, title, body, body_path, word_count, gate, source, source_platform,
                    canonical_url, created_at, updated_at, user_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    article_id,
                    title,
                    "",
                    body_path,
                    len(body.split()),
                    "pending",
                    "remote",
                    platform,
                    canonical_url,
                    timestamp,
                    timestamp,
                    user_id,
                ),
            )
            for dest_platform in _PLATFORMS:
                self._con.execute(
                    "INSERT INTO article_destinations "
                    "(article_id, platform, status, label) VALUES (?,?,?,?)",
                    (article_id, dest_platform, "none", "—"),
                )
            self._add_timeline(article_id, f"Imported from {platform.title()}")
            self._insert_article_revision(
                article_id,
                1,
                title,
                body,
                source="remote-sync",
                description=f"Imported from {platform.title()}",
                created_by=user_id,
                created_at=timestamp,
            )
            now = _ts(_now())
            self._con.execute(
                """INSERT INTO remote_article_identities
                   (user_id, platform, remote_id, article_id, created_at, updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (user_id, platform, remote_id, article_id, now, now),
            )
            self._con.commit()
            return self.get_article(user_id, article_id), True  # type: ignore[return-value]

    def sync_remote_article_metadata(
        self,
        user_id: str,
        article_id: str,
        *,
        platform: str,
        status: str,
        url: str | None,
        remote_id: str,
        canonical_url: str | None,
        remote_updated_at: str | None,
    ) -> bool:
        label = "Published" if status == "published" else "Draft"
        draft_id = remote_id if status == "draft" else None
        with self._workspace_lock.acquire():
            article = self._con.execute(
                "SELECT * FROM articles WHERE id=? AND user_id=?",
                (article_id, user_id),
            ).fetchone()
            if article is None:
                raise KeyError(article_id)
            destination = self._con.execute(
                """SELECT status, label, url, draft_id FROM article_destinations
                   WHERE article_id=? AND platform=?""",
                (article_id, platform),
            ).fetchone()
            article_changed = (
                article["canonical_url"] != canonical_url
                or article["source"] != "remote"
                or article["source_platform"] != platform
            )
            destination_changed = destination is None or any((
                destination["status"] != status,
                destination["label"] != label,
                destination["url"] != url,
                destination["draft_id"] != draft_id,
            ))
            timestamp = remote_updated_at or article["updated_at"]
            with self._con:
                self._con.execute(
                    """UPDATE articles
                       SET canonical_url=?, source='remote', source_platform=?, updated_at=?
                       WHERE id=? AND user_id=?""",
                    (canonical_url, platform, timestamp, article_id, user_id),
                )
                self._con.execute(
                    """INSERT INTO article_destinations
                       (article_id, platform, status, label, url, draft_id, error)
                       VALUES (?,?,?,?,?,?,NULL)
                       ON CONFLICT(article_id, platform) DO UPDATE SET
                         status=excluded.status,
                         label=excluded.label,
                         url=excluded.url,
                         draft_id=excluded.draft_id,
                         error=NULL""",
                    (article_id, platform, status, label, url, draft_id),
                )
                if destination_changed:
                    self._add_timeline(
                        article_id,
                        f"{platform.title()} remote status synchronized ({label})",
                    )
            return article_changed or destination_changed

    def update_article_body(self,
                            user_id: str,
                            article_id: str,
                            body: str,
                            event: str = "Article generated by AI") -> None:
        lowered = event.lower()
        source = "agent" if "ai" in lowered else "import" if (
            "import" in lowered or "upload" in lowered
        ) else "user"
        self.save_article_revision(
            user_id,
            article_id,
            content=body,
            source=source,
            description=event,
        )

    def update_article_title(self, user_id: str, article_id: str, title: str) -> None:
        self.save_article_revision(
            user_id,
            article_id,
            title=title,
            source="user",
            description="Article title updated",
        )

    def delete_articles(self, user_id: str, ids: list[str], force: bool = False) -> list[str]:
        with self._workspace_lock.acquire():
            blocked = []
            for aid in ids:
                row = self._con.execute(
                    "SELECT id FROM articles WHERE id=? AND user_id=?", (aid, user_id)
                ).fetchone()
                if row is None:
                    continue
                is_published = self._con.execute(
                    "SELECT 1 FROM article_destinations "
                    "WHERE article_id=? AND status='published'",
                    (aid,),
                ).fetchone() is not None
                if is_published and not force:
                    blocked.append(aid)
                else:
                    self._con.execute(
                        "DELETE FROM articles WHERE id=? AND user_id=?", (aid, user_id)
                    )
                    blob_dir = self._blobs_dir / "articles" / aid
                    if blob_dir.exists():
                        shutil.rmtree(blob_dir)
            self._con.commit()
            return blocked

    def find_article_by_canonical_url(self, user_id: str, canonical_url: str) -> dict | None:
        url = canonical_url.strip().lower()
        row = self._con.execute("SELECT * FROM articles WHERE LOWER(TRIM(canonical_url))=? AND user_id=?",
                                (url, user_id)).fetchone()
        return self._load_article(row) if row else None

    def find_article_by_title(self, user_id: str, title: str) -> dict | None:
        needle = " ".join(title.strip().lower().split())
        rows = self._con.execute("SELECT * FROM articles WHERE user_id=?", (user_id,)).fetchall()
        for row in rows:
            hay = " ".join(row["title"].strip().lower().split())
            if hay == needle:
                return self._load_article(row)
        return None

    def merge_platform_into_article(
        self,
        user_id: str,
        article_id: str,
        platform: str,
        status: str,
        url: str | None,
        draft_id: str | None,
        event: str,
    ) -> dict:
        label = "Published" if status == "published" else "Draft"
        self._con.execute(
            """INSERT INTO article_destinations (article_id, platform, status, label, url, draft_id)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(article_id, platform) DO UPDATE SET
               status=excluded.status, label=excluded.label,
               url=excluded.url, draft_id=excluded.draft_id""",
            (article_id, platform, status, label, url, draft_id),
        )
        self._touch(article_id)
        self._add_timeline(article_id, event)
        self._con.commit()
        return self.get_article(user_id, article_id)  # type: ignore[return-value]

    def apply_inspect_result(self, user_id: str, article_id: str, gate: str) -> None:
        self._con.execute("UPDATE articles SET gate=? WHERE id=? AND user_id=?", (gate, article_id, user_id))
        self._touch(article_id)
        self._add_timeline(article_id, f"Inspection completed (gate: {gate})")
        self._con.commit()

    def apply_push_result(
        self,
        user_id: str,
        article_id: str,
        platform: str,
        success: bool,
        url: str | None = None,
        error: str | None = None,
        label: str | None = None,
        draft_id: str | None = None,
        status: str | None = None,
    ) -> None:
        if success:
            new_status = status or "draft"
            new_label = label or "Draft"
            self._con.execute(
                """UPDATE article_destinations
                   SET status=?, label=?, url=?, error=NULL, draft_id=COALESCE(?,draft_id)
                   WHERE article_id=? AND platform=?""",
                (new_status, new_label, url, draft_id, article_id, platform),
            )
            event = "Published to" if new_status == "published" else "Draft pushed to"
            self._add_timeline(article_id, f"{event} {platform.title()}")
        else:
            self._con.execute(
                """UPDATE article_destinations
                   SET status='error', label=?, error=?
                   WHERE article_id=? AND platform=?""",
                (label or "Error", error, article_id, platform),
            )
            self._add_timeline(article_id, f"{platform.title()} push failed — {error}")
        self._touch(article_id)
        self._con.commit()

    def set_destinations_pending(self, user_id: str, article_id: str, platforms: list[str]) -> None:
        for p in platforms:
            self._con.execute(
                """UPDATE article_destinations SET status='pending'
                   WHERE article_id=? AND platform=?
                   AND article_id IN (SELECT id FROM articles WHERE id=? AND user_id=?)""",
                (article_id, p, article_id, user_id),
            )
        self._touch(article_id)
        self._con.commit()

    # ── Connections ──────────────────────────────────────────────────────────

    def list_connections(self, user_id: str) -> list[dict]:
        rows = {r["platform"]: r for r in self._con.execute(
            "SELECT * FROM connections WHERE user_id=?", (user_id,)).fetchall()}
        result = []
        for conn_id, meta in _CONNECTION_META.items():
            row = rows.get(conn_id)
            if row:
                status = row["status"]
                username = row["username"] or None
                connected_at = row["connected_at"] or None
                error_message = row["error_message"] or None
            else:
                status = "connected" if self._connection_has_env_secret(conn_id) else "disconnected"
                username = None
                connected_at = None
                error_message = None
            result.append({
                "id": conn_id,
                "label": meta["label"],
                "type": meta["type"],
                "auth_method": meta["auth"],
                "status": status,
                "username": username,
                "connected_at": connected_at,
                "error_message": error_message,
            })
        return result

    def save_connection(
        self,
        user_id: str,
        conn_id: str,
        token: str,
        status: str = "connected",
        username: str | None = None,
        error: str | None = None,
    ) -> dict:
        if conn_id not in _CONNECTION_META:
            raise KeyError(f"Unknown connection: {conn_id}")
        now_s = _ts(_now())
        self._con.execute(
            """INSERT INTO connections (platform, token, status, username, connected_at, error_message, user_id)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(platform, user_id) DO UPDATE SET
               token=excluded.token, status=excluded.status, username=excluded.username,
               connected_at=excluded.connected_at, error_message=excluded.error_message""",
            (conn_id, encrypt_token(token), status, username, now_s, error, user_id),
        )
        self._con.commit()
        meta = _CONNECTION_META[conn_id]
        return {
            "id": conn_id,
            "label": meta["label"],
            "type": meta["type"],
            "auth_method": meta["auth"],
            "status": status,
            "username": username,
            "connected_at": now_s,
            "error_message": error,
        }

    def delete_connection(self, user_id: str, conn_id: str) -> None:
        # Insert a "disconnected" stub row rather than deleting the row.
        # Deleting would let _connection_has_env_secret() auto-report "connected"
        # when the env var is present, which breaks tests and the UI delete flow.
        self._con.execute(
            """INSERT OR REPLACE INTO connections
               (platform, token, status, username, connected_at, error_message, user_id)
               VALUES (?, '', 'disconnected', NULL, '', NULL, ?)""",
            (conn_id, user_id),
        )
        self._con.commit()

    def get_connection_token(self, user_id: str, conn_id: str) -> str | None:
        row = self._con.execute("SELECT token FROM connections WHERE platform=? AND user_id=?",
                                (conn_id, user_id)).fetchone()
        if not row or not row["token"]:
            return None
        try:
            return decrypt_token(row["token"]) or None
        except CredentialDecryptionError:
            logger.warning(
                "undecryptable credential for connection %r (user %r); treating as disconnected",
                conn_id, user_id,
            )
            return None

    def reencrypt_connection_credentials(self) -> int:
        """Move plaintext, legacy, and retired-key credentials to the active key."""
        rows = self._con.execute(
            "SELECT platform, user_id, token FROM connections WHERE token <> ''"
        ).fetchall()
        replacements = []
        for row in rows:
            if needs_reencryption(row["token"]):
                replacements.append((
                    encrypt_token(decrypt_token(row["token"])),
                    row["platform"],
                    row["user_id"],
                ))
        if replacements:
            with self._con:
                self._con.executemany(
                    "UPDATE connections SET token=? WHERE platform=? AND user_id IS ?",
                    replacements,
                )
        return len(replacements)

    def count_connected(self, user_id: str) -> int:
        return sum(1 for c in self.list_connections(user_id) if c["status"] == "connected")

    def create_oauth_state(self, conn_id: str) -> str:
        state = secrets.token_urlsafe(32)
        # Invalidate any previous pending state for this conn_id
        stale = [k for k, v in self._oauth_pending.items() if v["conn_id"] == conn_id]
        for k in stale:
            del self._oauth_pending[k]
        self._oauth_pending[state] = {"conn_id": conn_id, "expires": time.time() + 600}
        return state

    def consume_oauth_state(self, state: str, conn_id: str) -> bool:
        entry = self._oauth_pending.pop(state, None)
        if entry is None:
            return False
        if entry["conn_id"] != conn_id:
            return False
        if time.time() > entry["expires"]:
            return False
        return True

    # ── Auth: users ───────────────────────────────────────────────────────────────

    def create_user(self, email: str, password_hash: str) -> dict:
        user_id = str(uuid.uuid4())
        now_s = _ts(_now())
        self._con.execute(
            "INSERT INTO users (id, email, password_hash, created_at) VALUES (?,?,?,?)",
            (user_id, email, password_hash, now_s),
        )
        self._con.commit()
        return {"id": user_id, "email": email, "password_hash": password_hash,
                "created_at": now_s, "is_active": True}

    def get_user_by_email(self, email: str) -> dict | None:
        row = self._con.execute(
            "SELECT id, email, password_hash, created_at, is_active "
            "FROM users WHERE email=?",
            (email,),
        ).fetchone()
        if not row:
            return None
        return {"id": row["id"], "email": row["email"],
                "password_hash": row["password_hash"],
                "created_at": row["created_at"], "is_active": bool(row["is_active"])}

    def get_user_by_id(self, user_id: str) -> dict | None:
        row = self._con.execute(
            "SELECT id, email, created_at, is_active FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        return {"id": row["id"], "email": row["email"],
                "created_at": row["created_at"], "is_active": bool(row["is_active"])}

    # ── Auth: sessions ────────────────────────────────────────────────────────────

    def create_session(self, token: str, user_id: str, expires_at: str,
                       remember_me: bool = False) -> None:
        now_s = _ts(_now())
        self._con.execute(
            "INSERT INTO sessions (token, user_id, expires_at, created_at, remember_me) "
            "VALUES (?,?,?,?,?)",
            (token, user_id, expires_at, now_s, int(remember_me)),
        )
        self._con.commit()

    def get_session(self, token: str) -> dict | None:
        row = self._con.execute(
            "SELECT token, user_id, expires_at, remember_me FROM sessions WHERE token=?",
            (token,),
        ).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
            self._con.execute("DELETE FROM sessions WHERE token=?", (token,))
            self._con.commit()
            return None
        return {"token": row["token"], "user_id": row["user_id"],
                "expires_at": row["expires_at"], "remember_me": bool(row["remember_me"])}

    def delete_session(self, token: str) -> None:
        self._con.execute("DELETE FROM sessions WHERE token=?", (token,))
        self._con.commit()

    def delete_expired_sessions(self) -> int:
        now_s = _ts(datetime.now(timezone.utc))
        cur = self._con.execute("DELETE FROM sessions WHERE expires_at <= ?", (now_s,))
        self._con.commit()
        return cur.rowcount

    # ── Platforms ────────────────────────────────────────────────────────────

    def list_platforms(self, user_id: str) -> list[dict]:
        connections = {c["id"]: c for c in self.list_connections(user_id)}
        result = []
        for pm in _PLATFORM_META:
            conn = connections.get(pm["id"], {})
            result.append({
                **pm,
                "connected": conn.get("status") == "connected",
                "username": conn.get("username") or pm.get("username"),
            })
        return result

    # ── Lifecycle ────────────────────────────────────────────────────────────

    @property
    def schema_version(self) -> int:
        return self._con.execute("PRAGMA user_version").fetchone()[0]

    def create_backup(
        self,
        backup_dir: str | None = None,
        *,
        retain: int = 14,
    ) -> Path:
        if self._db_path == ":memory:":
            raise BackupError("File backups are not available for an in-memory database")
        destination = backup_dir or str(Path(self._db_path).resolve().parent / "backups")
        with self._workspace_lock.acquire():
            return create_verified_backup(
                self._con, self._blobs_dir, destination, retain=retain
            )

    def create_backup_if_due(
        self,
        interval: timedelta,
        backup_dir: str | None = None,
        *,
        retain: int = 14,
    ) -> Path | None:
        if self._db_path == ":memory:":
            raise BackupError("File backups are not available for an in-memory database")
        destination = backup_dir or str(Path(self._db_path).resolve().parent / "backups")
        with self._workspace_lock.acquire():
            return create_verified_backup_if_due(
                self._con,
                self._blobs_dir,
                destination,
                interval=interval,
                retain=retain,
            )

    def close(self) -> None:
        self._con.close()

    def store_asset(
        self,
        user_id: str,
        article_id: str,
        filename: str,
        data: bytes,
        mime_type: str | None = None,
    ) -> str:
        """Write binary asset to disk and record in article_assets. Returns asset_path."""
        with self._workspace_lock.acquire():
            row = self._con.execute(
                "SELECT id FROM articles WHERE id=? AND user_id=?",
                (article_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"Article {article_id} not found for user")
            assets_dir = self._blobs_dir / "articles" / article_id / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            dest = assets_dir / filename
            dest.write_bytes(data)
            rel = str(dest.relative_to(self._blobs_dir))
            now_s = _ts(_now())
            self._con.execute(
                """INSERT INTO article_assets
                   (article_id, filename, asset_path, mime_type, created_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(article_id, filename) DO UPDATE SET
                   asset_path=excluded.asset_path, mime_type=excluded.mime_type""",
                (article_id, filename, rel, mime_type, now_s),
            )
            self._con.commit()
            return rel

    def read_article_asset(
        self, user_id: str, article_id: str, asset_id: int,
    ) -> dict | None:
        """Read a registered asset without exposing its filesystem location."""
        with self._workspace_lock.acquire():
            row = self._con.execute(
                """SELECT aa.id, aa.filename, aa.asset_path, aa.mime_type
                   FROM article_assets aa
                   JOIN articles a ON a.id=aa.article_id
                   WHERE aa.id=? AND aa.article_id=? AND a.user_id=?""",
                (asset_id, article_id, user_id),
            ).fetchone()
            if row is None:
                return None

            assets_root = (
                self._blobs_dir / "articles" / article_id / "assets"
            ).resolve()
            candidate = (self._blobs_dir / row["asset_path"]).resolve()
            try:
                candidate.relative_to(assets_root)
            except ValueError:
                return None
            try:
                if not candidate.is_file():
                    return None
                data = candidate.read_bytes()
            except OSError:
                return None
            return {
                "id": row["id"],
                "filename": row["filename"],
                "mime_type": row["mime_type"],
                "data": data,
            }

    def get_article_asset_by_filename(
        self, user_id: str, article_id: str, filename: str,
    ) -> dict | None:
        with self._workspace_lock.acquire():
            row = self._con.execute(
                """SELECT aa.id, aa.filename, aa.asset_path, aa.mime_type
                   FROM article_assets aa
                   JOIN articles a ON a.id=aa.article_id
                   WHERE aa.article_id=? AND aa.filename=? AND a.user_id=?""",
                (article_id, filename, user_id),
            ).fetchone()
            if row is None:
                return None

            assets_root = (
                self._blobs_dir / "articles" / article_id / "assets"
            ).resolve()
            candidate = (self._blobs_dir / row["asset_path"]).resolve()
            try:
                candidate.relative_to(assets_root)
            except ValueError:
                return None
            try:
                if not candidate.is_file():
                    return None
                data = candidate.read_bytes()
            except OSError:
                return None
            return {
                "id": row["id"],
                "filename": row["filename"],
                "mime_type": row["mime_type"],
                "data": data,
            }

    def reset(self) -> None:
        """Drop all data and re-seed. Used by the /api/dev/reset endpoint in tests."""
        with self._workspace_lock.acquire():
            self._con.executescript("""
                DELETE FROM article_chat_log;
                DELETE FROM agent_sessions;
                DELETE FROM browser_publish_runs;
                DELETE FROM browser_connections;
                DELETE FROM article_patch_revisions;
                DELETE FROM article_patches;
                DELETE FROM article_comments;
                DELETE FROM article_timeline;
                DELETE FROM article_revisions;
                DELETE FROM article_destinations;
                DELETE FROM remote_article_identities;
                DELETE FROM article_assets;
                DELETE FROM articles;
                DELETE FROM jobs;
                DELETE FROM connections;
                DELETE FROM connection_auth_flows;
                DELETE FROM sessions;
                DELETE FROM users;
            """)
            self._con.commit()
            articles_blobs = self._blobs_dir / "articles"
            if articles_blobs.exists():
                shutil.rmtree(articles_blobs)
            self._seed_if_empty()
            self._ensure_initial_article_revisions()
            self._ensure_patch_revision_links()
            self._oauth_pending.clear()

    # ── Comments ─────────────────────────────────────────────────────────────

    def list_comments(self, user_id: str, article_id: str) -> list[dict]:
        rows = self._con.execute(
            "SELECT c.* FROM article_comments c JOIN articles a ON c.article_id = a.id "
            "WHERE c.article_id=? AND a.user_id=? ORDER BY c.created_at ASC",
            (article_id, user_id),
        ).fetchall()
        return [self._comment_row_to_dict(r) for r in rows]

    def add_comment(self,
                    user_id: str,
                    article_id: str,
                    author: str,
                    text: str,
                    anchor: str | None = None) -> dict:
        row = self._con.execute("SELECT id FROM articles WHERE id=? AND user_id=?",
                                (article_id, user_id)).fetchone()
        if row is None:
            raise KeyError(f"Article {article_id} not found for user")
        comment_id = f"c_{uuid.uuid4().hex[:8]}"
        now_s = _ts(_now())
        self._con.execute(
            "INSERT INTO article_comments (id, article_id, author, text, anchor, resolved, has_patch, created_at) "
            "VALUES (?,?,?,?,?,0,0,?)",
            (comment_id, article_id, author, text, anchor, now_s),
        )
        self._con.commit()
        return self._comment_row_to_dict(
            self._con.execute("SELECT * FROM article_comments WHERE id=?",
                              (comment_id,)).fetchone())

    def update_comment(self,
                       user_id: str,
                       article_id: str,
                       comment_id: str,
                       resolved: bool | None = None,
                       text: str | None = None) -> dict | None:
        row = self._con.execute(
            "SELECT c.* FROM article_comments c JOIN articles a ON c.article_id = a.id "
            "WHERE c.id=? AND c.article_id=? AND a.user_id=?",
            (comment_id, article_id, user_id),
        ).fetchone()
        if row is None:
            return None
        if resolved is not None:
            self._con.execute(
                "UPDATE article_comments SET resolved=? WHERE id=?",
                (1 if resolved else 0, comment_id),
            )
        if text is not None:
            self._con.execute("UPDATE article_comments SET text=? WHERE id=?", (text, comment_id))
        self._con.commit()
        return self._comment_row_to_dict(
            self._con.execute("SELECT * FROM article_comments WHERE id=?",
                              (comment_id,)).fetchone())

    def delete_comment(self, user_id: str, article_id: str, comment_id: str) -> bool:
        # Verify article ownership before deleting
        owner_check = self._con.execute("SELECT id FROM articles WHERE id=? AND user_id=?",
                                        (article_id, user_id)).fetchone()
        if owner_check is None:
            return False
        cur = self._con.execute(
            "DELETE FROM article_comments WHERE id=? AND article_id=?",
            (comment_id, article_id),
        )
        self._con.commit()
        return cur.rowcount > 0

    @staticmethod
    def _comment_row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "article_id": row["article_id"],
            "author": row["author"],
            "text": row["text"],
            "anchor": row["anchor"],
            "resolved": bool(row["resolved"]),
            "has_patch": bool(row["has_patch"]),
            "created_at": row["created_at"],
        }

    # ── Patches ──────────────────────────────────────────────────────────────

    def list_patches(self, user_id: str, article_id: str) -> list[dict]:
        rows = self._con.execute(
            "SELECT p.*, pr.base_revision_id, ao.session_id AS agent_session_id "
            "FROM article_patches p "
            "LEFT JOIN article_patch_revisions pr ON pr.patch_id=p.id "
            "LEFT JOIN agent_session_outputs ao "
            "ON ao.reference=p.id AND ao.kind='article_patch' "
            "JOIN articles a ON p.article_id = a.id "
            "WHERE p.article_id=? AND a.user_id=? ORDER BY p.created_at ASC",
            (article_id, user_id),
        ).fetchall()
        return [self._patch_row_to_dict(r) for r in rows]

    def get_patch(self, user_id: str, article_id: str, patch_id: str) -> dict | None:
        row = self._con.execute(
            "SELECT p.*, pr.base_revision_id, ao.session_id AS agent_session_id "
            "FROM article_patches p "
            "LEFT JOIN article_patch_revisions pr ON pr.patch_id=p.id "
            "LEFT JOIN agent_session_outputs ao "
            "ON ao.reference=p.id AND ao.kind='article_patch' "
            "JOIN articles a ON p.article_id=a.id "
            "WHERE p.id=? AND p.article_id=? AND a.user_id=?",
            (patch_id, article_id, user_id),
        ).fetchone()
        return self._patch_row_to_dict(row) if row else None

    def get_pending_agent_session_patch(
        self, user_id: str, session_id: str
    ) -> dict | None:
        row = self._con.execute(
            "SELECT p.*, pr.base_revision_id, ao.session_id AS agent_session_id "
            "FROM agent_session_outputs ao "
            "JOIN agent_sessions s ON s.id=ao.session_id "
            "JOIN article_patches p ON p.id=ao.reference "
            "JOIN article_patch_revisions pr ON pr.patch_id=p.id "
            "WHERE ao.session_id=? AND s.user_id=? AND ao.kind='article_patch' "
            "AND p.state='pending' ORDER BY ao.created_at DESC LIMIT 1",
            (session_id, user_id),
        ).fetchone()
        return self._patch_row_to_dict(row) if row else None

    def add_patch(self,
                  user_id: str,
                  article_id: str,
                  label: str,
                  removed: str,
                  added: str,
                  comment_id: str | None = None,
                  base_revision_id: str | None = None) -> dict:
        row = self._con.execute("SELECT id FROM articles WHERE id=? AND user_id=?",
                                (article_id, user_id)).fetchone()
        if row is None:
            raise KeyError(f"Article {article_id} not found for user")
        patch_id = f"p_{uuid.uuid4().hex[:8]}"
        now_s = _ts(_now())
        self._con.execute(
            "INSERT INTO article_patches (id, article_id, comment_id, label, removed, added, state, created_at) "
            "VALUES (?,?,?,?,?,?,'pending',?)",
            (patch_id, article_id, comment_id, label, removed, added, now_s),
        )
        revision = (
            self.get_article_revision(user_id, article_id, base_revision_id)
            if base_revision_id else self.get_current_article_revision(user_id, article_id)
        )
        if revision is None:
            self._con.rollback()
            raise KeyError(f"Revision not found for article {article_id}")
        self._con.execute(
            "INSERT INTO article_patch_revisions (patch_id, base_revision_id) VALUES (?,?)",
            (patch_id, revision["id"]),
        )
        if comment_id:
            self._con.execute("UPDATE article_comments SET has_patch=1 WHERE id=?", (comment_id,))
        self._con.commit()
        return self._patch_row_to_dict(
            self._con.execute(
                "SELECT p.*, pr.base_revision_id FROM article_patches p "
                "JOIN article_patch_revisions pr ON pr.patch_id=p.id WHERE p.id=?",
                (patch_id,),
            ).fetchone())

    def set_patch_state(self, user_id: str, article_id: str, patch_id: str, state: str) -> dict | None:
        row = self._con.execute(
            "SELECT p.*, pr.base_revision_id FROM article_patches p "
            "LEFT JOIN article_patch_revisions pr ON pr.patch_id=p.id "
            "JOIN articles a ON p.article_id = a.id "
            "WHERE p.id=? AND p.article_id=? AND a.user_id=?",
            (patch_id, article_id, user_id),
        ).fetchone()
        if row is None:
            return None
        self._con.execute("UPDATE article_patches SET state=? WHERE id=?", (state, patch_id))
        self._con.commit()
        return self._patch_row_to_dict(
            self._con.execute(
                "SELECT p.*, pr.base_revision_id FROM article_patches p "
                "LEFT JOIN article_patch_revisions pr ON pr.patch_id=p.id WHERE p.id=?",
                (patch_id,),
            ).fetchone())

    def delete_patches(self, user_id: str, article_id: str) -> None:
        owner = self._con.execute("SELECT id FROM articles WHERE id=? AND user_id=?",
                                  (article_id, user_id)).fetchone()
        if owner is None:
            return
        self._con.execute(
            "DELETE FROM article_patches WHERE article_id=? AND NOT EXISTS ("
            "SELECT 1 FROM agent_session_outputs ao "
            "WHERE ao.kind='article_patch' AND ao.reference=article_patches.id)",
            (article_id,),
        )
        self._con.execute("UPDATE article_comments SET has_patch=0 WHERE article_id=?",
                          (article_id,))
        self._con.commit()

    @staticmethod
    def _patch_row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "article_id": row["article_id"],
            "comment_id": row["comment_id"],
            "label": row["label"],
            "removed": row["removed"],
            "added": row["added"],
            "state": row["state"],
            "created_at": row["created_at"],
            "base_revision_id": row["base_revision_id"],
            "agent_session_id": (
                row["agent_session_id"] if "agent_session_id" in row.keys() else None
            ),
        }

    # ── Chat log ─────────────────────────────────────────────────────────────

    def list_chat(self, user_id: str, article_id: str) -> list[dict]:
        rows = self._con.execute(
            "SELECT cl.role, cl.text, cl.created_at FROM article_chat_log cl "
            "JOIN articles a ON cl.article_id = a.id "
            "WHERE cl.article_id=? AND a.user_id=? ORDER BY cl.id ASC",
            (article_id, user_id),
        ).fetchall()
        return [{"role": r["role"], "text": r["text"], "created_at": r["created_at"]} for r in rows]

    def add_chat_message(self, user_id: str, article_id: str, role: str, text: str) -> dict:
        row = self._con.execute("SELECT id FROM articles WHERE id=? AND user_id=?",
                                (article_id, user_id)).fetchone()
        if row is None:
            raise KeyError(f"Article {article_id} not found for user")
        now_s = _ts(_now())
        self._con.execute(
            "INSERT INTO article_chat_log (article_id, role, text, created_at) VALUES (?,?,?,?)",
            (article_id, role, text, now_s),
        )
        self._con.commit()
        return {"role": role, "text": text, "created_at": now_s}

    # ── Internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _connection_has_env_secret(conn_id: str) -> bool:
        env_name = {
            "devto": "DEVTO_API_KEY",
            "hashnode": "HASHNODE_PAT",
            "medium": "MEDIUM_TOKEN",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
        }.get(conn_id)
        if not env_name:
            return False
        if os.environ.get(env_name, "").strip():
            return True
        env_path = Path(Path(__file__).resolve().parents[4], ".env")
        if not env_path.exists():
            return False
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == env_name and value.strip():
                return True
        return False
