"""
Hindsight-compatible warm-layer bridge backed by PostgreSQL.
Provides same REST API at http://localhost:8890 expected by
Memory Sidecar scripts (memory_governance_rebuild.py, tiered_context_injector.py).

Endpoints:
  POST /v1/default/banks/hermes/memories  - retain memory
  GET  /v1/default/banks/hermes/memories/recall?query=...  - recall memories
  GET  /health
  GET  /v1/default/banks/hermes/stats
  POST /v1/default/banks/hermes/consolidate  - consolidate patterns
  GET  /metrics
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)
DB_URL = os.environ.get("HINDSIGHT_DB_URL", "postgresql://sidecar:sidecar123@localhost:5432/sidecar")
BANK = "hermes"


def get_conn():
    return psycopg2.connect(DB_URL)


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hindsight_memories (
            id TEXT PRIMARY KEY,
            memory TEXT NOT NULL,
            observation TEXT NOT NULL DEFAULT '',
            embedding vector(384),
            tags TEXT[] NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_recalled TIMESTAMPTZ,
            recall_count INTEGER NOT NULL DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hindsight_consolidations (
            id SERIAL PRIMARY KEY,
            pattern TEXT NOT NULL,
            source_ids TEXT[] NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    # FTS on memories
    cur.execute("ALTER TABLE hindsight_memories ADD COLUMN IF NOT EXISTS fts TSVECTOR")
    cur.execute("CREATE INDEX IF NOT EXISTS hindsight_fts_idx ON hindsight_memories USING GIN(fts)")
    conn.commit()
    cur.close()
    conn.close()
    logger.info("hindsight bridge: DB initialized")


class HindsightHandler(BaseHTTPRequestHandler):

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length > 0 else {}
        try:
            if self.path.endswith("/memories"):
                result = self._retain(body)
            elif self.path.endswith("/consolidate"):
                result = self._consolidate()
            else:
                self._respond(404, {"error": "not found"})
                return
            self._respond(200, result)
        except Exception as e:
            logger.exception("hindsight error")
            self._respond(500, {"error": str(e)})

    def do_GET(self):
        try:
            if self.path == "/health":
                self._respond(200, {"status": "healthy", "database": "connected"})
            elif self.path.endswith("/stats"):
                self._respond(200, self._stats())
            elif "/recall" in self.path:
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                query = qs.get("query", [""])[0]
                limit = int(qs.get("limit", [20])[0])
                self._respond(200, self._recall(query, limit))
            elif self.path == "/metrics":
                self._respond(200, self._metrics())
            else:
                self._respond(404, {"error": "not found"})
        except Exception as e:
            logger.exception("hindsight error")
            self._respond(500, {"error": str(e)})

    def _retain(self, body: dict) -> dict:
        memory = body.get("memory", body.get("text", ""))
        observation = body.get("observation", memory[:200])
        tags = body.get("tags", [])
        mid = body.get("id", f"mem-{uuid.uuid4().hex[:12]}")
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO hindsight_memories (id, memory, observation, tags, fts)
               VALUES (%s, %s, %s, %s, to_tsvector('english', %s))
               ON CONFLICT (id) DO UPDATE SET memory=%s, observation=%s, tags=%s,
               fts=to_tsvector('english', %s), last_recalled=NOW()""",
            (mid, memory, observation, tags, memory, memory, observation, tags, memory),
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.debug("hindsight: retained %s", mid)
        return {"id": mid, "status": "retained"}

    def _recall(self, query: str, limit: int) -> dict:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if query:
            cur.execute(
                """SELECT id, memory, observation, tags, recall_count FROM hindsight_memories
                   WHERE fts @@ plainto_tsquery('english', %s)
                   ORDER BY recall_count DESC, last_recalled DESC NULLS LAST
                   LIMIT %s""",
                (query, limit),
            )
        else:
            cur.execute(
                "SELECT id, memory, observation, tags, recall_count FROM hindsight_memories ORDER BY last_recalled DESC NULLS LAST LIMIT %s",
                (limit,),
            )
        rows = cur.fetchall()
        # Update recall stats
        for r in rows:
            cur.execute(
                "UPDATE hindsight_memories SET recall_count=recall_count+1, last_recalled=NOW() WHERE id=%s",
                (r["id"],),
            )
        conn.commit()
        cur.close()
        conn.close()
        return {"memories": [dict(r) for r in rows], "count": len(rows)}

    def _stats(self) -> dict:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as c FROM hindsight_memories")
        total = cur.fetchone()[0]
        cur.close()
        conn.close()
        return {"bank": BANK, "total_memories": total, "extracted": total}

    def _consolidate(self) -> dict:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT memory FROM hindsight_memories ORDER BY recall_count DESC LIMIT 100")
        rows = cur.fetchall()
        patterns = []
        seen = set()
        for r in rows:
            words = r[0].lower().split()
            for w in words:
                if len(w) > 4 and w not in seen:
                    seen.add(w)
                    patterns.append(w)
        if patterns:
            cur.execute(
                "INSERT INTO hindsight_consolidations (pattern, source_ids) VALUES (%s, %s)",
                (", ".join(patterns[:50]), [r[0][:50] for r in rows[:10]]),
            )
            conn.commit()
        cur.close()
        conn.close()
        return {"status": "consolidated", "patterns_found": len(patterns[:50])}

    def _metrics(self) -> str:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM hindsight_memories")
        total = cur.fetchone()[0]
        cur.close()
        conn.close()
        return f"hindsight_total_memories {total}\n"

    def _respond(self, code: int, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug("hindsight: %s", fmt % args)


def serve(host: str = "", port: int = 8890):
    host = host or os.environ.get("BIND_HOST", "127.0.0.1")
    port = int(os.environ.get("BIND_PORT", str(port)))
    init_db()
    server = HTTPServer((host, port), HindsightHandler)
    logger.info(f"hindsight bridge listening on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    serve()
