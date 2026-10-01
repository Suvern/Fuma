# Backend

Python 3.13、FastAPI / Pydantic、SQLAlchemy / psycopg、PostgreSQL、Celery / Redis。配置仅从进程环境读取；用户在本机使用 `uv run --env-file ../.env ...` 显式加载配置。

## 模块

| 路径 | 职责 |
| --- | --- |
| `app/api` | 管理、前台、CI HTTP 接口；Cookie / CSRF / 版本条件 |
| `app/api/contracts.py` | 由 `idl/openapi.yaml` 生成的 DTO，不手动修改 |
| `app/core` | Settings、标准错误、脱敏与日志配置 |
| `app/domains/auth` | Argon2 密码、hash 会话、一次性初始化与持久化限流 |
| `app/domains/applications` | App、平台及仓库绑定 |
| `app/domains/github` | PAT 加密、仓库与完整 Release 快照 |
| `app/domains/distribution` | 飞书可信租户、机器人群、Debug 缓存、下载授权、Actions 和投递 |
| `app/domains/audit` | 不含密钥或请求原文的操作摘要 |
| `app/integrations` | GitHub / 飞书适配器及提供方错误转换 |
| `app/workers` | PostgreSQL 持久任务扫描、Celery 执行、重启恢复 |
| `app/cli` | 契约工具、服务器管理员密码重置 |
| `migrations` / `tests` | Alembic、契约、提供方边界与原生 PostgreSQL 测试 |

## 本地运行

在 `backend/` 目录执行，数据库和 Redis 需预先可用：

```sh
uv sync --locked
uv run --env-file ../.env alembic upgrade head
uv run --env-file ../.env uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --no-access-log
```

独立终端启动 Worker 与 Scheduler：

```sh
uv run --env-file ../.env celery -A app.workers.celery_app:celery_app worker -Q general,files --loglevel=WARNING
uv run --env-file ../.env python -m app.workers.scheduler
```

Scheduler 是数据库任务扫描进程，不是 Celery Beat。只启动 API 不会处理冷缓存、Release 同步、群同步或群通知。

## 修改约定

先修改 IDL 并在根目录运行 `make idl`，再实现端点。数据库模型与 API DTO 分开；迁移显式运行，API 不自动建表。每请求一个 Session，服务明确提交事务；业务状态以 PostgreSQL 为准，Redis 只承担任务唤醒。

写接口校验管理员 / 下载者权限、同源 Origin、CSRF、`If-Match` 或指定的幂等键。CI 回调只接受所属规则 Bearer，不借用 Cookie 权限。提供方错误只转换为可公开摘要；不输出原始 provider body、临时 URL、Authorization、OAuth code / state 或配置值。

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run python -m app.cli.export_openapi --check --check-implementation
```

测试数据库准备与验收边界见[开发文档](../docs/development.md)。服务端重置管理员密码使用：

```sh
uv run --env-file ../.env python -m app.cli.reset_admin
```

命令要求交互终端，不接受密码参数，不输出密码；重置后撤销全部管理员会话。

## 健康检查

`GET /api/v1/health/live` 表示进程响应，`GET /api/v1/health/ready` 表示数据库和 Redis 可连接。管理员系统健康页另查 Worker / Scheduler 心跳及配置状态。任何健康接口都不能代替真实 GitHub Release、飞书资格、群通知或手机下载安装验收。
