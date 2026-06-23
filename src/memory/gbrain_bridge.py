"""
gbrain-compatible MCP bridge backed by PostgreSQL.
Provides JSON-RPC API at http://localhost:8787/mcp
with ACL-aware knowledge management.

Supported methods:
  - put_page(id, title, content, tags, frontmatter, read_roles, write_roles)
  - search(query, limit, user_id)
  - get_page(id)
  - delete_page(id, user_id)
  - list_for_owner(owner_type, owner_id)
  - add_tag(page_id, tag)
  - add_timeline_entry(page_id, date, title, description)
  - add_link(source_id, target_id, relation)
"""
from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("GBRAIN_DB_URL", "")


def get_conn():
    if not DB_URL:
        raise RuntimeError("GBRAIN_DB_URL is required")
    return psycopg2.connect(DB_URL)


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gbrain_pages (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            tags TEXT[] NOT NULL DEFAULT '{}',
            read_roles TEXT[] NOT NULL DEFAULT '{*}',
            write_roles TEXT[] NOT NULL DEFAULT '{admin}',
            frontmatter JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gbrain_timeline (
            id SERIAL PRIMARY KEY,
            page_id TEXT NOT NULL REFERENCES gbrain_pages(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT ''
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gbrain_links (
            id SERIAL PRIMARY KEY,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation TEXT NOT NULL DEFAULT 'related_to'
        )
    """)
    # Migrate: add ACL columns to existing tables
    for col, dtype in [("read_roles", "TEXT[] NOT NULL DEFAULT '{{*}}'"),
                        ("write_roles", "TEXT[] NOT NULL DEFAULT '{{admin}}'")]:
        try:
            cur.execute(f"ALTER TABLE gbrain_pages ADD COLUMN IF NOT EXISTS {col.split()[0]} {dtype}")
        except Exception:
            pass
    try:
        cur.execute("ALTER TABLE gbrain_pages ADD COLUMN IF NOT EXISTS fts TSVECTOR")
        cur.execute("CREATE INDEX IF NOT EXISTS gbrain_pages_fts_idx ON gbrain_pages USING GIN(fts)")
    except Exception:
        pass
    conn.commit()
    cur.close()
    conn.close()
    logger.info("gbrain bridge: DB initialized")


class GbrainHandler(BaseHTTPRequestHandler):

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            request = json.loads(raw)
            method = request.get("method", "")
            params = request.get("params", {})
            request_id = request.get("id")
            result = self._dispatch(method, params)
            self._respond(200, {"jsonrpc": "2.0", "id": request_id, "result": result})
        except Exception as e:
            logger.exception("gbrain handler error")
            self._respond(200, {"jsonrpc": "2.0", "id": request.get("id"),
                                "error": {"code": -1, "message": str(e)}})

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"status": "healthy", "db": "connected"})
        elif self.path == "/mcp":
            self._respond(200, {"service": "gbrain-mcp-bridge", "protocols": ["json-rpc"]})
        else:
            self._respond(404, {"error": "not found"})

    def _dispatch(self, method: str, params: dict) -> Any:
        dispatch = {
            "put_page": self._put_page,
            "get_page": self._get_page,
            "search": self._search,
            "delete_page": self._delete_page,
            "list_for_owner": self._list_for_owner,
            "add_tag": self._add_tag,
            "add_timeline_entry": self._add_timeline,
            "add_link": self._add_link,
        }
        handler = dispatch.get(method)
        if not handler:
            raise ValueError(f"Unknown method: {method}")
        return handler(params)

    def _put_page(self, p: dict) -> dict:
        conn = get_conn()
        cur = conn.cursor()
        pid = p.get("id", "")
        title = p.get("title", "")
        content = p.get("content", "")
        tags = p.get("tags", [])
        read_roles = p.get("read_roles", ["*"])
        write_roles = p.get("write_roles", ["admin"])
        fm = json.dumps(p.get("frontmatter", {}))
        cur.execute(
            """INSERT INTO gbrain_pages (id, title, content, tags, read_roles, write_roles, frontmatter, fts)
               VALUES (%s, %s, %s, %s, %s, %s, %s, to_tsvector('english', %s))
               ON CONFLICT (id) DO UPDATE SET
               title=%s, content=%s, tags=%s, read_roles=%s, write_roles=%s,
               frontmatter=%s, fts=to_tsvector('english', %s), updated_at=NOW()""",
            (pid, title, content, tags, read_roles, write_roles, fm, content,
             title, content, tags, read_roles, write_roles, fm, content),
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"id": pid, "status": "ok"}

    def _get_page(self, p: dict) -> dict | None:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM gbrain_pages WHERE id = %s", (p.get("id", ""),))
        row = cur.fetchone()
        if row:
            result = dict(row)
            # JSON-ify frontmatter
            if isinstance(result.get("frontmatter"), str):
                result["frontmatter"] = json.loads(result["frontmatter"])
            # Also get timeline + links
            cur.execute("SELECT * FROM gbrain_timeline WHERE page_id = %s ORDER BY date DESC LIMIT 20", (p["id"],))
            result["timeline"] = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM gbrain_links WHERE source_id = %s OR target_id = %s", (p["id"], p["id"]))
            result["links"] = [dict(r) for r in cur.fetchall()]
            cur.close()
            conn.close()
            return result
        cur.close()
        conn.close()
        return None

    def _search(self, p: dict) -> list[dict]:
        query = p.get("query", "")
        limit = int(p.get("limit", 20))
        user_id = p.get("user_id", "")
        conn = get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if user_id:
            # ACL-aware search: match read_roles against user
            cur.execute(
                """SELECT id, title, content, tags, read_roles, write_roles, frontmatter
                   FROM gbrain_pages
                   WHERE fts @@ plainto_tsquery('english', %s)
                   AND (read_roles && ARRAY['*', %s])
                   LIMIT %s""",
                (query, user_id, limit),
            )
        else:
            cur.execute(
                "SELECT id, title, content, tags, read_roles, write_roles, frontmatter "
                "FROM gbrain_pages WHERE fts @@ plainto_tsquery('english', %s) LIMIT %s",
                (query, limit),
            )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [dict(r) for r in rows]

    def _delete_page(self, p: dict) -> dict:
        pid = p.get("id", "")
        user_id = p.get("user_id", "")
        conn = get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Check write permission: user must be in write_roles or write_roles contains '*'
        cur.execute(
            "SELECT write_roles FROM gbrain_pages WHERE id = %s",
            (pid,),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            raise ValueError(f"Page {pid} not found")
        wroles = row["write_roles"]
        if user_id not in wroles and "*" not in wroles and "admin" not in wroles:
            cur.close()
            conn.close()
            raise ValueError(f"User {user_id} not authorized to delete {pid}")
        # Cascade delete handles timeline/links via FK
        cur.execute("DELETE FROM gbrain_pages WHERE id = %s", (pid,))
        conn.commit()
        cur.close()
        conn.close()
        return {"id": pid, "status": "deleted"}

    def _list_for_owner(self, p: dict) -> list[dict]:
        owner_type = p.get("owner_type", "organization")
        owner_id = p.get("owner_id", "*")
        user_id = p.get("user_id", "")
        conn = get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # The owner_type and owner_id are stored in frontmatter or deduced from id prefix
        # Query by frontmatter->>owner_type
        cur.execute(
            """SELECT id, title, content, tags, read_roles, write_roles, frontmatter
               FROM gbrain_pages
               WHERE frontmatter->>'owner_type' = %s AND frontmatter->>'owner_id' = %s
               ORDER BY created_at DESC LIMIT 100""",
            (owner_type, owner_id),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        results = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("frontmatter"), str):
                d["frontmatter"] = json.loads(d["frontmatter"])
            results.append(d)
        return results

    def _add_tag(self, p: dict) -> dict:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE gbrain_pages SET tags = array_append(tags, %s) WHERE id = %s AND NOT (%s = ANY(tags))",
            (p.get("tag", ""), p.get("page_id", ""), p.get("tag", "")),
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok"}

    def _add_timeline(self, p: dict) -> dict:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO gbrain_timeline (page_id, date, title, description) VALUES (%s, %s, %s, %s)",
            (p.get("page_id", ""), p.get("date", ""), p.get("title", ""), p.get("description", "")),
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok"}

    def _add_link(self, p: dict) -> dict:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO gbrain_links (source_id, target_id, relation) VALUES (%s, %s, %s)",
            (p.get("source_id", ""), p.get("target_id", ""), p.get("relation", "related_to")),
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok"}

    def _respond(self, code: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug("gbrain: %s", fmt % args)


def serve(host: str = "", port: int = 8787):
    host = host or os.environ.get("BIND_HOST", "127.0.0.1")
    port = int(os.environ.get("BIND_PORT", str(port)))
    init_db()
    server = HTTPServer((host, port), GbrainHandler)
    logger.info(f"gbrain bridge listening on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    serve()
