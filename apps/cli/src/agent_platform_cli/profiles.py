"""Manage minidsh installations and plugins in user-owned profiles."""
from __future__ import annotations

import argparse
import configparser
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from zipfile import ZipFile
import venv

from dotenv import dotenv_values
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename
import yaml

from agent_platform_plugin_runtime import load_yaml_config
from agent_platform_plugin_sdk import PLUGIN_ENTRY_POINT_GROUP, PluginConfiguration, PluginEntry


def atomic_write(path: Path, content: str) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Profile:
    def __init__(self, name: str):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
            raise ValueError("Profile names use lowercase letters, digits, underscores and hyphens")
        home = Path(os.environ.get("MINIDSH_HOME", Path.home() / ".minidsh")).expanduser().resolve()
        self.root = home / "profiles" / name
        self.venv = self.root / ".venv"
        self.python = self.venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.config = self.root / "plugins.yaml"
        self.env_file = self.root / "local.env"
        self.lockfile = self.root / "requirements.lock"
        self.base = self.root / "runtime.lock"

    @contextmanager
    def exclusive(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / ".operation.lock").open("a+b") as handle:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError(f"Profile is in use: {self.root.name}. Stop its minidsh process first.") from exc
            yield

    def environment(self) -> dict[str, str]:
        env = os.environ.copy()
        for key, value in dotenv_values(self.env_file).items():
            if value is not None:
                env.setdefault(key, value)
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONPATH", None)
        env.update({
            "PLUGIN_CONFIG": str(self.config),
            "AGENT_PLATFORM_ENV": str(self.env_file),
            "PYTHONUTF8": "1",
            "PYTHONNOUSERSITE": "1",
            "VIRTUAL_ENV": str(self.venv),
            "PATH": str(self.python.parent) + os.pathsep + env.get("PATH", ""),
        })
        defaults = {
            "SANDBOX_WORKSPACE_ROOT": str(self.root / "workspaces"),
            "SKILL_INSTALL_ROOT": str(self.root / "skills"),
            "PAPER_CACHE_DIR": str(self.root / "cache" / "paper-mcp"),
            "OVERLEAF_ENV_FILE": str(self.env_file),
            "OVERLEAF_ENABLED": "false",
            "OVERLEAF_RT_ENABLED": "false",
            "BUILTIN_MCP_PORT": "19001",
            "PAPER_MCP_PORT": "19002",
            "MINIDSH_LOCAL": "true",
        }
        for key, value in defaults.items():
            env.setdefault(key, value)
        return env

    def execute(self, *args, capture=False, input=None, env=None):
        return subprocess.run(
            [str(self.python), *map(str, args)], cwd=self.root, env=env or self.environment(),
            check=True, stdout=subprocess.PIPE if capture else None, text=True,
            encoding="utf-8", input=input,
        )

    def worker(self, action):
        return json.loads(self.execute("-m", "agent_platform_cli._profile_worker", action, capture=True).stdout)

    def inventory(self):
        return {row["distribution"]: row for row in self.worker("inventory")}

    def refresh_lock(self) -> None:
        rows = self.inventory()
        atomic_write(self.lockfile, "".join(f"{name}=={rows[name]['version']}\n" for name in sorted(rows)))

    def require_initialized(self) -> None:
        if not self.base.is_file() or not self.python.is_file():
            raise RuntimeError(f"Run minidsh profile init --profile {self.root.name} --wheelhouse <release-dir> first.")

    def init(self, wheelhouse: Path) -> None:
        requirements = wheelhouse / "runtime-requirements.txt"
        if not requirements.is_file():
            raise ValueError(f"Release manifest not found: {requirements}")
        with self.exclusive():
            if self.base.is_file():
                self.require_initialized()
                print(self.root)
                return
            if not self.config.exists():
                atomic_write(self.config, "version: 1\nplugins: []\n")
            if not self.env_file.exists():
                atomic_write(self.env_file, "# Set your database and optional model credentials here.\n"
                             "DATABASE_URL=postgresql://saas:your_password@127.0.0.1:5432/saas\n")
            if not self.python.is_file():
                venv.EnvBuilder(with_pip=True).create(self.venv)
            self.execute("-m", "pip", "install", "--find-links", wheelhouse, "-r", requirements)
            self.execute("-m", "pip", "check")
            self.refresh_lock()
            atomic_write(self.base, self.lockfile.read_text(encoding="utf-8"))
            print(self.root)

    def validate_and_save(self, entries) -> None:
        config = PluginConfiguration(plugins=tuple(entries))
        self.execute("-m", "agent_platform_cli._profile_worker", "validate", input=config.model_dump_json())
        atomic_write(self.config, yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False, allow_unicode=True))

    def list_plugins(self) -> None:
        config = self.worker("config")
        configured = set()
        for row in config["plugins"]:
            configured.add(row["name"])
            state = "disabled" if row["disabled"] else "enabled"
            print(f'{row["id"]:<26} {state:<12} {row["name"]}')
        for dist in self.inventory().values():
            for entry in dist["entries"]:
                if entry not in configured:
                    print(f'{"":26} {"installed":12} {entry} ({dist["distribution"]} {dist["version"]})')

    def toggle(self, plugin_id: str, *, disabled: bool) -> None:
        entries = list(load_yaml_config(self.config).plugins)
        current = PluginConfiguration.model_validate(self.worker("config"))
        target = next((row for row in current.plugins if row.id == plugin_id), None)
        if target is None:
            raise ValueError(f"Unknown plugin ID: {plugin_id}. Use minidsh plugin list.")
        if target.disabled == disabled:
            return
        entries = [row for row in entries if row.id != plugin_id]
        entries.append(target.model_copy(update={"disabled": disabled}))
        self.validate_and_save(entries)

    def install(self, source: str, *, entry_name: str | None, plugin_id: str | None,
                config: dict, wheelhouse: Path | None, disabled: bool = False) -> None:
        local = Path(source).expanduser()
        if local.is_file():
            source = str(local.resolve())
        links = ["--find-links", wheelhouse] if wheelhouse is not None else []
        with tempfile.TemporaryDirectory(prefix="minidsh-plugin-") as staging:
            self.execute("-m", "pip", "download", "--no-deps", "--only-binary=:all:", "--dest", staging,
                         *links, "--", source)
            wheels = list(Path(staging).glob("*.whl"))
            if len(wheels) != 1:
                raise ValueError("Specify one plugin wheel or package requirement")
            wheel = wheels[0]
            distribution, _, _, _ = parse_wheel_filename(wheel.name)
            installed = self.inventory()
            if distribution in installed:
                raise ValueError(f"{distribution} is already installed in this profile")
            entries = wheel_entries(wheel)
            if entry_name is None and len(entries) == 1:
                entry_name = entries[0]
            if entry_name not in entries:
                raise ValueError("Select a declared entry with --entry: " + (", ".join(entries) or "(none)"))
            if any(entry in row["entries"] for row in installed.values() for entry in entries):
                raise ValueError("This wheel collides with an installed plugin entry point")
            candidate = PluginEntry(id=plugin_id or entry_name, name=entry_name, config=config, disabled=disabled)
            overrides = load_yaml_config(self.config).plugins
            effective = PluginConfiguration.model_validate(self.worker("config")).plugins
            if any(row.id == candidate.id for row in effective):
                raise ValueError(f"Plugin ID already in use: {candidate.id}")
            self.refresh_lock()
            try:
                self.execute("-m", "pip", "install", "--constraint", self.lockfile, *links, wheel)
                try:
                    self.validate_and_save((*overrides, candidate))
                except Exception:
                    self.execute("-m", "pip", "uninstall", "--yes", distribution)
                    raise
            finally:
                self.refresh_lock()

    def remove(self, distribution: str) -> None:
        distribution = canonicalize_name(distribution)
        installed = self.inventory()
        dist = installed.get(distribution)
        if dist is None or not dist["entries"]:
            raise ValueError(f"No installed plugin distribution: {distribution}")
        protected = {line.partition("==")[0] for line in self.base.read_text(encoding="utf-8").splitlines()}
        if distribution in protected:
            raise ValueError("Runtime packages are managed by the profile. Disable the plugin by ID instead.")
        for name, row in installed.items():
            if name == distribution:
                continue
            for raw in row["requires"]:
                requirement = Requirement(raw)
                if canonicalize_name(requirement.name) == distribution and (
                    requirement.marker is None or requirement.marker.evaluate()
                ):
                    raise ValueError(f"{name} depends on {distribution}")
        entries = [
            row for row in load_yaml_config(self.config).plugins
            if row.name not in dist["entries"]
        ]
        self.validate_and_save(entries)
        try:
            self.execute("-m", "pip", "uninstall", "--yes", distribution)
        finally:
            self.refresh_lock()


def wheel_entries(wheel: Path) -> tuple[str, ...]:
    with ZipFile(wheel) as archive:
        entries = [name for name in archive.namelist() if name.endswith(".dist-info/entry_points.txt")]
        if len(entries) != 1:
            return ()
        config = configparser.ConfigParser(interpolation=None)
        config.optionxform = str
        config.read_string(archive.read(entries[0]).decode("utf-8"))
        return tuple(config[PLUGIN_ENTRY_POINT_GROUP]) if config.has_section(PLUGIN_ENTRY_POINT_GROUP) else ()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="minidsh", description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    def profile_option(command):
        command.add_argument("--profile", default="web")
        return command

    profiles = commands.add_parser("profile", help="initialize an application profile")
    profile_commands = profiles.add_subparsers(dest="action", required=True)
    init = profile_option(profile_commands.add_parser("init"))
    init.add_argument("--wheelhouse", type=Path, required=True)

    web = profile_option(commands.add_parser("web", help="start the profile's Web application"))
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=4000)
    run = profile_option(commands.add_parser("run", help="run one Agent turn in the profile"))
    run.add_argument("question")
    run.add_argument("--agent", required=True)
    run.add_argument("--tenant-id", type=int, default=1)

    plugins = commands.add_parser("plugin", help="manage profile plugins")
    plugin_commands = plugins.add_subparsers(dest="action", required=True)
    profile_option(plugin_commands.add_parser("list"))
    install = profile_option(plugin_commands.add_parser("install"))
    install.add_argument("source")
    install.add_argument("--entry")
    install.add_argument("--id")
    install.add_argument("--config", default="{}", help="initial plugin config as a JSON object")
    install.add_argument("--wheelhouse", type=Path)
    install.add_argument("--disabled", action="store_true", help="install without activating the entry")
    for action in ("enable", "disable"):
        profile_option(plugin_commands.add_parser(action)).add_argument("id")
    profile_option(plugin_commands.add_parser("remove")).add_argument("distribution")
    return root


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        profile = Profile(args.profile)
        if args.command == "profile":
            profile.init(args.wheelhouse.expanduser().resolve())
            return 0
        profile.require_initialized()
        if args.command == "plugin" and args.action == "list":
            profile.list_plugins()
            return 0
        with profile.exclusive():
            if args.command == "web":
                env = {**profile.environment(), "MINIDSH_SERVE_WEB": "1"}
                profile.execute("-m", "uvicorn", "agent_platform_server:app",
                                "--host", args.host, "--port", args.port, env=env)
            elif args.command == "run":
                profile.execute("-m", "agent_platform_cli", "run", "--agent", args.agent,
                                "--tenant-id", args.tenant_id, "--", args.question)
            elif args.action == "install":
                config = json.loads(args.config)
                if not isinstance(config, dict):
                    raise ValueError("--config must be a JSON object")
                wheelhouse = args.wheelhouse.expanduser().resolve() if args.wheelhouse else None
                profile.install(args.source, entry_name=args.entry, plugin_id=args.id,
                                config=config, wheelhouse=wheelhouse, disabled=args.disabled)
            elif args.action in ("enable", "disable"):
                profile.toggle(args.id, disabled=args.action == "disable")
            elif args.action == "remove":
                profile.remove(args.distribution)
        return 0
    except KeyboardInterrupt:
        return 130
    except subprocess.CalledProcessError as exc:
        # Subprocess diagnostics are already visible. Keep arguments and credentials out of this summary.
        print(f"minidsh: profile operation failed (exit {exc.returncode})", file=sys.stderr)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"minidsh: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
