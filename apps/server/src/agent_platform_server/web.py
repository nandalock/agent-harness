"""Serve the release's browser shell and allow SPA navigation."""
import os
from pathlib import Path

from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException


class BrowserShell(StaticFiles):
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            accepts_html = any(
                key == b"accept" and b"text/html" in value for key, value in scope["headers"]
            )
            first = path.replace("\\", "/").split("/", 1)[0]
            if exc.status_code != 404 or not accepts_html or first in {"api", "assets", "plugins"}:
                raise
            return await super().get_response("index.html", scope)


def mount_web(app) -> None:
    override = os.environ.get("MINIDSH_WEB_ROOT")
    directory = Path(override).expanduser().resolve() if override else Path(__file__).parent / "web"
    if not (directory / "index.html").is_file():
        raise RuntimeError(f"Browser shell missing at {directory}. Install the release wheels or check MINIDSH_WEB_ROOT.")
    app.mount("/", BrowserShell(directory=directory, html=True), name="minidsh-web")
