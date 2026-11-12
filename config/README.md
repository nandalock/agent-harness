# 配置目录

这里存放部署环境文件和配置模板。本地插件配置位于所选 [Profile](../docs/profiles.md)。

## 文件

| 文件 | 用途 | 是否提交 |
| --- | --- | --- |
| `local.env` | 本地运行配置（`python minidsh.py web/start/build/doctor`） | 否，gitignored |
| `local.env.example` | 本地配置模板；`setup` 用它生成 `local.env` | 是 |
| `docker.env` | Docker Compose 变量替换（`docker compose --env-file config/docker.env ...`） | 否，gitignored |
| `docker.env.example` | Docker 配置模板 | 是 |
| `cordis.yml.example` | 插件根配置模板 | 是 |
| `cordis.patch.yml.example` | 插件覆盖配置模板 | 是 |

## 本地运行

```sh
python minidsh.py setup          # 创建 config/local.env，生成随机 JWT_SECRET
# 按需编辑 config/local.env
python minidsh.py doctor
python minidsh.py web
```

环境变量优先级从高到低是进程环境、所选 profile 的 `local.env`（有此文件时）或 `config/local.env`、CLI 默认值。

## 前端 profile

前端不是写在 `config/` 里的，而是和 DSH 的 `dsh.client` 一样，由**前端包自己的
`package.json`** 声明 `dsh.frontend`：

```json
{
  "name": "@app/web2",
  "dsh": {
    "frontend": {
      "name": "web2",
      "dev": "npm run dev -- --host 127.0.0.1 --port {port}",
      "build": "npm run build",
      "start": "npm run preview -- --host 127.0.0.1 --port {port}",
      "dist": "dist",
      "requiresNode": true
    }
  }
}
```

`minidsh` 扫描 `packages/*/package.json` 发现 profile：

```sh
python minidsh.py web                        # 默认 web
python minidsh.py web --frontend web2        # 按 packages/client2 目录名或包名
python minidsh.py web --dir D:/jk/Code/web2  # 仓库外的前端包
```

## Docker

```sh
cp config/docker.env.example config/docker.env   # 首次
# 按需编辑 config/docker.env

python minidsh.py docker
# 等价于：
docker compose --env-file config/docker.env up -d --build
```

Compose 只从这个文件读取 `${...}` 变量；容器内的 `DATABASE_URL`、`JWT_SECRET`
由 `docker-compose.yml` 固定注入。

## 插件

首次启动可以直接使用内置清单。本地可把模板复制到 `~/.minidsh/profiles/<profile>/`，分别命名为 `cordis.yml` 和 `cordis.patch.yml`。Docker Compose 使用当前目录下的两个文件：

```sh
cp config/cordis.yml.example config/cordis.yml
cp config/cordis.patch.yml.example config/cordis.patch.yml
```

Compose 显式传递容器内的配置路径。可用 `PLUGIN_CONFIG` 指定另一个容器内的根配置文件。

## 迁移说明

旧版根目录的 `.env`、`.env.local` 仍会被兼容读取。如果源码启动原来使用仓库内的 `config/plugins.yaml`，请把它复制到所选 profile 的 `cordis.yml`：

```sh
mv .env config/docker.env
mv .env.local config/local.env
mkdir -p ~/.minidsh/profiles/web
cp config/plugins.yaml ~/.minidsh/profiles/web/cordis.yml
```

如果旧配置使用相对 `includes`，请一并复制引用文件并保留相对目录结构。

`python minidsh.py setup` 也会在 `config/local.env` 不存在时自动迁移旧的
`.env.local`。备份存放在 `~/.minidsh/backup/`。
