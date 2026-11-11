"""Phase 1 服务注册表：SQLite，记录每个已发布服务的状态。"""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "services.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,          -- raster | vector | tiles
    status TEXT NOT NULL,        -- active | error
    file_path TEXT,              -- 上传文件在 data/ 下的相对路径（tiles 为空）
    table_name TEXT,             -- vector 在 PostGIS 里的表名（svc_<slug>）
    source_slug TEXT,            -- tiles 的源服务 slug
    style TEXT NOT NULL DEFAULT '{}',  -- JSON：fill/outline/line/width
    error TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(services)")]
    if "geom_type" not in cols:
        conn.execute("ALTER TABLE services ADD COLUMN geom_type TEXT")
    conn.commit()
    return conn


def list_services():
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM services ORDER BY id DESC")]
    finally:
        conn.close()


def get_service(slug):
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM services WHERE slug=?", (slug,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def slug_exists(slug):
    return get_service(slug) is not None


def insert_service(row):
    conn = connect()
    try:
        cur = conn.execute(
            """INSERT INTO services
               (slug, name, type, status, file_path, table_name,
                source_slug, style, error, created_at, updated_at, geom_type)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row["slug"], row["name"], row["type"], row["status"],
             row.get("file_path"), row.get("table_name"),
             row.get("source_slug"), row.get("style", "{}"),
             row.get("error", ""), row["created_at"], row["updated_at"],
             row.get("geom_type")))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_service(slug, **fields):
    fields["updated_at"] = fields.get("updated_at") or __import__(
        "datetime").datetime.now().isoformat(timespec="seconds")
    keys = ", ".join("%s=?" % k for k in fields)
    conn = connect()
    try:
        conn.execute("UPDATE services SET %s WHERE slug=?" % keys,
                     tuple(fields.values()) + (slug,))
        conn.commit()
    finally:
        conn.close()


def delete_service(slug):
    conn = connect()
    try:
        conn.execute("DELETE FROM services WHERE slug=?", (slug,))
        conn.commit()
    finally:
        conn.close()
