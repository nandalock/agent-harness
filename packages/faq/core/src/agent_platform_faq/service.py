"""Tenant-scoped FAQ storage and matching."""
from __future__ import annotations

import csv
import io
import json
import logging
import os
from urllib.request import Request, urlopen

from agent_platform_plugin_sdk import Database

from .models import FAQImportResult

logger = logging.getLogger(__name__)


def _embed_sync(text: str) -> list[float] | None:
    """Synchronous Ollama embedding; failures degrade to an unvectorized row."""
    ollama_url = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    try:
        body = json.dumps({"model": "bge-m3", "input": text}).encode()
        request = Request(
            f"{ollama_url}/api/embed",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=60) as response:
            data = json.loads(response.read())
            embeddings = data.get("embeddings", [])
            if embeddings:
                return embeddings[0]
    except Exception:  # noqa: BLE001
        return None
    return None


class FAQService:
    """One FAQ service per plugin runtime."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def create(
        self, tenant_id: int, question: str, answer: str,
        tags: list[str], vectorize: bool = True,
    ) -> dict:
        embedding = _embed_sync(question) if vectorize else None
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO faqs (tenant_id, question, answer, tags, embedding)
                       VALUES (%s, %s, %s, %s, %s::vector) RETURNING *""",
                    (tenant_id, question, answer, tags, embedding),
                )
                return dict(cur.fetchone())

    def get(self, tenant_id: int, faq_id: int) -> dict | None:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM faqs WHERE id = %s AND tenant_id = %s",
                    (faq_id, tenant_id),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def update(self, tenant_id: int, faq_id: int, **kwargs) -> dict | None:
        allowed = {"question", "answer", "tags", "is_active"}
        updates = {key: value for key, value in kwargs.items() if key in allowed and value is not None}
        if not updates:
            return self.get(tenant_id, faq_id)

        set_clause = ", ".join(f"{key} = %s" for key in updates)
        values = list(updates.values()) + [faq_id, tenant_id]
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE faqs SET {set_clause}, updated_at = now() "
                    "WHERE id = %s AND tenant_id = %s RETURNING *",
                    values,
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def delete(self, tenant_id: int, faq_id: int) -> bool:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM faqs WHERE id = %s AND tenant_id = %s",
                    (faq_id, tenant_id),
                )
                return cur.rowcount > 0

    def list(
        self, tenant_id: int, tag: str = "", page: int = 1, size: int = 20,
    ) -> tuple[list[dict], int]:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                if tag:
                    cur.execute(
                        "SELECT count(*) FROM faqs WHERE tenant_id = %s AND %s = ANY(tags)",
                        (tenant_id, tag),
                    )
                else:
                    cur.execute("SELECT count(*) FROM faqs WHERE tenant_id = %s", (tenant_id,))
                total = cur.fetchone()["count"]

                offset = (page - 1) * size
                if tag:
                    cur.execute(
                        """SELECT * FROM faqs WHERE tenant_id = %s AND %s = ANY(tags)
                           ORDER BY updated_at DESC LIMIT %s OFFSET %s""",
                        (tenant_id, tag, size, offset),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM faqs WHERE tenant_id = %s "
                        "ORDER BY updated_at DESC LIMIT %s OFFSET %s",
                        (tenant_id, size, offset),
                    )
                return [dict(row) for row in cur.fetchall()], total

    def match(
        self, tenant_id: int, question: str, direct_threshold: float = 0.95,
    ) -> dict | None:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT *, similarity(question, %s) AS _score
                       FROM faqs
                       WHERE tenant_id = %s AND is_active = true
                         AND similarity(question, %s) > 0.3
                       ORDER BY _score DESC LIMIT 1""",
                    (question, tenant_id, question),
                )
                row = cur.fetchone()
                if row:
                    result = dict(row)
                    if result.get("_score", 0) >= direct_threshold:
                        result["_tier"] = "direct"
                        return result
        return None

    def import_csv(self, tenant_id: int, file_content: bytes) -> FAQImportResult:
        reader = csv.DictReader(io.StringIO(file_content.decode("utf-8-sig")))
        required = {"question", "answer"}
        if not required.issubset(set(reader.fieldnames or [])):
            return FAQImportResult(
                total=0, success=0, errors=["CSV 缺少必需列: question, answer"],
            )

        total = 0
        success = 0
        errors: list[str] = []
        with self._database.get_conn() as conn:
            for index, row in enumerate(reader, start=1):
                total += 1
                question = (row.get("question") or "").strip()
                answer = (row.get("answer") or "").strip()
                if not question or not answer:
                    errors.append(f"行 {index}: question 或 answer 为空")
                    continue
                tags_raw = (row.get("tags") or "").strip()
                tags = [tag.strip() for tag in tags_raw.split(",") if tag.strip()] if tags_raw else []
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO faqs (tenant_id, question, answer, tags) "
                        "VALUES (%s, %s, %s, %s)",
                        (tenant_id, question, answer, tags),
                    )
                success += 1
        return FAQImportResult(total=total, success=success, errors=errors)

    def vectorize(self, tenant_id: int, faq_id: int) -> tuple[bool, str]:
        faq = self.get(tenant_id, faq_id)
        if not faq:
            return False, "FAQ 不存在"
        vector = _embed_sync(faq["question"])
        if not vector:
            return False, "embedding 失败"
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE faqs SET embedding = %s::vector, updated_at = now() "
                    "WHERE id = %s AND tenant_id = %s",
                    (vector, faq_id, tenant_id),
                )
        return True, ""

    def backfill(self, tenant_id: int) -> dict:
        with self._database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, question FROM faqs "
                    "WHERE tenant_id = %s AND embedding IS NULL AND is_active = true",
                    (tenant_id,),
                )
                rows = cur.fetchall()

        total = len(rows)
        success = 0
        errors: list[str] = []
        for row in rows:
            vector = _embed_sync(row["question"])
            if not vector:
                errors.append(f"id={row['id']}: embedding 失败")
                continue
            with self._database.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE faqs SET embedding = %s::vector, updated_at = now() "
                        "WHERE id = %s",
                        (vector, row["id"]),
                    )
            success += 1
        return {"total": total, "success": success, "errors": errors}
