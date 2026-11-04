"""Run inside the isolated Overleaf environment, after loading local credentials."""
import os
from pathlib import Path

from dotenv import dotenv_values


def main():
    env_file = Path(os.environ.get(
        "OVERLEAF_ENV_FILE", Path.cwd() / ".env",
    ))
    # Only Overleaf account settings are read; unrelated application secrets
    # and OS-specific cache paths are not passed to the third-party server.
    account_settings = (
        "OVERLEAF_SESSION", "OVERLEAF_GIT_TOKEN", "OVERLEAF_BASE_URL",
        "OVERLEAF_GIT_HOST", "OVERLEAF_GIT_AUTHOR_NAME", "OVERLEAF_GIT_AUTHOR_EMAIL",
    )
    if env_file.is_file():
        values = dotenv_values(env_file, interpolate=False)
        for key in account_settings:
            if values.get(key) and not os.environ.get(key):
                os.environ[key] = values[key]

    # Upstream resolves credentials and cache settings at import time.
    from overleaf_mcp.server import main as run_server
    run_server()


if __name__ == "__main__":
    main()
