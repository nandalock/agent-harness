"""Agent 配置读写"""
from backend.core.connection import get_conn


def get_agent_definition(agent_key: str) -> dict | None:
    """读取 agent 定义（name, desc, config, cache_policy）"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT agent_key, name, description, config, status, agent_type, cache_policy FROM agent_definitions WHERE agent_key = %s",
                (agent_key,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_agent_config(agent_key: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT config FROM agent_configs WHERE agent_key = %s",
                (agent_key,),
            )
            row = cur.fetchone()
            return dict(row["config"]) if row else None


# ── L1 关键字 CRUD（独立表 router_l1_keywords） ──
