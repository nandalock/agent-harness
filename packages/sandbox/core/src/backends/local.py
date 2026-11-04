"""Same-host confinement: Windows restricted tokens, Linux bwrap, macOS Seatbelt.

The Windows runner is the pinned MIT-licensed DeepSeek Harness implementation.
It restricts writes, not reads/network, and reports partial enforcement.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Sequence

from ..errors import SandboxUnavailableError
from ..provider import ConfinedArgv, RunnerFailureRule, SandboxProvider
from ..vocabulary import SandboxPolicy

NATIVE_DIR = Path(__file__).resolve().parents[1] / "native"


class LocalProvider(SandboxProvider):
    backend = "local"

    def confine(self, argv: Sequence[str], policy: SandboxPolicy) -> ConfinedArgv:
        if not argv:
            raise ValueError("argv cannot be empty")
        root = Path(policy.workspace_root).resolve(strict=True)
        if not root.is_dir() or not Path(policy.workspace_root).is_absolute():
            raise SandboxUnavailableError(policy.mode, "Workspace must be an existing absolute directory")
        if sys.platform == "win32":
            if policy.mode == "workspace-write" and any(Path(p).resolve() != root for p in policy.write_roots):
                raise SandboxUnavailableError(policy.mode, "Windows local confinement supports one writable workspace; use Docker for extra write roots")
            node = shutil.which("node")
            runner = NATIVE_DIR / "node_modules/@deepseek-ai/dsh-sandbox-windows-acl/lib/runner.js"
            if not node or not runner.is_file():
                raise SandboxUnavailableError(policy.mode, "Windows sandbox runner missing; run python minidsh.py setup")
            return ConfinedArgv(
                argv=[node, str(runner), "--workspace", str(root), "--temp", tempfile.gettempdir(),
                      "--mode", policy.mode, "--", *argv],
                enforcement="partial", denial_signatures=("is denied", "permission denied", "unauthorizedaccess", "拒绝访问"),
                runner_failure_rules=(RunnerFailureRule(fatal_signatures=("windows-acl-run:", "cannot find module", "cannot find package"), allowed_exit_codes=(127, 1)),),
            )
        if sys.platform.startswith("linux"):
            runner = shutil.which("bwrap")
            if not runner:
                raise SandboxUnavailableError(policy.mode, "Linux local confinement requires bubblewrap (bwrap)")
            wrapped = [runner, "--die-with-parent", "--new-session", "--ro-bind", "/", "/", "--proc", "/proc", "--dev", "/dev"]
            if policy.mode == "workspace-write":
                for directory in (str(root), *policy.write_roots):
                    path = str(Path(directory).resolve(strict=True))
                    wrapped += ["--bind", path, path]
                wrapped += ["--tmpfs", "/tmp"]
            wrapped += ["--chdir", str(root), "--", *argv]
            return ConfinedArgv(wrapped, "full", ("read-only file system", "permission denied"),
                                (RunnerFailureRule(fatal_signatures=("bwrap:",)),))
        if sys.platform == "darwin":
            runner = shutil.which("sandbox-exec")
            if not runner:
                raise SandboxUnavailableError(policy.mode, "macOS Seatbelt runner is unavailable")
            profile = '(version 1)(allow default)(deny file-write*)'
            if policy.mode == "workspace-write":
                for path in (str(root), tempfile.gettempdir(), *policy.write_roots):
                    profile += f'(allow file-write* (subpath {json.dumps(str(Path(path).resolve(strict=True)))}))'
            return ConfinedArgv([runner, "-p", profile, *argv], "full", ("operation not permitted", "permission denied"),
                                (RunnerFailureRule(fatal_signatures=("sandbox-exec:",)),))
        raise SandboxUnavailableError(policy.mode, f"Unsupported native sandbox platform: {sys.platform}")


def host_argv(argv: Sequence[str]) -> list[str]:
    """Resolve real host interpreters without changing tool argument semantics."""
    result = list(argv)
    if result[0] == "python":
        result[0] = sys.executable
    elif result[0] == "bash":
        bash = os.environ.get("MINIDSH_BASH") or shutil.which("bash")
        if os.name == "nt" and bash and "system32" in bash.lower():
            git = shutil.which("git")
            candidates = [
                Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe",
                Path("D:/Program Files/Git/bin/bash.exe"),
            ]
            if git:
                candidates.append(Path(git).parent.parent / "bin/bash.exe")
            bash = next((str(p) for p in candidates if p.is_file()), None)
        if not bash:
            raise ValueError("Host bash is unavailable; configure MINIDSH_BASH or use powershell on Windows")
        result[0] = bash
    return result
