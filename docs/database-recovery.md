# Database Migrations and Recovery

BlogHub stores structured data in SQLite and article bodies and assets beneath the
blob directory. A usable backup always contains both.

## Paths

The default paths are:

```text
data/bloghub.db
data/blobs/
data/backups/
```

Override them with `BLOGHUB_DB_PATH`, `BLOGHUB_BLOBS_DIR`, and
`BLOGHUB_BACKUP_DIR`.

## Schema

The database shape is defined in `backend/store/sql/schema.sql`, isolated from
Python so it can be read and reviewed on its own. BlogHub applies it automatically
when it opens the database; every statement is idempotent, so re-applying it
against an already-current database is a no-op.

BlogHub does not migrate schemas in place. When `schema.sql` changes, delete the
runtime database (`data/bloghub.db`) and let it be recreated fresh, instead of
writing an upgrade path for the old shape. Bump `SCHEMA_VERSION` in
`backend/store/schema.py` alongside a breaking schema change so `status` reports
it.

Check the current schema version and database integrity with:

```bash
python scripts/bloghub_db.py status
```

## On-demand backups

The backup command uses SQLite's online backup API, so committed WAL data is
included without copying a live database file directly. It then copies the blob
workspace, verifies SQLite integrity and foreign keys, checks every referenced
blob, records a SHA-256 checksum, and atomically publishes the completed bundle.
Database-and-blob operations share a cross-process workspace lock, preventing
article or asset writes from crossing the backup snapshot boundary.

```bash
python scripts/bloghub_db.py backup --retain 14
```

Each bundle is a directory containing:

```text
manifest.json
bloghub.sqlite3
blobs/
```

## Scheduled backups

Run the idempotent due check from cron, systemd, Windows Task Scheduler, or the
deployment scheduler. Calling it more frequently than the interval is safe:

```bash
python scripts/bloghub_db.py backup --if-due-hours 24 --retain 14
```

The command prints `backup not due` until the newest verified bundle is at least
24 hours old. Alert on a non-zero exit and monitor the age of the newest bundle.

## Verify a backup

Verification does not modify the bundle:

```bash
python scripts/bloghub_db.py verify data/backups/bloghub-YYYYMMDDTHHMMSS.ffffffZ
```

Verification checks the manifest format, database checksum, SQLite integrity,
foreign keys, row-count summary, and all database-referenced blob files.

## Restore

1. Stop BlogHub and every worker that can access the database or blobs.
2. Verify the selected bundle.
3. Restore it with explicit confirmation.
4. Start BlogHub and run the status command.
5. Exercise article reads, asset downloads, authentication, and a non-publishing
   agent job before resuming normal operation.

```bash
python scripts/bloghub_db.py verify <bundle>
python scripts/bloghub_db.py restore <bundle> --yes
python scripts/bloghub_db.py status
```

Restore stages the database and blobs before replacing the active paths. If the
replacement fails, it puts the previous database and blob directory back.

## Recovery policy

- Keep at least 14 daily backups in production.
- Copy backups to storage outside the BlogHub host.
- Restrict access because backups contain articles, account data, and encrypted
  provider credentials.
- Test a restore regularly. A backup is not considered healthy until verification
  and restore checks pass.
- Do not commit database files, WAL files, backup bundles, or blob contents.
