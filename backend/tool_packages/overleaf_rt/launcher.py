"""向固定版本的实时服务传递账户设置；不读取或打印其他应用密钥。"""
import os
from pathlib import Path
import shutil
import subprocess

from dotenv import dotenv_values


def main():
    env_file = Path(os.environ.get("OVERLEAF_ENV_FILE", Path(__file__).resolve().parents[3] / ".env"))
    values = dotenv_values(env_file, interpolate=False) if env_file.is_file() else {}
    mapping = {"OVERLEAF_RT_URL": "OVERLEAF_URL",
               "OVERLEAF_RT_SESSION_COOKIE": "OVERLEAF_SESSION_COOKIE",
               "OVERLEAF_RT_CREDENTIALS_FILE": "OVERLEAF_CREDENTIALS_FILE"}
    for source, target in mapping.items():
        value = os.environ.get(source) or values.get(source)
        if value:
            os.environ[target] = value
    executable = shutil.which("overleaf-mcp-rt")
    if executable:
        args = [executable]
    else:
        npx = shutil.which("npx")
        if not npx:
            raise RuntimeError("请安装 Node.js 20 以上版本和 overleaf-mcp-rt@2.2.0")
        args = [npx, "-y", "overleaf-mcp-rt@2.2.0"]
    if os.name == "nt":
        raise SystemExit(subprocess.call(args))
    os.execv(args[0], args)


if __name__ == "__main__":
    main()

