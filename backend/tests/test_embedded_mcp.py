import signal
import socket
import unittest

import httpx
from fastapi import FastAPI

from backend.embedded_mcp import close_servers, start_server


class EmbeddedMcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_readiness_and_shutdown_do_not_replace_host_signal_handlers(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        app = FastAPI()

        @app.get("/ready")
        async def ready():
            return {"ready": True}

        before = signal.getsignal(signal.SIGINT)
        server, task = await start_server(app, port)
        try:
            self.assertIs(signal.getsignal(signal.SIGINT), before)
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://127.0.0.1:{port}/ready")
                self.assertEqual(response.json(), {"ready": True})
        finally:
            await close_servers([(server, task)])
        self.assertTrue(task.done())
        with socket.socket() as sock:
            self.assertNotEqual(sock.connect_ex(("127.0.0.1", port)), 0)


if __name__ == "__main__":
    unittest.main()
