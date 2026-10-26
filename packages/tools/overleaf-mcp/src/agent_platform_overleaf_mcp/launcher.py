"""Launch the upstream MCP server without importing SDK 2 into the backend."""
import os
from pathlib import Path


def main():
    configured = os.environ.get("OVERLEAF_MCP_PYTHON")
    if configured:
        python = Path(configured)
    elif os.name == "nt":
        python = Path.home() / ".codex/mcp/overleaf/venv/Scripts/python.exe"
    else:
        python = Path("/opt/overleaf-mcp/bin/python")
    if not python.is_file():
        raise SystemExit(
            "Overleaf MCP environment missing. Rebuild the backend image or "
            "set OVERLEAF_MCP_PYTHON to its isolated Python executable."
        )
    entrypoint = Path(__file__).with_name("entrypoint.py")
    env = os.environ.copy()
    cache = Path(env.setdefault(
        "OVERLEAF_TEMP_DIR", str(Path.home() / ".cache/overleaf-mcp"),
    ))
    cache.mkdir(parents=True, exist_ok=True)
    os.execve(str(python), [str(python), str(entrypoint)], env)


if __name__ == "__main__":
    main()
