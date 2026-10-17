# 开发指南

本指南适用于修改 Fuma API、前端和异步任务。完整上传与发布流程需要 API、Worker、Scheduler 和独立 parser；仅启动前端与 API 不会处理安装包。

## 环境与依赖

- Python 3.13，uv 0.12.7；后端依赖锁定在 `backend/uv.lock`。
- Node.js 22.12+ 的 22 系列，pnpm 12.4.1；前端依赖锁定在 `frontend/pnpm-lock.yaml`。
- PostgreSQL 17、Redis；本地 Compose 使用 Redis 7，生产模板使用 Redis 8。
- Docker Engine / Desktop 与 Compose 插件用于容器依赖和隔离 parser。

在仓库根目录安装依赖、启动开发数据库及 Redis：

```sh
make setup
make infra-up
```

`deploy/compose.dev.yml` 只启动数据库和 Redis，端口为 `127.0.0.1:55432` 和 `127.0.0.1:56379`。它使用无密码的本机开发配置，不能用于生产。已有服务占用端口时，先确认归属，不要停止或重建不属于本项目的实例。

## 配置

后端只读取进程环境，不自动读取 dotenv。使用上述开发依赖时，代码默认值已匹配其连接配置。需要自定义时设置 `FUMA_` 环境变量；也可由开发者本地维护 `.env`，通过 `uv run --env-file ../.env ...` 显式加载。不要提交实际配置、令牌或密码。

| 变量 | 默认值或约束 |
| --- | --- |
| `FUMA_DATABASE_HOST` / `FUMA_DATABASE_PORT` | `127.0.0.1` / `55432` |
| `FUMA_DATABASE_NAME` / `FUMA_DATABASE_USER` | 均为 `fuma` |
| `FUMA_DATABASE_PASSWORD` | 空；只适用于本机 trust 开发数据库 |
| `FUMA_REDIS_HOST` / `FUMA_REDIS_PORT` | `127.0.0.1` / `56379` |
| `FUMA_REDIS_DB` | `0` |
| `FUMA_REDIS_USERNAME` / `FUMA_REDIS_PASSWORD` | 默认空，按所使用的 Redis 配置填写 |
| `FUMA_SITE_URL` | `http://localhost:5174`，须与浏览器 Origin 一致；本地前端默认运行在 5174 |
| `FUMA_COOKIE_SECURE` | 默认 `false`，仅允许回环地址；非本机站点必须使用 HTTPS 和 Secure Cookie |
| `FUMA_STATE_DIR` | `~/.local/share/fuma/state`；持久密钥、正式包和上传暂存 |
| `FUMA_CACHE_DIR` | `~/.local/share/fuma/cache`；GitHub 附件缓存 |
| `FUMA_PARSER_DIR` | 未设置时使用状态目录下的 `parser`；包含 `inbox`、`outbox` |
| `FUMA_SESSION_TTL_SECONDS` | 默认 28800，允许 300–86400 秒 |

API 和 Worker 必须使用相同的数据库、状态、缓存和 parser 目录。非空的兼容变量 `FUMA_DATABASE_URL` / `FUMA_REDIS_URL` 优先于对应分字段配置。新部署无需配置根密钥：API 自动生成持久密钥，后续启动会核对数据库指纹。

## 启动服务

在 `backend/` 执行迁移，然后启动 API：

```sh
uv run alembic upgrade head
FUMA_SITE_URL=http://localhost:5174 uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --no-access-log
```

确认 API 已初始化后，分别在另外两个 `backend/` 终端运行：

```sh
uv run celery -A app.workers.celery_app:celery_app worker -Q general,files --loglevel=WARNING
uv run python -m app.workers.scheduler
```

另一个终端在根目录启动本地前端：

```sh
pnpm --dir frontend dev:local
```

访问 `http://localhost:5174/login`。首次成功初始化时，API 日志只输出一次 `admin` 随机密码；登录后必须先改密。重启不会重置密码。忘记密码时，在 `backend/` 运行交互命令 `uv run python -m app.cli.reset_admin`。

**本地后端开发使用 `dev:local`，始终连接本机 API。** 普通 `dev` 会从 `frontend/.env` 读取 `FUMA_API_PROXY_TARGET`，未配置时同样连接本机。可以从 `frontend/.env.example` 创建本地配置；实际 `.env` 被 Git 忽略，仅示例文件随项目分发。进程环境变量优先于文件配置，远程地址须由开发者显式指定，详见[前端说明](../frontend/README.md)。

## 启动隔离 parser

生产 Compose 已包含 parser。本机混合开发需要另外启动解析容器，否则上传会停在解析阶段，五分钟未返回后失败。解析器不得挂载整个状态目录、数据库配置或服务凭据。

以下命令在仓库根目录执行，适用于未自定义状态和 parser 目录的开发环境；命令根据现有解析协议整理，本轮文档检查未执行 Docker 或真包验收：

```sh
mkdir -p "$HOME/.local/share/fuma/state/parser/inbox" "$HOME/.local/share/fuma/state/parser/outbox"
docker build -f parser/Dockerfile -t fuma-parser:dev .
docker run --rm --name fuma-parser-dev \
  --user "$(id -u):$(id -g)" \
  --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --memory 2g --pids-limit 64 --cpus 1 \
  --tmpfs /tmp:size=128m \
  --mount "type=bind,source=$HOME/.local/share/fuma/state/parser/inbox,target=/inbox,readonly" \
  --mount "type=bind,source=$HOME/.local/share/fuma/state/parser/outbox,target=/outbox" \
  fuma-parser:dev
```

该终端需要持续运行。自定义目录时同步替换两个挂载源，并确保 API / Worker 与容器用户可以读写各自需要的目录；不要通过开放整个状态目录权限排障。验证时在后台配置应用包标识，上传测试包并检查任务是否完成。APK 需通过解析器内的 `aapt`、`apksigner`；IPA 元数据解析不证明设备可安装。

## 测试与检查

前端检查不依赖业务数据库：

```sh
pnpm --dir frontend lint
pnpm --dir frontend typecheck
pnpm --dir frontend test
pnpm --dir frontend build
```

后端中不依赖数据库的契约、配置和提供方边界测试可单独运行，例如在 `backend/`：

```sh
uv run pytest tests/test_config.py tests/test_contract.py tests/test_dependency_checks.py tests/test_http.py tests/test_feishu_adapter.py tests/test_github_adapter.py tests/test_connector_diagnostics.py
uv run ruff check --config pyproject.toml app tests migrations ../parser
uv run ruff format --check --config pyproject.toml app tests migrations ../parser
uv run python -m app.cli.export_openapi --check --check-implementation
```

完整后端测试统一使用 `FUMA_TEST_DATABASE_URL` 和显式开关 `FUMA_TEST_DATABASE_ALLOW_CREATE=1`。不设置两者时，数据库测试跳过；只设置其中一个、URL 不符合约束或连接失败时，测试明确失败，不回退到业务连接或固定本机库。旧 `FUMA_OPERATIONS_TEST_DATABASE_URL` 不再接受。

在仓库根目录启动独立、无持久卷的测试 PostgreSQL，并运行检查：

```sh
make test-infra-up
FUMA_TEST_DATABASE_URL=postgresql+psycopg://fuma@127.0.0.1:55499/fuma_test \
FUMA_TEST_DATABASE_ALLOW_CREATE=1 make check
make test-infra-down
```

[测试 Compose](../deploy/compose.test.yml) 使用独立项目名和 `127.0.0.1:55499` 端口，数据保存在 tmpfs，停止容器后丢弃。端口冲突时设置 `FUMA_TEST_POSTGRES_PORT`，并同步修改测试 URL；不要停止不属于本项目的服务。

URL 必须使用 `postgresql+psycopg`，显式指定主机和用户，入口库名使用小写字母、数字、下划线并以 `_test` 结尾，不接受查询参数。账号需要在专用测试实例中具有 `CREATEDB` 权限；不要为此给业务账号增加权限。URL 中的密码不在错误消息中输出，实际凭据不要放入命令历史或提交到仓库。

入口库仅用于创建临时数据库，不在其中建表、清表或执行迁移。每个用例创建一个新的 `fuma_pytest_<随机值>` 数据库，用例结束后只删除本次成功创建的库。迁移测试的 downgrade 也只在该临时库执行；已存在的同名库不会被复用或删除。

正常失败会执行清理；进程被强制终止或数据库断连时可能遗留临时库，确认归属后再处理，不批量删除未知数据库。任何 skip 都表示对应测试未执行，[CI](../.github/workflows/ci.yml) 将跳过视为失败。CI 已配置测试入口与显式开关，无需预建多组业务测试库。

## Release 通知卡片模板

管理员及对应应用的维护者，在「应用管理 → 具体应用 → 飞书卡片」编辑标题、正文、
主 / 次按钮文案和标题颜色，右侧使用当前应用实时预览。各应用独立保存，归档应用仅可查看。
支持 `{{app_name}}`、`{{version}}`、`{{buildNumber}}`、`{{file_names}}`、`{{summary}}`、`{{time}}`；时间使用北京时间。
默认卡片采用绿色就绪标题，正文按版本 / Build、安装包、结果与时间分段，底部为下载页面按钮。
`buildNumber` 是 App 的 Android `versionCode` / iOS `CFBundleVersion`，不是 GitHub run ID。
自动分发优先读取已关联安装包或条目的构建号，缺失时通过现有离线解析器读取已校验缓存，
校验 SHA-256 后保存构建号。解析不可用超过两分钟或失败时显示“未获取”，不阻断通知。
同一 Release 多包构建号不同则逐文件列出，避免把某个平台的构建号误用于所有安装包。
正文支持飞书 Markdown（加粗、斜体、删除线、链接、换行），标题与按钮仍为纯文本。
默认正文用粗体区分字段；编辑器和通知详情提供对应预览。不执行 HTML 或群 @ 指令，变量值转义为字面文本。
正文格式随通知快照保存；历史未记录格式的卡片继续按纯文本重试。
预览构建号示例为 `2026100701`；实际构建号按安装包元数据原样保留，不截短、不用示例值替代。

配置通过 `/api/v1/apps/{id}/release-notification-template` 的 GET / PUT 管理，保存需要应用维护权限、
CSRF 和独立的 `If-Match`，并写入带应用范围的审计。迁移 `0020_app_notification_templates`
将旧全局自定义模板复制到现有各应用的独立记录，原全局配置保留但不再使用；新应用使用系统默认模板。
旧全局模板接口已移除。配置表以 `app_id` 为主键，不会因编辑一个应用而改变其他应用的模板。
次按钮使用飞书 `default` 样式，文案支持同样的变量，链接固定为当前应用 `/apps/{id}` 下载页面。
按钮文案和链接在创建通知时写入快照；历史卡片缺少次按钮时不会在重试中自动补加。
未保存模板时使用默认模板；仅在新建 `build_ready` 通知时渲染并持久化卡片快照。
编辑、恢复默认草稿、预览均不发送消息；已排队或历史通知重试、失败通知、连接测试卡片不受影响。
正文变量替换后超过 2000 字会省略末尾，标题上限 100 字、主 / 次按钮文案各上限 30 字。

## 修改接口与提交验证

先修改 `idl/openapi.yaml`，运行 `make idl` 同步 JSON、后端 DTO 和前端类型。数据库结构变化补充 Alembic 迁移；不要手改生成文件。

按影响范围执行契约、权限、状态变化及失败恢复测试，并记录实际验证和未验证边界。`make check` 聚合契约、lint、测试和构建，但不包含完整 Docker 部署及真实外部服务验收。提供方替身通过不能替代飞书登录、群消息、云对象收回或真机下载安装验证。

## 发布前安全与许可证检查

CI 在常规检查之外执行 Python 依赖漏洞审计、前端全部依赖漏洞审计（包含构建和测试工具）、项目文件密钥扫描及依赖许可证检查。漏洞或未经审查的许可类型会阻止通过；新增许可类型需核对来源、分发方式和正文后再修改 `scripts/license-policy.json`，不要直接放行 `UNKNOWN`。

本地可在仓库根目录运行：

```sh
uvx pip-audit==2.10.1 --path backend/.venv/lib/python3.13/site-packages
pnpm --dir frontend audit
python3 scripts/scan_secrets.py
```

密钥扫描使用固定版本、校验 SHA-256 的 Gitleaks，只复制受跟踪文件和未被 Git 忽略的新文件到系统临时目录。它不读取任何 `.env`、`.env.*` 或 `*.env` 文件（包括示例），不遍历 Git 历史；实际 dotenv 文件若被跟踪则直接失败。输出只包含规则、路径及行号，不包含匹配原文。当前支持 Linux x86_64 和 macOS arm64；其他平台需增加经过核实的下载校验值。历史及被排除的文件仍需单独审查，不能把这项检查当作完整历史清理。

`make build` 校验后端 wheel、源码包和前端 dist 均包含项目许可证及第三方说明。根目录 `LICENSE` 和 `THIRD_PARTY_NOTICES.md` 为权威副本；修改后同步复制至 `backend/`，以便独立构建源码包，校验会阻止副本不一致。

前端构建按实际打包模块输出 `dependency-licenses.json` 和 `THIRD_PARTY_LICENSES.txt`。后端 Docker 构建从生产 Python 环境生成 `THIRD_PARTY_LICENSES.json`，并将许可证文件放在 `/usr/share/licenses/fuma/`；CI 对开发环境依赖也执行许可证检查。手工生成时使用：

```sh
python3 scripts/backend_licenses.py --python backend/.venv/bin/python --output /tmp/fuma-python-licenses.json
```

生成文件包含版本、许可正文及包提供的 NOTICE，临时检查完毕后删除。此清单不覆盖镜像的系统软件、原生库或头像素材授权，也不自动履行 LGPL 等许可证的源码提供义务，详见[第三方声明](../THIRD_PARTY_NOTICES.md)。
