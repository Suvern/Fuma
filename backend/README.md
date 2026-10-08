# 后端

Python 3.13、FastAPI / Pydantic、SQLAlchemy / psycopg、PostgreSQL、Celery / Redis。配置仅从进程环境读取；依赖、默认配置和隔离测试说明见[开发指南](../docs/development.md)。

## 模块

| 路径 | 职责 |
| --- | --- |
| `app/api` | 管理、分发及 CI HTTP 接口、请求依赖与权限入口 |
| `app/api/contracts.py` | 由 IDL 生成的 DTO，不手动修改 |
| `app/core` | 配置、标准错误、密钥与日志处理 |
| `app/domains/auth`、`app/domains/access` | 本地管理员、会话、限流、飞书成员角色与应用范围 |
| `app/domains/applications` | 应用、平台、包标识及仓库绑定 |
| `app/domains/github` | Connector、仓库和 Release 快照 |
| `app/domains/distribution` | 飞书资格、机器人群、Debug 缓存、授权、Actions 和通知 |
| `app/domains/library` | 正式包、上传、解析协调、版本与发布 |
| `app/domains/storage` | COS / OSS 适配、文件持久化、公开副本与收回 |
| `app/domains/audit` | 操作摘要与查询 |
| `app/integrations` | GitHub、GitHub App、飞书调用和错误转换 |
| `app/workers` | 数据库任务调度、Celery 执行和租约恢复 |
| `app/cli` | 契约工具与管理员密码重置 |
| `migrations`、`tests` | Alembic 迁移、契约与业务测试 |
| `../parser` | 无网络的独立安装包解析服务 |

## 本地运行

先按开发指南启动 PostgreSQL 和 Redis。在 `backend/` 执行：

```sh
uv sync --locked
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --no-access-log
```

API 初始化后，在另外两个 `backend/` 终端分别运行：

```sh
uv run celery -A app.workers.celery_app:celery_app worker -Q general,files --loglevel=WARNING
uv run python -m app.workers.scheduler
```

Scheduler 是数据库任务扫描进程。只启动 API 不会完成缓存、Release 同步、群通知或正式包处理；上传还需要按开发指南启动隔离 parser。自定义环境配置时，应让全部后端进程使用一致配置。

## 修改与验证

先修改 [OpenAPI YAML](../idl/openapi.yaml) 并在根目录运行 `make idl`。数据库模型与 API DTO 分开，结构变化显式增加迁移；API 不自动建表。每请求使用独立 Session，服务明确事务边界，业务状态以 PostgreSQL 为准。

Cookie 写接口检查 Origin、CSRF 和当前权限；资源修改、幂等命令分别遵循契约。人工发起的异步任务执行时也复查权限。CI 回调只接受所属规则的 Bearer 令牌。提供方原始响应、签名 URL、认证信息及 OAuth code / state 不进入公开错误或日志。

在 `backend/` 可运行：

```sh
uv run ruff check --config pyproject.toml app tests migrations ../parser
uv run ruff format --check --config pyproject.toml app tests migrations ../parser
uv run python -m app.cli.export_openapi --check --check-implementation
```

完整 `pytest` 会清空测试表；部分测试仍使用固定数据库名。先阅读开发指南并准备隔离实例，不要在业务环境直接运行。提供方替身测试不能代替真实接入验收。

## 运维入口

`GET /api/v1/health/live` 表示进程响应，`GET /api/v1/health/ready` 检查数据库和 Redis。后台系统页另外展示 Worker / Scheduler 心跳；健康状态不代表整个发布、下载或通知链路可用。

忘记本地 admin 密码时，在使用同一实例配置的交互终端执行 `uv run python -m app.cli.reset_admin`。命令不接受明文密码参数；重置会撤销管理员会话。持久根密钥及正式包必须与数据库一起备份，详见[部署与备份](../docs/deployment.md)。
