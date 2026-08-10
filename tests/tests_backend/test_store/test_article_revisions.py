from __future__ import annotations

import pytest

from backend.store.article_revisions import RevisionConflict
from backend.store.backends.sqlite import SQLiteStore


def test_existing_articles_are_bootstrapped_on_reopen(tmp_path):
    database = tmp_path / "bloghub.db"
    blobs = tmp_path / "blobs"
    store = SQLiteStore(str(database), str(blobs))
    expected = store.get_article(store.SEED_USER_ID, "art_001")
    store._con.execute("DELETE FROM article_revisions")
    store._con.commit()
    store.close()

    reopened = SQLiteStore(str(database), str(blobs))
    try:
        revision = reopened.get_current_article_revision(reopened.SEED_USER_ID, "art_001")
        assert revision is not None
        assert revision["revision_number"] == 1
        assert revision["content"] == expected["body"]
    finally:
        reopened.close()


def test_revision_sources_distinguish_agent_and_import_updates(tmp_path):
    store = SQLiteStore(str(tmp_path / "bloghub.db"), str(tmp_path / "blobs"))
    try:
        current = store.get_current_article_revision(store.SEED_USER_ID, "art_001")
        agent = store.save_article_revision(
            store.SEED_USER_ID,
            "art_001",
            content="agent body",
            expected_revision_id=current["id"],
            source="agent",
            description="Agent rewrite",
        )
        imported = store.save_article_revision(
            store.SEED_USER_ID,
            "art_001",
            content="imported body",
            expected_revision_id=agent["id"],
            source="import",
            description="Imported update",
        )

        assert agent["source"] == "agent"
        assert imported["source"] == "import"
    finally:
        store.close()


def test_store_rejects_a_stale_expected_revision(tmp_path):
    store = SQLiteStore(str(tmp_path / "bloghub.db"), str(tmp_path / "blobs"))
    try:
        initial = store.get_current_article_revision(store.SEED_USER_ID, "art_001")
        store.save_article_revision(
            store.SEED_USER_ID,
            "art_001",
            content="newer",
            expected_revision_id=initial["id"],
        )

        with pytest.raises(RevisionConflict) as error:
            store.save_article_revision(
                store.SEED_USER_ID,
                "art_001",
                content="stale",
                expected_revision_id=initial["id"],
            )

        assert error.value.current["content"] == "newer"
        assert store.get_article(store.SEED_USER_ID, "art_001")["body"] == "newer"
    finally:
        store.close()
