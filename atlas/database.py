"""SQLite persistence and schema migrations; SQLite owns record metadata."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1


def connect(db_path: Path):
    conn = sqlite3.connect(str(db_path), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=10000')
    return conn


def migrate(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError('Database created with a newer Atlas version')
        if version == SCHEMA_VERSION:
            return
        conn.executescript('''
        BEGIN IMMEDIATE;
        CREATE TABLE IF NOT EXISTS workspaces (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            kind_label TEXT NOT NULL DEFAULT '', archived_at TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
            title TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('todo','doing','blocked','done')),
            priority INTEGER NOT NULL DEFAULT 2 CHECK(priority BETWEEN 1 AND 3),
            due_on TEXT, next_action TEXT NOT NULL DEFAULT '', details TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_workspace ON tasks(workspace_id);
        CREATE TABLE IF NOT EXISTS checkpoints (
            id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
            summary TEXT NOT NULL, next_action TEXT NOT NULL, blocker TEXT NOT NULL DEFAULT '',
            evidence TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_checkpoints_workspace ON checkpoints(workspace_id,created_at);
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
            title TEXT NOT NULL, relative_path TEXT NOT NULL UNIQUE,
            content_version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS file_references (
            id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
            display_name TEXT NOT NULL, target_path TEXT NOT NULL, kind TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS activity_events (
            id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
            type TEXT NOT NULL, related_id TEXT NOT NULL, summary TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS legacy_imports (
            digest TEXT PRIMARY KEY, imported_at TEXT NOT NULL,
            raw_relative_path TEXT NOT NULL, mapped_workspaces INTEGER NOT NULL,
            mapped_tasks INTEGER NOT NULL, unmapped_summary TEXT NOT NULL
        );
        PRAGMA user_version=1;
        COMMIT;
        ''')
    except Exception:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        raise
    finally:
        conn.close()


@contextmanager
def transaction(db_path: Path):
    conn = connect(db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        yield conn
        conn.execute('COMMIT')
    except Exception:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        raise
    finally:
        conn.close()


def rows(db_path: Path, query: str, args=()):
    conn = connect(db_path)
    try:
        return [dict(row) for row in conn.execute(query, args).fetchall()]
    finally:
        conn.close()


def one(db_path: Path, query: str, args=()):
    conn = connect(db_path)
    try:
        row = conn.execute(query, args).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
