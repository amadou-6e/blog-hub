"""Immutable article revision storage and optimistic save operations."""
from __future__ import annotations

import difflib
import uuid
from datetime import datetime, timezone


class RevisionConflict(Exception):
    def __init__(self, current: dict):
        super().__init__("The article changed after this draft was loaded")
        self.current = current


class ArticleRevisionStoreMixin:
    def _revision_row_to_dict(self, row, *, include_content: bool = True) -> dict:
        revision = {
            "id": row["id"],
            "article_id": row["article_id"],
            "revision_number": row["revision_number"],
            "title": row["title"],
            "source": row["source"],
            "description": row["description"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "base_revision_id": row["base_revision_id"],
            "restored_from_id": row["restored_from_id"],
        }
        if include_content:
            revision["content"] = row["content"]
        return revision

    def _latest_revision_row(self, article_id: str):
        return self._con.execute(
            "SELECT * FROM article_revisions WHERE article_id=? "
            "ORDER BY revision_number DESC LIMIT 1",
            (article_id,),
        ).fetchone()

    def _insert_article_revision(
        self,
        article_id: str,
        revision_number: int,
        title: str,
        content: str,
        *,
        source: str,
        description: str | None,
        created_by: str | None,
        created_at: str | None = None,
        base_revision_id: str | None = None,
        restored_from_id: str | None = None,
    ):
        revision_id = f"rev_{uuid.uuid4().hex}"
        self._con.execute(
            """INSERT INTO article_revisions
               (id, article_id, revision_number, title, content, source,
                description, created_by, created_at, base_revision_id, restored_from_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                revision_id,
                article_id,
                revision_number,
                title,
                content,
                source,
                description,
                created_by,
                created_at or datetime.now(timezone.utc).isoformat(),
                base_revision_id,
                restored_from_id,
            ),
        )
        return self._con.execute(
            "SELECT * FROM article_revisions WHERE id=?", (revision_id,)
        ).fetchone()

    def _ensure_initial_article_revisions(self) -> None:
        rows = self._con.execute(
            """SELECT a.* FROM articles a
               WHERE NOT EXISTS (
                   SELECT 1 FROM article_revisions r WHERE r.article_id=a.id
               )"""
        ).fetchall()
        for row in rows:
            self._insert_article_revision(
                row["id"],
                1,
                row["title"],
                self._read_body(row),
                source="import" if row["source"] != "native" else "system",
                description="Initial revision",
                created_by=row["user_id"],
                created_at=row["created_at"],
            )
        if rows:
            self._con.commit()

    def _ensure_patch_revision_links(self) -> None:
        rows = self._con.execute(
            """SELECT p.id, p.article_id FROM article_patches p
               WHERE NOT EXISTS (
                   SELECT 1 FROM article_patch_revisions pr WHERE pr.patch_id=p.id
               )"""
        ).fetchall()
        for row in rows:
            current = self._latest_revision_row(row["article_id"])
            if current:
                self._con.execute(
                    "INSERT INTO article_patch_revisions (patch_id, base_revision_id) VALUES (?,?)",
                    (row["id"], current["id"]),
                )
        if rows:
            self._con.commit()

    def get_current_article_revision(self, user_id: str, article_id: str) -> dict | None:
        owner = self._con.execute(
            "SELECT id FROM articles WHERE id=? AND user_id=?", (article_id, user_id)
        ).fetchone()
        row = self._latest_revision_row(article_id) if owner else None
        return self._revision_row_to_dict(row) if row else None

    def list_article_revisions(self, user_id: str, article_id: str) -> list[dict]:
        rows = self._con.execute(
            """SELECT r.* FROM article_revisions r
               JOIN articles a ON a.id=r.article_id
               WHERE r.article_id=? AND a.user_id=?
               ORDER BY r.revision_number DESC""",
            (article_id, user_id),
        ).fetchall()
        return [self._revision_row_to_dict(row, include_content=False) for row in rows]

    def get_article_revision(
        self, user_id: str, article_id: str, revision_id: str
    ) -> dict | None:
        row = self._con.execute(
            """SELECT r.* FROM article_revisions r
               JOIN articles a ON a.id=r.article_id
               WHERE r.id=? AND r.article_id=? AND a.user_id=?""",
            (revision_id, article_id, user_id),
        ).fetchone()
        return self._revision_row_to_dict(row) if row else None

    def save_article_revision(
        self,
        user_id: str,
        article_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        expected_revision_id: str | None = None,
        source: str = "user",
        description: str | None = None,
        force_revision: bool = False,
        restored_from_id: str | None = None,
    ) -> dict:
        with self._workspace_lock.acquire():
            article = self._con.execute(
                "SELECT * FROM articles WHERE id=? AND user_id=?", (article_id, user_id)
            ).fetchone()
            if article is None:
                raise KeyError(article_id)
            current_row = self._latest_revision_row(article_id)
            if current_row is None:
                self._ensure_initial_article_revisions()
                current_row = self._latest_revision_row(article_id)
            assert current_row is not None
            current = self._revision_row_to_dict(current_row)
            if expected_revision_id is not None and expected_revision_id != current["id"]:
                raise RevisionConflict(current)

            next_title = article["title"] if title is None else title
            next_content = self._read_body(article) if content is None else content
            if (
                not force_revision
                and next_title == current["title"]
                and next_content == current["content"]
            ):
                return current

            now = datetime.now(timezone.utc).isoformat()
            body_path = self._write_body(article_id, next_content)
            self._con.execute(
                """UPDATE articles
                   SET title=?, body='', body_path=?, word_count=?, updated_at=?
                   WHERE id=? AND user_id=?""",
                (
                    next_title,
                    body_path,
                    len(next_content.split()),
                    now,
                    article_id,
                    user_id,
                ),
            )
            revision_row = self._insert_article_revision(
                article_id,
                current["revision_number"] + 1,
                next_title,
                next_content,
                source=source,
                description=description,
                created_by=user_id,
                created_at=now,
                base_revision_id=current["id"],
                restored_from_id=restored_from_id,
            )
            event = description or {
                "user": "Article saved",
                "agent": "Article updated by AI",
                "import": "Imported article updated",
                "restore": "Article revision restored",
            }.get(source, "Article updated")
            self._add_timeline(article_id, event)
            self._con.commit()
            return self._revision_row_to_dict(revision_row)

    def restore_article_revision(
        self,
        user_id: str,
        article_id: str,
        revision_id: str,
        expected_revision_id: str,
    ) -> dict:
        target = self.get_article_revision(user_id, article_id, revision_id)
        if target is None:
            raise KeyError(revision_id)
        return self.save_article_revision(
            user_id,
            article_id,
            title=target["title"],
            content=target["content"],
            expected_revision_id=expected_revision_id,
            source="restore",
            description=f"Restored revision {target['revision_number']}",
            force_revision=True,
            restored_from_id=revision_id,
        )

    def compare_article_revision(
        self, user_id: str, article_id: str, revision_id: str
    ) -> dict | None:
        revision = self.get_article_revision(user_id, article_id, revision_id)
        current = self.get_current_article_revision(user_id, article_id)
        if revision is None or current is None:
            return None
        before = [f"# {revision['title']}\n", *revision["content"].splitlines(keepends=True)]
        after = [f"# {current['title']}\n", *current["content"].splitlines(keepends=True)]
        diff = "".join(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"revision-{revision['revision_number']}",
                tofile=f"revision-{current['revision_number']}",
            )
        )
        return {"revision": revision, "current": current, "diff": diff}
