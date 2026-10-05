# Fuma

Fuma 是自托管移动端安装包管理工具，采用 FastAPI + React / TypeScript。M1 提供 GitHub Release 附件检索、飞书 SSO 校验、Debug 安装包本机缓存与临时下载，以及 GitHub Actions 构建完成后的飞书群通知。

当前实现、测试结果和待完成的真实资源验收以 [PROCESS](docs/PROCESS.md) 为准。生产镜像与 Compose 已提供，尚未执行 Docker 构建或部署验证。

## M1 功能

- 首次启动自动生成 `admin` 初始密码并输出到 API 日志，首次登录强制改密；Cookie 会话、CSRF、密码重置与审计。
- 创建 Android / iOS App，配置 GitHub PAT Connector，关联公有或私有仓库并检索 Release / 附件。
- 按安装包文件名通配符、排除规则、Tag 与预发布类型预览并批量导入全部 Release 产物；可开启定时检查，自动导入新 Release 或更新的附件，已有来源自动去重。
- 绑定一个飞书企业自建应用及同应用机器人；管理员 OAuth 确认部署租户，下载者通过飞书登录。
- APK / IPA 缓存到本机磁盘；鉴权后签发短期链接，支持 HEAD、单 Range 和过期校验。IPA 下载不等于设备可直接安装。
- 同步并搜索机器人所在群，配置 Actions 工作流、可信分支 / Tag、文件规则与目标群；后台等构建成功和文件就绪后发卡片。
- 查看异步任务、逐阶段构建结果、通知投递与审计；未知投递不会自动重发。

COS / OSS、Release 灰度、团队角色和 TestFlight 属于后续[里程碑](docs/milestones/index.md)。

## 快速开始：本地运行

准备 Python 3.13 / uv 0.12.7、Node.js 22（22.12+）、pnpm 12.4.1，以及本机 PostgreSQL 17 和 Redis。当前开发默认连接 `127.0.0.1:55432` / `127.0.0.1:56379`，不需要运行 Docker。

```sh
make setup
```

由你复制 `.env.example` 为 `.env`，填写数据库与 Redis 的分字段连接信息；无需配置初始化令牌或加密密钥。配置项见[开发文档](docs/development.md#本地配置)。后端不会自动加载 dotenv，下列命令显式加载用户本地文件。

先执行迁移：

```sh
cd backend
uv run --env-file ../.env alembic upgrade head
```

然后分别在三个后端终端启动：

```sh
# 在 backend/：API
uv run --env-file ../.env uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --no-access-log

# 在另一个 backend/ 终端：Worker
uv run --env-file ../.env celery -A app.workers.celery_app:celery_app worker -Q general,files --loglevel=WARNING

# 在另一个 backend/ 终端：数据库任务调度器
uv run --env-file ../.env python -m app.workers.scheduler
```

第四个终端在项目根目录启动前端：

```sh
pnpm --dir frontend dev:local
```

在 API 首次启动日志中查看 `admin` 的随机初始密码，访问 `http://127.0.0.1:5173/login` 登录并修改密码。重启不会重置或再次输出密码。按照“飞书设置 → GitHub Connector → App / 仓库 → Release 附件 → Debug 下载 → Actions 规则”的顺序配置。GitHub PAT、飞书 App Secret 在管理页面输入，不放到前端配置。

## 开发与验证

```sh
make idl          # YAML IDL → JSON / 后端 DTO / 前端类型
make check        # 契约同步、lint、测试、构建
uv run --directory backend python -m app.cli.export_openapi --check --check-implementation
```

本机数据库测试需要独立测试库；不可使用业务库执行迁移回滚或数据重建。准备方式、原生依赖启动、测试范围与浏览器联调步骤见[开发文档](docs/development.md)。

## 域名与部署

[部署文档](docs/deployment.md)说明单域名 HTTPS、Compose、首次接入、备份升级和恢复。源 Android 项目可参考 [Actions 示例](deploy/github-actions-example.yml)，在上传 Release 附件后调用 Fuma；回调返回 202 后应立即结束步骤。

## 项目目录

| 目录 / 文档 | 内容 |
| --- | --- |
| [frontend](frontend/README.md) | React 页面、身份守卫、API 客户端和浏览器交互 |
| [backend](backend/README.md) | API、领域服务、数据库迁移、Worker / Scheduler |
| [idl](idl/README.md) | 先行接口设计及生成契约 |
| [deploy](docs/deployment.md) | Dockerfile、Caddy、生产 Compose、Actions 示例 |
| [docs/PROCESS.md](docs/PROCESS.md) | 完成事项、TODO、验收证据 |
| [PRD](docs/prd/index.md) / [技术方案](docs/technical-design/index.md) | 全量产品与实现约定 |
| [M1](docs/milestones/m1.md) | MVP 范围与验收清单 |

### Release 规则导入与自动同步

在应用的「GitHub Releases」中设置文件名规则，例如 `joice-*-arm64.apk, *.ipa`，排除 `*unsigned*`。规则区分大小写，多个包含规则命中任意一条即可，排除规则优先；只导入应用支持的 APK / IPA，草稿与超出文件大小限制的附件会跳过。预览覆盖所有已同步的 Release，不受下方分页和搜索条件限制；列表最多展示 200 个，批量导入处理全部匹配项。

自动同步默认关闭。勾选并保存后，scheduler 会先检查并导入历史匹配产物，随后按间隔检查（默认 15 分钟，最短 5 分钟）。scheduler 与 worker 需要持续运行。页面显示下次检查、最近新增/已有/失败数量及任务链接；停用应用或 GitHub 连接会暂停检查。规则变更或关闭自动同步后，旧规则的排队任务会停止。

该流程无需在源项目配置 GitHub Actions 回调。导入会创建 Debug 下载记录，文件仍在首次下载时缓存并校验；已导入的来源不会重复创建或重新启用。附件发生替换时按新来源导入，旧记录保留。升级时运行 `alembic upgrade head` 创建规则与调度表，再启动新版 API、worker 和 scheduler。
