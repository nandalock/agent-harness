"""Cross-platform source deployment CLI (Python 3.12+, Node 20+).

    python minidsh.py setup
    python minidsh.py doctor
    python minidsh.py dev --mode hybrid
    python minidsh.py start --mode local
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def command(args, **kwargs):
    kwargs.setdefault("cwd", ROOT)
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def executable(name):
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"Missing {name}; install it and add it to PATH.")
    return path


def setup(args):
    if not PYTHON.exists():
        command([sys.executable, "-m", "venv", VENV])
    command([PYTHON, "-m", "pip", "install", "-r", "requirements-local.txt"])
    if args.rag:
        command([PYTHON, "-m", "pip", "install", "-r", "requirements-rag.txt"])
    if not args.backend_only:
        command([executable("npm"), "ci", "--no-audit", "--no-fund"], cwd=ROOT / "frontend")
    env_file = ROOT / args.env_file
    if not env_file.exists():
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text((ROOT / ".env.local.example").read_text(encoding="utf-8").replace(
            "JWT_SECRET=GENERATE_ON_SETUP", "JWT_SECRET=" + secrets.token_urlsafe(40)), encoding="utf-8")
    print(f"Setup complete. Configure {env_file.name}, then: python minidsh.py dev")
    return 0


def environment(args):
    from dotenv import dotenv_values

    env = os.environ.copy()
    path = ROOT / args.env_file
    if not path.is_file():
        raise RuntimeError(f"Missing {path.name}; run python minidsh.py setup first.")
    # Explicit shell environment takes precedence; never read Docker's .env.
    for key, value in dotenv_values(path).items():
        if value is not None:
            env.setdefault(key, value)
    data_home = Path(env.get("MINIDSH_HOME", str(Path.home() / ".minidsh"))).expanduser().resolve()
    defaults = {
        "DATABASE_URL": "postgresql://saas:saas@localhost:5432/saas",
        "REDIS_URL": "redis://localhost:6379/0",
        "SANDBOX_WORKSPACE_ROOT": str(data_home / "workspaces"),
        "SKILL_INSTALL_ROOT": str(data_home / "skills"),
        "PAPER_CACHE_DIR": str(data_home / "cache" / "paper-mcp"),
        "BUILTIN_MCP_PORT": "19001", "PAPER_MCP_PORT": "19002",
        "OVERLEAF_ENABLED": "false", "OVERLEAF_RT_ENABLED": "false",
        "MINIDSH_LOCAL": "true", "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8", "NEXT_TELEMETRY_DISABLED": "1",
        "NEXT_PUBLIC_API_URL": f"http://localhost:{args.backend_port}",
        "BACKEND_URL": f"http://127.0.0.1:{args.backend_port}",
        "CORS_ORIGINS": f"http://localhost:{args.frontend_port},http://127.0.0.1:{args.frontend_port}",
        "NEXT_DIST_DIR": ".next-local" if args.action == "dev" else ".next-local-build",
    }
    for key, value in defaults.items():
        env.setdefault(key, value)
    return env


def doctor(env, backend_only=False):
    """Check required capabilities without changing database or exposing DSNs."""
    import psycopg2

    for module in ("uvicorn", "backend.main", "agent_platform_default"):
        if importlib.util.find_spec(module) is None:
            raise RuntimeError(f"Missing {module}; run python minidsh.py setup.")
    try:
        with psycopg2.connect(env["DATABASE_URL"], connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM pg_available_extensions WHERE name IN ('vector', 'pg_trgm')")
                found = {row[0] for row in cur.fetchall()}
                if found != {"vector", "pg_trgm"}:
                    raise RuntimeError("PostgreSQL requires installed pgvector and pg_trgm extension files.")
    except psycopg2.Error:
        raise RuntimeError("PostgreSQL connection failed; check DATABASE_URL or run with --mode hybrid.") from None
    print("OK PostgreSQL + pgvector + pg_trgm")
    if not backend_only:
        version = subprocess.check_output([executable("node"), "--version"], text=True).strip()
        if int(version.lstrip("v").split(".")[0]) < 20:
            raise RuntimeError("Node.js 20+ is required.")
        executable("npm")
        if not (ROOT / "frontend/node_modules/next/package.json").is_file():
            raise RuntimeError("Frontend dependencies missing; run python minidsh.py setup.")
        print(f"OK Node {version} + frontend dependencies")
    import redis
    try:
        redis.Redis.from_url(env["REDIS_URL"], socket_connect_timeout=2, socket_timeout=2).ping()
        print("OK Redis")
    except redis.RedisError:
        print("NOTE Redis unavailable; semantic cache will miss. PostgreSQL remains required.")
    print("NOTE bash/python isolation uses Docker; chat and MCP do not require a backend container.")
    return 0


def infra():
    command([executable("docker"), "compose", "-f", "deploy/compose.infra.yaml", "up", "-d", "--wait", "db", "redis"])


def stop(process):
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        if process.poll() is not None:
            return
        # A non-interactive Windows console may not support control events.
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        else:
            raise
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def check_ports(args, env):
    ports = [args.backend_port, int(env["BUILTIN_MCP_PORT"]), int(env["PAPER_MCP_PORT"])]
    if not args.backend_only:
        ports.append(args.frontend_port)
    if len(set(ports)) != len(ports):
        raise RuntimeError("Backend, frontend and MCP ports must be distinct.")
    for port in ports:
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                raise RuntimeError(f"Port {port} is occupied or reserved. Stop the corresponding service or choose another port.") from None


def run(args, env):
    if args.mode == "hybrid":
        infra()
    doctor(env, args.backend_only)
    check_ports(args, env)
    children = []

    def spawn(argv, cwd):
        options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                   else {"start_new_session": True})
        process = subprocess.Popen([str(a) for a in argv], cwd=cwd, env=env, **options)
        children.append(process)
        return process

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupted)
    previous_break = signal.signal(signal.SIGBREAK, interrupted) if os.name == "nt" else None
    try:
        argv = [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(args.backend_port)]
        if args.action == "dev":
            argv += ["--reload", "--reload-dir", "backend", "--reload-dir", "packages"]
        backend = spawn(argv, ROOT)
        deadline = time.monotonic() + 120
        while True:
            if backend.poll() is not None:
                raise RuntimeError("Backend exited during startup; see logs above.")
            try:
                with urlopen(f"http://127.0.0.1:{args.backend_port}/health", timeout=2) as response:
                    if response.status == 200:
                        break
            except (OSError, URLError):
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("Backend readiness timed out; see plugin/database logs above.")
            time.sleep(0.4)
        if not args.backend_only:
            if args.action == "start" and not (ROOT / "frontend" / env["NEXT_DIST_DIR"] / "BUILD_ID").is_file():
                raise RuntimeError("Frontend production build missing; run python minidsh.py build first.")
            spawn([executable("node"), "node_modules/next/dist/bin/next", "dev" if args.action == "dev" else "start",
                   "-H", "127.0.0.1", "-p", str(args.frontend_port)], ROOT / "frontend")
        print(f"Backend ready: http://localhost:{args.backend_port}/docs", flush=True)
        if not args.backend_only:
            print(f"Frontend: http://localhost:{args.frontend_port} (Ctrl+C stops both processes)", flush=True)
        while all(p.poll() is None for p in children):
            time.sleep(0.5)
        raise RuntimeError("A service exited; stopping the other processes.")
    except KeyboardInterrupt:
        return 0
    finally:
        signal.signal(signal.SIGTERM, previous)
        if os.name == "nt":
            signal.signal(signal.SIGBREAK, previous_break)
        for process in reversed(children):
            stop(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["setup", "doctor", "dev", "build", "start", "infra", "docker"])
    parser.add_argument("--mode", choices=["local", "hybrid"], default="local")
    parser.add_argument("--env-file", default=".env.local")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=4000)
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--rag", action="store_true", help="Install optional reranker during setup")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error("Python 3.12+ is required")
    os.chdir(ROOT)
    try:
        if args.action == "setup":
            return setup(args)
        if args.action == "docker":
            command([executable("docker"), "compose", "up", "-d", "--build"])
            return 0
        if args.action == "infra":
            infra()
            return 0
        if not PYTHON.exists():
            raise RuntimeError("Run python minidsh.py setup first.")
        if Path(sys.prefix).resolve() != VENV.resolve():
            return subprocess.call([str(PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]], cwd=ROOT)
        env = environment(args)
        if args.action == "doctor":
            return doctor(env, args.backend_only)
        if args.action == "build":
            command([executable("node"), "node_modules/next/dist/bin/next", "build"], cwd=ROOT / "frontend", env=env)
            return 0
        return run(args, env)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
