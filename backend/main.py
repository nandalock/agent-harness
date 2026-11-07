"""ASGI proxy: starts the plugin runtime, then delegates to the HTTP plugin.

The FastAPI application itself is owned by ``agent-platform.http-api``. This
module contains no routes and no business startup; it only owns the process
lifecycle that uvicorn sees.
"""
import logging

logger = logging.getLogger(__name__)


class RuntimeASGIApp:
    def __init__(self):
        self._app = None

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self._lifespan(scope, receive, send)
            return
        if self._app is None:
            raise RuntimeError("HTTP plugin is not running")
        await self._app(scope, receive, send)

    async def _start(self):
        from backend.plugin_host import init_plugin_host
        from agent_platform_http_api import HTTP_APP

        host = await init_plugin_host()
        if host is None:
            raise RuntimeError("plugin runtime was not started")
        self._app = host.runtime.require(HTTP_APP)
        logger.info("HTTP/API plugin ready")

    async def _lifespan(self, scope, receive, send):
        startup = await receive()
        if startup["type"] != "lifespan.startup":
            raise RuntimeError("unexpected lifespan message")
        try:
            await self._start()
        except BaseException as exc:
            logger.exception("plugin runtime startup failed")
            await send({"type": "lifespan.startup.failed", "message": str(exc)})
            raise
        state = {"first": True}

        async def inner_receive():
            if state["first"]:
                state["first"] = False
                return startup
            return await receive()

        try:
            await self._app(scope, inner_receive, send)
        finally:
            from backend.plugin_host import close_plugin_host

            try:
                await close_plugin_host()
            except Exception as exc:  # noqa: BLE001
                logger.warning("plugin runtime shutdown failed: %s", exc)


app = RuntimeASGIApp()
