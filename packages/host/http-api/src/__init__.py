"""HTTP/API plugin: FastAPI application assembly."""
from .app import create_app
from .plugin import HttpApiPlugin
from .services import HTTP_APP, HttpAppService

__all__ = ["HTTP_APP", "HttpApiPlugin", "HttpAppService", "create_app"]
