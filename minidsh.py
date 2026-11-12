"""Cross-platform source deployment CLI (Python 3.12+, Node 20+).

    python minidsh.py setup
    python minidsh.py doctor
    python minidsh.py web                 # backend + web plugin shell (dev)
    python minidsh.py web --prod          # build, then serve the web shell
    python minidsh.py web --mode hybrid   # Docker only for PostgreSQL/Redis

Deployment environment files live in config/:
    config/local.env   local processes (this CLI)
    config/docker.env  Docker Compose variable substitution
Plugin configuration comes from ~/.minidsh/profiles/<profile>/cordis*.yml.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib.util
import json
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
DEFAULT_ENV_FILE = "config/local.env"
WEB_SHELL_PORT = 4100


def command(args, **kwargs):
    kwargs.setdefault("cwd", ROOT)
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def executable(name):
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"Missing {name}; install it and add it to PATH.")
    return path


def shell_command(command: str, **kwargs):
    """Run a profile-provided shell command (npm, pnpm, vite, ...)."""
    kwargs.setdefault("cwd", ROOT)
    return subprocess.run(command, shell=True, check=True, **kwargs)


@dataclass(frozen=True)
class FrontendProfile:
    """One replaceable web frontend (packages/client, web2, ...)."""

    name: str
    dir: Path
    install: str
    dev: str
    build: str
    start: str
    dist: str | None = "dist"
    requires_node: bool = True


def _default_frontend_profile(name: str = "web") -> FrontendProfile:
    return FrontendProfile(
        name=name,
        dir=(ROOT / "packages" / "client").resolve(),
        install="npm ci --no-audit --no-fund",
        dev="npm run dev -- --host 127.0.0.1 --port {port}",
        build="npm run build",
        start="npm run preview -- --host 127.0.0.1 --port {port}",
        dist="dist",
        requires_node=True,
    )


def _frontend_from_package(
    directory: Path, manifest: dict, package_name: str
) -> FrontendProfile:
    base = _default_frontend_profile(str(manifest.get("name") or directory.name))
    dist = manifest.get("dist", base.dist)
    return FrontendProfile(
        name=str(manifest.get("name") or directory.name),
        dir=directory.resolve(),
        install=str(manifest.get("install", base.install)),
        dev=str(manifest.get("dev", base.dev)),
        build=str(manifest.get("build", base.build)),
        start=str(manifest.get("start", base.start)),
        dist=str(dist) if dist else None,
        requires_node=bool(
            manifest.get("requiresNode", manifest.get("requires_node", base.requires_node))
        ),
    )


def _read_frontend_package(directory: Path) -> tuple[dict, str] | None:
    package_file = directory / "package.json"
    if not package_file.is_file():
        return None
    try:
        data = json.loads(package_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read {package_file}: {exc}") from None
    dsh = data.get("dsh")
    if not isinstance(dsh, dict):
        return None
    manifest = dsh.get("frontend")
    if not isinstance(manifest, dict):
        return None
    return manifest, str(data.get("name", directory.name))


def discover_frontend_profiles() -> dict[str, FrontendProfile]:
    """Scan packages/*/package.json for `dsh.frontend` declarations."""
    packages = ROOT / "packages"
    profiles: dict[str, FrontendProfile] = {}
    if not packages.is_dir():
        return profiles
    for child in sorted(packages.iterdir()):
        if not child.is_dir():
            continue
        found = _read_frontend_package(child)
        if found is None:
            continue
        manifest, package_name = found
        profile = _frontend_from_package(child, manifest, package_name)
        for alias in {child.name, package_name, str(manifest.get("name", ""))}:
            if not alias:
                continue
            existing = profiles.get(alias)
            if existing is not None and existing.dir != profile.dir:
                raise RuntimeError(
                    f"Duplicate frontend profile alias {alias!r}: {existing.dir} and {profile.dir}"
                )
            profiles[alias] = profile
    return profiles


def load_frontend_profile(
    name: str | None = None, directory: str | Path | None = None
) -> FrontendProfile:
    """Discover a frontend from packages/*/package.json `dsh.frontend`.

    This mirrors DSH's package-declared client/bundle manifests. There is no
    central frontend config file: `--frontend web2` matches a package directory
    or package name, and `--dir` points at a package outside packages/.
    """
    if directory is not None:
        path = Path(directory).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        path = path.resolve()
        found = _read_frontend_package(path)
        if found is None:
            raise RuntimeError(f"{path} does not declare dsh.frontend in package.json")
        manifest, package_name = found
        return _frontend_from_package(path, manifest, package_name)

    profiles = discover_frontend_profiles()
    selected = name or "web"
    if selected in profiles:
        return profiles[selected]
    if selected == "web" and not profiles:
        return _default_frontend_profile()
    available = ", ".join(sorted(profiles)) or "(none)"
    raise RuntimeError(
        f"Unknown frontend profile {selected!r}; available: {available}. "
        "Declare dsh.frontend in the package's package.json, or pass --dir."
    )


def setup(args, profile: FrontendProfile):
    if not PYTHON.exists():
        command([sys.executable, "-m", "venv", VENV])
    command([PYTHON, "-m", "pip", "install", "-r", "requirements-local.txt"])
    if args.rag:
        command([PYTHON, "-m", "pip", "install", "-r", "requirements-rag.txt"])
    if not args.backend_only:
        if not profile.dir.is_dir():
            raise RuntimeError(f"Frontend profile {profile.name!r} directory not found: {profile.dir}")
        if profile.requires_node:
            executable("npm")
        shell_command(profile.install, cwd=profile.dir)
    if os.name == "nt":
        command([executable("npm"), "ci", "--no-audit", "--no-fund"], cwd=ROOT / "packages/sandbox/core/src/native")
    env_file = ROOT / args.env_file
    if not env_file.exists():
        env_file.parent.mkdir(parents=True, exist_ok=True)
        legacy = ROOT / ".env.local" if args.env_file == DEFAULT_ENV_FILE else None
        if legacy is not None and legacy.is_file():
            # Compatibility: migrate the old root .env.local without touching it.
            env_file.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"Migrated {legacy.name} -> {_display_path(env_file)}")
        else:
            template = ROOT / "config" / "local.env.example"
            env_file.write_text(template.read_text(encoding="utf-8").replace(
                "JWT_SECRET=GENERATE_ON_SETUP", "JWT_SECRET=" + secrets.token_urlsafe(40)), encoding="utf-8")
    print(f"Setup complete. Configure {_display_path(env_file)}, then: python minidsh.py web")
    return 0


def _env_file(args) -> Path:
    """Resolve the local env file, accepting the legacy root .env.local."""
    path = ROOT / args.env_file
    if path.is_file():
        return path
    legacy = ROOT / ".env.local"
    if args.env_file == DEFAULT_ENV_FILE and legacy.is_file():
        print(
            f"NOTE: {legacy.name} is deprecated; move it to "
            f"{DEFAULT_ENV_FILE} (config/README.md).",
            file=sys.stderr,
        )
        return legacy
    raise RuntimeError(
        f"Missing {args.env_file}; run python minidsh.py setup first."
    )


def environment(args):
    from agent_platform_cli.profiles import Profile
    from dotenv import dotenv_values

    env = os.environ.copy()
    name = getattr(args, "profile", "web")
    profile = Profile(name)
    path = profile.env_file if args.env_file == DEFAULT_ENV_FILE and profile.env_file.is_file() else _env_file(args)
    # Explicit shell environment takes precedence; never read Docker's env file.
    for key, value in dotenv_values(path).items():
        if value is not None:
            env.setdefault(key, value)
    profile = Profile(name, home=env.get("MINIDSH_HOME"))
    env.update(profile.configuration_environment())
    defaults = {
        "DATABASE_URL": "postgresql://saas:saas@127.0.0.1:5432/saas",
        "REDIS_URL": "redis://localhost:6379/0",
        **profile.data_environment(),
        "AGENT_PLATFORM_ENV": str(path.resolve()),
        "BUILTIN_MCP_PORT": "19001", "PAPER_MCP_PORT": "19002",
        "SANDBOX_BACKEND": "local",
        "OVERLEAF_ENABLED": "false", "OVERLEAF_RT_ENABLED": "false",
        # The isolated Overleaf entrypoints read credentials from this file.
        "OVERLEAF_ENV_FILE": str(path.resolve()),
        "MINIDSH_LOCAL": "true", "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "NEXT_PUBLIC_API_URL": f"http://127.0.0.1:{args.backend_port}",
        "BACKEND_URL": f"http://127.0.0.1:{args.backend_port}",
        # The standalone web shell dev server uses 4100; minidsh itself uses frontend_port.
        "CORS_ORIGINS": (
            f"http://localhost:{args.frontend_port},http://127.0.0.1:{args.frontend_port},"
            f"http://localhost:{WEB_SHELL_PORT},http://127.0.0.1:{WEB_SHELL_PORT}"
        ),
    }
    for key, value in defaults.items():
        env.setdefault(key, value)
    return env


def doctor(env, backend_only=False, profile: FrontendProfile | None = None):
    """Check required capabilities without changing database or exposing DSNs."""
    profile = profile or _default_frontend_profile()
    import psycopg2

    for module in ("uvicorn", "agent_platform_server", "agent_platform_default"):
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
        if not profile.dir.is_dir():
            raise RuntimeError(f"Frontend profile {profile.name!r} directory not found: {profile.dir}")
        if profile.requires_node:
            version = subprocess.check_output([executable("node"), "--version"], text=True).strip()
            if int(version.lstrip("v").split(".")[0]) < 20:
                raise RuntimeError("Node.js 20+ is required.")
            executable("npm")
            if not (profile.dir / "node_modules").is_dir():
                raise RuntimeError(
                    f"Frontend dependencies missing for {profile.name!r}; "
                    f"run python minidsh.py setup --frontend {profile.name}."
                )
            print(f"OK Node {version} + frontend profile {profile.name} ({_display_path(profile.dir)})")
        else:
            print(f"OK frontend profile {profile.name} ({_display_path(profile.dir)})")
    import redis
    try:
        redis.Redis.from_url(env["REDIS_URL"], socket_connect_timeout=2, socket_timeout=2).ping()
        print("OK Redis")
    except redis.RedisError:
        print("NOTE Redis unavailable; semantic cache will miss. PostgreSQL remains required.")
    print(f"Sandbox backend: {env['SANDBOX_BACKEND']} (native confinement fails closed when OS support is unavailable)")
    return 0


def infra():
    command([executable("docker"), "compose", "-f", "deploy/compose.infra.yaml", "up", "-d", "--wait", "db", "redis"])


def docker_env_file() -> Path | None:
    """Canonical Docker env file, with a legacy root .env fallback."""
    canonical = ROOT / "config" / "docker.env"
    if canonical.is_file():
        return canonical
    legacy = ROOT / ".env"
    if legacy.is_file():
        print(
            f"NOTE: {legacy.name} is deprecated; move it to "
            f"{_display_path(canonical)} (config/README.md).",
            file=sys.stderr,
        )
        return legacy
    return None


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


def run(args, env, profile: FrontendProfile):
    if args.mode == "hybrid":
        infra()
    doctor(env, args.backend_only, profile)
    check_ports(args, env)
    children = []

    def spawn(argv, cwd):
        options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                   else {"start_new_session": True})
        process = subprocess.Popen([str(a) for a in argv], cwd=cwd, env=env, **options)
        children.append(process)
        return process

    def spawn_shell(command, cwd):
        argv = ["cmd", "/c", command] if os.name == "nt" else ["sh", "-c", command]
        return spawn(argv, cwd)

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupted)
    previous_break = signal.signal(signal.SIGBREAK, interrupted) if os.name == "nt" else None
    try:
        argv = [sys.executable, "-m", "uvicorn", "agent_platform_server:app", "--host", "127.0.0.1", "--port", str(args.backend_port)]
        if os.name == "nt":
            # uvicorn 在 Windows 上只要启用 --reload / 多 worker 就会选
            # SelectorEventLoop（uvicorn.config.use_subprocess=True）。Selector
            # 不支持 asyncio.create_subprocess_exec，沙箱里的 bash/python/
            # powershell 会全部变成 tool.unavailable。--loop none 让 asyncio
            # 使用平台默认的 ProactorEventLoop。
            argv += ["--loop", "none"]
        if args.action == "dev":
            argv += ["--reload", "--reload-dir", "apps", "--reload-dir", "packages"]
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
            if not profile.dir.is_dir():
                raise RuntimeError(f"Frontend profile {profile.name!r} directory not found: {profile.dir}")
            if args.action == "start" and profile.dist:
                dist_index = profile.dir / profile.dist / "index.html"
                if not dist_index.is_file():
                    raise RuntimeError(
                        f"Frontend build missing for {profile.name!r}; run python minidsh.py build --frontend {profile.name} first."
                    )
            command = (profile.start if args.action == "start" else profile.dev).format(port=args.frontend_port)
            spawn_shell(command, profile.dir)
        print(f"Backend ready: http://localhost:{args.backend_port}/docs", flush=True)
        if not args.backend_only:
            print(f"Web ({profile.name}): http://localhost:{args.frontend_port} (Ctrl+C stops both processes)", flush=True)
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
    parser.add_argument("action", choices=["setup", "doctor", "web", "dev", "build", "start", "infra", "docker"])
    parser.add_argument("--mode", choices=["local", "hybrid"], default="local")
    parser.add_argument("--prod", action="store_true",
                        help="with web: build and serve the built shell (vite preview)")
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE,
                        help=f"local env file (default: {DEFAULT_ENV_FILE})")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=4000)
    parser.add_argument("--plugin-patch", type=Path, help="override the plugin configuration")
    parser.add_argument("--profile", default="web", help="runtime profile under MINIDSH_HOME/profiles (default: web)")
    parser.add_argument("--frontend", default=None,
                        help="frontend profile declared by packages/*/package.json dsh.frontend (default: web)")
    parser.add_argument("--dir", "--frontend-dir", dest="frontend_dir", default=None,
                        help="frontend package directory declaring dsh.frontend")
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--rag", action="store_true", help="Install optional reranker during setup")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error("Python 3.12+ is required")
    if args.prod and args.action != "web":
        parser.error("--prod is only valid with the web action")
    if args.action == "web" and args.backend_only:
        parser.error("web starts the frontend; use 'dev --backend-only' for backend-only")
    if args.frontend and args.frontend_dir:
        parser.error("use either --frontend or --dir, not both")
    if args.plugin_patch is not None:
        args.plugin_patch = args.plugin_patch.expanduser().resolve()
    os.chdir(ROOT)
    try:
        if args.action == "setup":
            return setup(args, load_frontend_profile(args.frontend, args.frontend_dir))
        if args.action == "docker":
            argv = [executable("docker"), "compose"]
            env_file = docker_env_file()
            if env_file is not None:
                argv += ["--env-file", str(env_file)]
            command([*argv, "up", "-d", "--build"])
            return 0
        if args.action == "infra":
            infra()
            return 0
        if not PYTHON.exists():
            raise RuntimeError("Run python minidsh.py setup first.")
        if Path(sys.prefix).resolve() != VENV.resolve():
            arguments = sys.argv[1:]
            if args.plugin_patch is not None:
                arguments = [*arguments, "--plugin-patch", str(args.plugin_patch)]
            return subprocess.call([str(PYTHON), str(Path(__file__).resolve()), *arguments], cwd=ROOT)
        web_prod = args.action == "web" and args.prod
        if args.action == "web":
            args.action = "start" if web_prod else "dev"
        env = environment(args)
        if args.plugin_patch is not None:
            env["MINIDSH_PLUGIN_PATCH"] = str(args.plugin_patch)
        profile = (_default_frontend_profile() if args.backend_only
                   else load_frontend_profile(args.frontend, args.frontend_dir))
        if args.action == "doctor":
            return doctor(env, args.backend_only, profile)
        if args.action == "build":
            shell_command(profile.build, cwd=profile.dir, env=env)
            return 0
        if web_prod:
            # One-command production web startup: always rebuild before preview.
            shell_command(profile.build, cwd=profile.dir, env=env)
        return run(args, env, profile)
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
