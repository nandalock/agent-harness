"""Database-backed settings plugin."""
from .plugin import PostgresSettingsPlugin
from .service import PostgresSettingsService

__all__ = ["PostgresSettingsPlugin", "PostgresSettingsService"]
