"""Environment-driven database access for MCP server registration."""
import os

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://saas:saas@localhost:5432/saas"
)


def connect():
    conn = psycopg2.connect(DATABASE_URL)
    conn.cursor_factory = RealDictCursor
    return conn
