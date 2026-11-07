"""Build the minidsh runtime wheelhouse and embed the production Web shell."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=".data/minidsh-release", type=Path)
    parser.add_argument("--no-build-isolation", action="store_true", help="use the build tools already installed in this environment")
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    frontend = ROOT / "packages" / "client"
    web = ROOT / "apps" / "server" / "src" / "agent_platform_server" / "web"
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if npm is None:
        parser.error("Node.js and npm are required to build a release")
    if not (frontend / "node_modules").is_dir():
        subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=frontend, check=True)
    subprocess.run(
        [npm, "run", "build", "--", "--outDir", str(web), "--emptyOutDir"], cwd=frontend,
        env={**os.environ, "MINIDSH_EMBEDDED_WEB": "1", "MINIDSH_CLIENT_ASSET_ROOT": str(ROOT / "packages")},
        check=True,
    )
    packages = [
        ROOT / line.removeprefix("-e ").strip()
        for line in (ROOT / "requirements-plugins.txt").read_text(encoding="utf-8").splitlines()
        if line.startswith("-e ")
    ]
    requirements = []
    for package in packages:
        project = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        requirements.append(f'{project["name"]}=={project["version"]}')
    requirements.extend(
        line for line in (ROOT / "requirements-local.txt").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith(("#", "-"))
    )
    with tempfile.TemporaryDirectory(dir=output) as staging:
        build_flags = ["--no-build-isolation"] if args.no_build_isolation else []
        subprocess.run(
            [sys.executable, "-m", "pip", "wheel", "--no-deps", *build_flags,
             "--wheel-dir", staging, *map(str, packages)],
            cwd=ROOT, check=True,
        )
        for wheel in Path(staging).glob("*.whl"):
            os.replace(wheel, output / wheel.name)
        manifest = Path(staging) / "runtime-requirements.txt"
        manifest.write_text("\n".join(requirements) + "\n", encoding="utf-8")
        os.replace(manifest, output / manifest.name)
    print(f"minidsh wheelhouse: {output}")


if __name__ == "__main__":
    main()
