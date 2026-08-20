"""Work around a migration-check mismatch in the pinned Skyvern 1.0.50 image."""

import os
import time

import psycopg


DATABASE_URL = os.environ.get(
    "SKYVERN_SCHEMA_WORKAROUND_DATABASE_URL",
    "postgresql://skyvern:skyvern@postgres:5432/skyvern",
)
CONSTRAINT = "ck_google_oauth_credentials_state"


def constraint_exists(connection: psycopg.Connection) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "select exists(select 1 from pg_constraint where conname = %s)",
            (CONSTRAINT,),
        )
        return bool(cursor.fetchone()[0])


def table_exists(connection: psycopg.Connection) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "select to_regclass('public.google_oauth_credentials') is not null"
        )
        return bool(cursor.fetchone()[0])


def drop_constraint(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "alter table google_oauth_credentials "
            f"drop constraint if exists {CONSTRAINT}"
        )


def main() -> None:
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
                if table_exists(connection):
                    drop_constraint(connection)
                    print("Skyvern 1.0.50 schema workaround complete", flush=True)
                    return
                while time.monotonic() < deadline:
                    if constraint_exists(connection):
                        drop_constraint(connection)
                        print("Skyvern 1.0.50 schema workaround complete", flush=True)
                        return
                    time.sleep(1)
        except psycopg.OperationalError:
            time.sleep(1)
    raise RuntimeError("Timed out waiting for Skyvern's 1.0.50 schema migration")


if __name__ == "__main__":
    main()
