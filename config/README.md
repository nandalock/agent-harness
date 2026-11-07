# 配置目录

所有运行配置都放在这里。根目录只保留 `docker-compose.yml` 和 `minidsh.py` 等入口文件。

## 文件

| 文件 | 用途 | 是否提交 |
| --- | --- | --- |
| `local.env` | 本地运行配置（`python minidsh.py web/start/build/doctor`） | 否，gitignored |
| `local.env.example` | 本地配置模板；`setup` 用它生成 `local.env` | 是 |
| `docker.env` | Docker Compose 变量替换（`docker compose --env-file config/docker.env ...`） | 否，gitignored |
| `docker.env.example` | Docker 配置模板 | 是 |
| `plugins.yaml` | 插件实例清单，运行时自动发现 | 否，gitignored |
| `plugins.yaml.example` | 插件配置模板 | 是 |

## 本地运行

```sh
python minidsh.py setup          # 创建 config/local.env，生成随机 JWT_SECRET
# 按需编辑 config/local.env
python minidsh.py doctor
python minidsh.py web
```

优先级：**进程环境变量 > `config/local.env` > CLI 默认值**。

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
python minidsh.py web --profile web2         # 按 packages/client2 目录名或包名
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

默认零配置。需要额外插件时：

```sh
cp config/plugins.yaml.example config/plugins.yaml
# 编辑后重启服务
```

发现顺序：`PLUGIN_CONFIG` 环境变量 → 仓库内的 `config/plugins.yaml`。
根目录 `plugins.yaml` 不再读取。

## 迁移说明

旧版根目录的 `.env`、`.env.local` 仍会被兼容读取；如果还有根目录 `plugins.yaml`，请手动移到 `config/plugins.yaml`（不再自动读取）：

```sh
mv .env config/docker.env
mv .env.local config/local.env
mv plugins.yaml config/plugins.yaml
```

`python minidsh.py setup` 也会在 `config/local.env` 不存在时自动迁移旧的
`.env.local`。备份存放在 `~/.minidsh/backup/`。
