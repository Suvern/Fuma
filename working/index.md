# Fuma / Joice COS 迁移工作目录

> 本目录是迁移实施的工作台。`index.md` 是进度、决策、问题和验证记录的唯一入口；各阶段文档只描述对应阶段的设计与执行细节。

## 1. 目标与边界

目标：Joice 的 GitHub Release 仅负责打包，不再上传 Release 资产；构建产物上传 COS 后通知 Fuma。Fuma 以 COS 作为 Debug 包的主来源，同时兼容现有 GitHub Release 流程、Release 包流程，以及 Debug/Release 使用不同桶或同桶不同前缀的情况。

分阶段原则：每个阶段都有明确输入、输出、验收条件和回滚办法；Fuma 先改造并保持 v1 兼容，再改造 Joice 接入。

## 2. 当前进度

状态枚举：`未开始` / `进行中` / `待确认` / `已完成` / `阻塞`。

| 阶段 | 文档 | 状态 | 主要输出 | 当前阻塞 |
|---|---|---|---|---|
| 0 | [项目上下文](./00-project-context.md) | 已完成 | 范围、术语、假设 | 无 |
| 1 | [现状基线](./01-current-state-baseline.md) | 已完成 | Fuma/Joice 当前行为与代码入口 | 需在实施前确认线上配置 |
| 2 | [目标架构](./02-target-architecture.md) | 已完成 | 端到端流程与兼容矩阵 | 无 |
| 3 | [App 存储绑定](./03-app-storage-binding.md) | 进行中 | Debug/Release 存储配置模型、同桶 prefix 隔离 | 需补充连接测试与历史 binding 迁移策略 |
| 4 | [v2 事件契约](./04-v2-cos-event-contract.md) | 进行中 | COS 通知协议、规则令牌鉴权与幂等落库 | 需确认 Joice 最终签名/通知通道 |
| 5 | [COS 对象校验](./05-cos-object-verification.md) | 进行中 | 绑定前缀校验、对象 HEAD/流式 SHA 校验任务 | 需确认真实 COS SDK、网络超时与下载上限 |
| 6 | [Debug COS 接入](./06-debug-cos-ingestion.md) | 未开始 | Debug 自动入库与通知 | 依赖 3-5 |
| 7 | [Release 接入](./07-release-ingestion-manual-publish.md) | 未开始 | Release 自动入库、人工发布 | 依赖 3-5 |
| 8 | [Fuma 后端改造](./08-fuma-backend-implementation.md) | 进行中 | App 存储绑定 API、迁移、审计和并发版本校验 | 依赖 4-7 的事件/对象流程 |
| 9 | [Fuma 前端与 OpenAPI](./09-fuma-frontend-and-openapi.md) | 进行中 | 应用设置绑定卡片、OpenAPI 类型同步 | 需补充连接测试、事件记录和发布页 |
| 10 | [Joice Actions 迁移](./10-joice-github-actions-migration.md) | 未开始 | COS 上传与通知流程 | 依赖 4、6 |
| 11 | [旧 Release 迁移](./11-legacy-release-migration.md) | 未开始 | 历史包同步、清单、校验与重试 | 依赖 5、7 |
| 12 | [灰度与回滚](./12-rollout-and-rollback.md) | 未开始 | 分阶段开关、回滚策略 | 依赖 8-11 |
| 13 | [测试与验收](./13-test-and-acceptance.md) | 未开始 | 测试矩阵、验收证据 | 依赖 8-12 |
| 14 | [运维手册](./14-operations-runbook.md) | 未开始 | 日常处理、告警、排障 | 依赖 6-13 |

## 3. 已确认决策

1. Debug/Release 存储按 App 配置，可使用不同桶；同桶时必须使用不同前缀隔离。
2. 支持私有桶和公开桶；Fuma 不能信任通知中的任意下载 URL，应依据已配置的存储位置生成或校验对象地址。
3. Debug v2 事件自动入库、自动 ready 并通知；Release v2 自动入库，但发布前保留人工确认。
4. 保留现有 GitHub Release v1 兼容路径，迁移期间可以回退到 v1。
5. GitHub 只负责打包；Joice 工作流负责上传 COS 并通知 Fuma，不再创建或上传 GitHub Release 资产。

## 4. 待确认问题

- COS 厂商、SDK 版本、区域、Endpoint、私有桶鉴权方式，以及 Fuma 运行环境是否能访问 COS。
- COS 通知使用 Fuma API、消息队列、Webhook 还是定时扫描；通知重试和签名方案。
- Debug/Release 的默认保留期、覆盖策略、同一版本多构建的命名规则。
- Joice 当前发布工作流、产物命名、版本号和构建元数据字段。
- 历史 GitHub Release 是否允许覆盖已有 COS 对象；缺少 commit/构建号的历史包如何归档。
- Release 人工确认人的权限、审批界面、审计字段和发布后通知渠道。

## 5. 问题记录

问题请按 [issue 模板](./templates/issue-record.md) 追加，格式为 `ISSUE-YYYYMMDD-NN`。未解决的问题不得从“待确认”直接标记为“已完成”。

| ID | 问题 | 影响阶段 | 状态 | 负责人 | 下一步 |
|---|---|---|---|---|---|
| ISSUE-INIT-01 | 需要确认线上 COS 配置、通知通道和密钥托管 | 3-10 | 待确认 | TBD | 召开设计确认会并补充配置表 |
| ISSUE-20261017-01 | 本地数据库当前没有 ready 的存储位置，无法在浏览器中选择真实桶验证上传 | 3、5、6 | 待确认 | TBD | 仅在本地创建测试 StorageLocation 或使用测试凭证完成连接测试；禁止指向线上桶 |

## 6. 决策记录

重要设计选择请按 [决策模板](./templates/decision-record.md) 追加，并在本节留下索引。

| ID | 决策 | 日期 | 状态 |
|---|---|---|---|
| ADR-001 | Debug/Release 按 App 绑定存储，同桶使用不同 prefix | 2026-10-16 | 已确认 |
| ADR-002 | v1 GitHub Release 与 v2 COS 事件并行兼容 | 2026-10-16 | 已确认 |
| ADR-003 | Debug 自动 ready，Release 需要人工 publish | 2026-10-16 | 已确认 |

## 7. 变更日志

| 日期 | 变更 | 影响 |
|---|---|---|
| 2026-10-16 | 创建工作目录与分阶段设计文档骨架 | 仅新增文档，不改业务代码 |
| 2026-10-16 | 完成文件清单、入口索引和关键文档存在性校验 | 文档工作区可进入阶段评审 |
| 2026-10-17 | 修正本地前端 5174 与 API Origin 不一致导致的 CSRF_INVALID | 更新本地启动命令与开发文档；未改变生产配置 |
| 2026-10-17 | 完成 App Debug/Release 存储绑定第一条垂直切片 | 新增 `app_storage_bindings` 迁移、GET/PUT API、If-Match 并发校验、prefix 规范化与同桶冲突校验；前端应用设置新增绑定卡片；保留 GitHub v1 流程 |
| 2026-10-17 | 将 App channel 存储绑定接入上传默认路由 | 未显式指定 `storage_location_id` 时，上传按 `debug/release` 使用 App 绑定；无绑定时继续回退系统默认存储，显式指定仍兼容 |
| 2026-10-17 | 完成 COS v2 事件接入首轮垂直切片 | 新增事件契约、规则令牌鉴权、App/channel/prefix 校验、`event_id` 幂等落库、`cos_package_ingest` 任务及对象 HEAD/大小/已有摘要元数据校验；尚未解析或自动 ready |
| 2026-10-17 | 完成 COS 对象内容校验切片 | 增加签名 URL 流式下载、对象 SHA-256 与 manifest SHA-256 校验，临时文件只写运行时临时目录；尚未解析或入库 |

## 8. 本轮本地验证证据

- `make idl-check`：OpenAPI YAML/JSON、后端生成契约、前端生成类型均同步。
- `uv run --directory backend alembic upgrade head`：本地开发数据库迁移到 `0022_package_ingestions`。
- 后端集成测试：独立临时 PostgreSQL 中 `284 passed`；除原有绑定/上传用例外，新增 COS 事件首次接收、重复、冲突、任务入队和 fake adapter HEAD 校验。
- 前端：`pnpm test --run`（186 passed）、`pnpm lint`、`pnpm typecheck`、`pnpm build` 均通过。
- 浏览器本地验证：`http://localhost:5174/admin/apps/<本地测试 App>` 已显示“包存储绑定”卡片，验证编辑态及未绑定保存；未连接任何线上 COS。
- 上传路由集成测试：未指定存储位置的 Release 上传命中 App Release 绑定，独立测试库用例通过。
- COS 事件集成测试：独立临时 PostgreSQL 中覆盖首次接收、重复事件、同事件内容冲突、任务入队和 fake adapter HEAD 校验；`test_actions_flow.py` 全部通过。

## 9. 每阶段完成定义

- 文档中的输入、输出、依赖、错误处理和回滚步骤已确认。
- 代码改动有单元测试、集成测试或可重复的本地验证命令。
- 至少有一条正常路径和一条失败路径验证证据。
- 相关配置、监控、告警、审计和运维说明已同步。
- index 中状态、问题、决策和验证记录已更新。
