"""Run the ASGI carrier with uvicorn."""
import os

import uvicorn

from . import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("BACKEND_HOST", "0.0.0.0"),
        port=int(os.environ.get("BACKEND_PORT", "8000")),
    )
