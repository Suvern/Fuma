# Fuma / Joice COS 迁移工作目录

> 本目录是迁移实施的工作台。`index.md` 是进度、决策、问题和验证记录的唯一入口；各阶段文档只描述对应阶段的设计与执行细节。

## 1. 目标与边界

目标：先完成 Fuma 改造。Fuma 以 COS 作为 Debug/Release 包的唯一主来源，默认要求 Debug/Release 分别绑定独立存储桶；COS webhook 是正常入口，通知丢失时可从已绑定 COS 对象手工补导入。GitHub 只保留 workflow/run/commit 的来源通知与审计，不再展示或依赖 GitHub Release。Joice 的 workflow 改造暂不在本阶段实施。

分阶段原则：每个阶段都有明确输入、输出、验收条件和回滚办法；Fuma 先改造并保持 v1 兼容，再改造 Joice 接入。

## 2. 当前进度

状态枚举：`未开始` / `进行中` / `待确认` / `已完成` / `阻塞`。

| 阶段 | 文档 | 状态 | 主要输出 | 当前阻塞 |
|---|---|---|---|---|
| 0 | [项目上下文](./00-project-context.md) | 已完成 | 范围、术语、假设 | 无 |
| 1 | [现状基线](./01-current-state-baseline.md) | 已完成 | Fuma/Joice 当前行为与代码入口 | 需在实施前确认线上配置 |
| 2 | [目标架构](./02-target-architecture.md) | 已完成 | 端到端流程与兼容矩阵 | 无 |
| 3 | [App 存储绑定](./03-app-storage-binding.md) | 已完成（产品约束） | Debug/Release 独立存储桶绑定、COS 主来源 | 连接测试与历史 binding 迁移仍待补充 |
| 4 | [v2 事件契约](./04-v2-cos-event-contract.md) | 进行中 | COS 通知协议、规则令牌鉴权、幂等落库和通知丢失补导入 | 需确认最终签名/通知通道 |
| 5 | [COS 对象校验](./05-cos-object-verification.md) | 进行中 | 绑定前缀校验、对象 HEAD/流式 SHA 校验任务 | 需确认真实 COS SDK、网络超时与下载上限 |
| 6 | [Debug COS 接入](./06-debug-cos-ingestion.md) | 进行中 | 已校验对象进入 Parser 并创建云端原件 Debug 记录；支持 webhook 和手工补导入 | 通知、ZIP manifest 细节与真实 Parser 联调待完成 |
| 7 | [Release 接入](./07-release-ingestion-manual-publish.md) | 进行中 | COS Release 入库到 `pending_publish`，版本发布页确认发布，复用 Publication 草稿与既有发布权限 | 需补拒绝/重新校验动作、发布后通知和真实 COS 联调 |
| 8 | [Fuma 后端改造](./08-fuma-backend-implementation.md) | 进行中 | App 存储绑定 API、迁移、审计和并发版本校验 | 依赖 4-7 的事件/对象流程 |
| 9 | [Fuma 前端与 OpenAPI](./09-fuma-frontend-and-openapi.md) | 已完成（产品主流程） | COS 主导航、Debug/Release 分桶配置、补导入与发布确认、OpenAPI 类型同步 | 需补充跨页扫描、真实连接测试和事件记录 |
| 10 | [Joice Actions 迁移](./10-joice-github-actions-migration.md) | 未开始 | 仅保留现状审计，不改 Joice 工作区 | Fuma 主路径验收完成后再单独排期 |
| 11 | [旧 Release 迁移](./11-legacy-release-migration.md) | 未开始 | 历史包同步、清单、校验与重试 | 依赖 5、7 |
| 12 | [灰度与回滚](./12-rollout-and-rollback.md) | 未开始 | 分阶段开关、回滚策略 | 依赖 8-11 |
| 13 | [测试与验收](./13-test-and-acceptance.md) | 未开始 | 测试矩阵、验收证据 | 依赖 8-12 |
| 14 | [运维手册](./14-operations-runbook.md) | 未开始 | 日常处理、告警、排障 | 依赖 6-13 |
| 15 | [产品主流程切换](./15-fuma-product-cutover.md) | 已完成（主流程） | 移除 GitHub Release 主入口、COS-first 文案与手工上传锁定 | 无 |
| 16 | [存储桶资源池复核](./16-storage-pool-product-review.md) | 已完成（本地代码与回归） | 将全局存储页降级为资源池，App/channel 绑定成为唯一分发语义 | 无；真实 COS 凭据仍待本地联调 |
| 17 | [桶根目录与凭据档案](./17-storage-root-and-credential-profiles.md) | 已完成（本地代码与回归） | 可选根前缀、App 根目录绑定、共享加密凭据档案、Joice 外层 ZIP 安全解包 | 新 workflow 仍建议直接上传 APK/IPA + manifest |
| 18 | [GitHub 仅通知入口](./18-github-notification-only.md) | 已完成（本地代码与回归） | 隐藏 GitHub 连接主入口；Actions 规则创建不再依赖 connector；默认回调切换 COS events | 旧 GitHub API/legacy v1 仍待最终删除 |
| 19 | [COS-first 管理主流程与安装包导入页](./19-cos-first-management-flow.md) | 已完成（本地代码与回归） | 独立批量导入页、版本发布概览、Actions/飞书通知信息架构、标准 ZIP 目录契约 | Harmony 原生包契约、真正单活动 Release 约束、服务端批量接口待后续切片 |

## 3. 已确认决策

1. Debug/Release 存储按 App 配置，默认且新配置强制使用不同存储桶；不允许用同桶 prefix 代替分桶。
2. 支持私有桶和公开桶；Fuma 不能信任通知中的任意下载 URL，应依据已配置的存储位置生成或校验对象地址。
3. Debug v2 事件自动入库、自动 ready 并通知；Release v2 自动入库，但发布前保留人工确认。
4. 旧 GitHub Release API 暂保留为后台兼容层，但从 Fuma 产品导航和主流程移除，不再作为回退入口。
5. Fuma 强绑定 COS：COS webhook、手工补导入和手工上传必须命中 App/channel binding；GitHub 只负责通知与来源审计。
6. Joice 后续再改为“GitHub 只负责打包，Actions 上传 COS 后通知 Fuma”；本阶段不修改 Joice。
7. GitHub 连接不属于新产品模型；新规则只使用 Actions CI token + COS 事件回调，旧 connector/repository/Release API 进入兼容退场阶段。

## 4. 待确认问题

- COS 厂商、SDK 版本、区域、Endpoint、私有桶鉴权方式，以及 Fuma 运行环境是否能访问 COS。
- COS 通知使用 Fuma API、消息队列、Webhook 还是定时扫描；通知重试和签名方案。当前已具备 webhook 和手工补导入两条 Fuma 入口。
- Debug/Release 的默认保留期、覆盖策略、同一版本多构建的命名规则。
- Joice 当前发布工作流、产物命名、版本号和构建元数据字段。
- 历史 GitHub Release 是否允许覆盖已有 COS 对象；缺少 commit/构建号的历史包如何归档。
- Release 人工确认人的权限、审批界面、审计字段和发布后通知渠道。
- COS `channel=release` 已进入 `pending_publish`，但尚未自动发布；手工补导入也遵循同一状态机。

## 5. 问题记录

问题请按 [issue 模板](./templates/issue-record.md) 追加，格式为 `ISSUE-YYYYMMDD-NN`。未解决的问题不得从“待确认”直接标记为“已完成”。

| ID | 问题 | 影响阶段 | 状态 | 负责人 | 下一步 |
|---|---|---|---|---|---|
| ISSUE-INIT-01 | 需要确认线上 COS 配置、通知通道和密钥托管 | 3-10 | 待确认 | TBD | 召开设计确认会并补充配置表 |
| ISSUE-20261017-01 | 本地数据库当前没有 ready 的存储位置，无法在浏览器中选择真实桶验证上传 | 3、5、6 | 已解决（本地测试） | TBD | 已使用 disposable PostgreSQL + 测试适配器验证；真实 COS 仍需单独准备本地测试凭证 |

## 6. 决策记录

重要设计选择请按 [决策模板](./templates/decision-record.md) 追加，并在本节留下索引。

| ID | 决策 | 日期 | 状态 |
|---|---|---|---|
| ADR-001 | Debug/Release 按 App 绑定两个独立存储桶 | 2026-10-16 | 已确认 |
| ADR-002 | GitHub Release 从产品主流程移除，旧 API 仅作后台兼容 | 2026-10-16 | 已确认 |
| ADR-003 | Debug 自动 ready，Release 需要人工 publish | 2026-10-16 | 已确认 |
| ADR-004 | COS webhook/手工补导入强制使用 App/channel binding；GitHub Release 仅作 legacy 兼容 | 2026-10-17 | 已确认 |
| ADR-005 | 全局存储页只管理资源池；新产品路径不再使用全局默认桶 | 2026-10-18 | 已确认 |
| ADR-006 | 空资源池/App 前缀表示绑定桶根目录；凭据档案与桶位置分离并可复用 | 2026-10-18 | 已确认 |
| ADR-007 | GitHub 从 API 连接降级为 Actions 通知入口，COS 是唯一包源 | 2026-10-18 | 已确认 |
| ADR-008 | 标准包目录为 `android/ios/harmony/<buildNumber>.zip`，导入页按绑定桶扫描并允许选择 Debug/Release | 2026-10-18 | 已确认 |

## 7. 变更日志

| 日期 | 变更 | 影响 |
|---|---|---|
| 2026-10-16 | 创建工作目录与分阶段设计文档骨架 | 仅新增文档，不改业务代码 |
| 2026-10-16 | 完成文件清单、入口索引和关键文档存在性校验 | 文档工作区可进入阶段评审 |
| 2026-10-17 | 修正本地前端 5174 与 API Origin 不一致导致的 CSRF_INVALID | 更新本地启动命令与开发文档；未改变生产配置 |
| 2026-10-17 | 完成 App Debug/Release 存储绑定第一条垂直切片 | 新增 `app_storage_bindings` 迁移、GET/PUT API、If-Match 并发校验、prefix 规范化与同桶冲突校验；前端应用设置新增绑定卡片；保留 GitHub v1 流程 |
| 2026-10-17 | 将 App channel 存储绑定接入上传默认路由 | 上传按 `debug/release` 使用 App 绑定；后续收紧为无绑定或显式错桶直接拒绝 |
| 2026-10-17 | 完成 COS v2 事件接入首轮垂直切片 | 新增事件契约、规则令牌鉴权、App/channel/prefix 校验、`event_id` 幂等落库、`cos_package_ingest` 任务及对象 HEAD/大小/已有摘要元数据校验；尚未解析或自动 ready |
| 2026-10-17 | 完成 COS 对象内容校验切片 | 增加签名 URL 流式下载、对象 SHA-256 与 manifest SHA-256 校验，临时文件只写运行时临时目录；尚未解析或入库 |
| 2026-10-17 | 开始 Debug COS 解析入库切片 | 增加独立 `cos_package_parse` 任务，消费 manifest 的平台/文件名，复用现有隔离 Parser，创建 `PackageRecord`、`StoredObject` 和 Debug 记录；原件继续以 COS 对象为主，不回传 GitHub Release |
| 2026-10-17 | 完成 Debug ready 通知切片 | COS 入库事务同时创建带规则归属的 Feishu 投递记录和通知任务；发送前重新校验 App、规则和群目标，新增 `0024_cos_notification_rule` 迁移；通知失败不回滚已 ready 包 |
| 2026-10-17 | 开始 COS Release 人工发布切片 | Release 解析后创建 `PackageRecord`、`VersionRecord`、草稿 `PublicationRecord`，入库状态为 `pending_publish`；新增 `package_id/publication_id` 关联和 `0025_cos_release_publication` 迁移，未创建 Debug 条目 |
| 2026-10-17 | 增加 COS Release 确认发布入口 | 新增 `POST /package-ingestions/{id}/publish`，复用 Publication 权限/审计/If-Match，并在发布前重新校验 COS canonical 对象 |
| 2026-10-17 | 接入 COS Release 管理页待发布列表 | 新增按 App 查询 `pending_publish` 入库记录的接口，版本发布页展示构建信息并带 Publication revision 确认发布；确认后自动刷新列表与版本数据 |
| 2026-10-17 | 补齐 Release 人工核验信息 | 待发布卡片增加 commit、workflow run、对象大小/SHA-256、manifest key/摘要等字段，便于确认前对照构建产物 |
| 2026-10-17 | 补齐 Release 失败恢复入口 | 入库列表支持按 channel 过滤，管理页展示失败记录和错误信息，并用幂等重试按钮重新排队 COS 校验 |
| 2026-10-17 | 审计 Joice 本地 Android workflow | 确认现有 workflow 已上传 COS 但仍上传 GitHub Release；旧 webhook 不符合 Fuma v2；当前 COS ZIP 产物不能直接被 Fuma Android Parser 解析，需先确认并改为 APK/IPA 对象契约 |
| 2026-10-17 | Fuma 增加 COS 通知丢失补导入能力 | 新增管理员 `POST /api/v1/apps/{id}/package-ingestions/import`；要求 App/channel binding 和 COS 对象/manifest 摘要，复用异步校验、解析、Debug ready、Release pending_publish 状态机；`package_ingestions.rule_id` 改为可空以支持无 CI 通知规则的导入 |
| 2026-10-17 | Fuma 管理页接入 COS 补导入表单 | 安装包页提供 Debug、版本发布页提供 Release；表单只提交 COS key/摘要和构建元数据，不上传文件，提交后统一刷新入库状态 |
| 2026-10-18 | Fuma 接入绑定 COS 对象扫描 | 新增 Adapter 统一列举 COS/OSS 对象和 continuation cursor；新增按 App/channel binding 限定范围的对象列表 API；前端选择对象后自动带入大小、摘要和同目录 manifest，缺少校验元数据时禁止直接提交 |
| 2026-10-18 | 完成 Fuma 产品主流程走查与 COS 切换 | 移除 GitHub Releases 导航和入口，旧链接重定向到版本发布；Debug/Release 新配置强制独立存储桶；安装包、Debug、Actions、通知模板统一改为 COS 主来源文案；GitHub 仅保留构建通知/审计语义 |
| 2026-10-18 | 收紧手工上传器的存储选择 | 安装包页按当前 Debug/Release channel 自动使用 App 绑定 COS bucket，不再展示系统默认、本机或任意存储位置；旧 API 回退仅保留给旧客户端兼容 |
| 2026-10-18 | 复核并纠正“全局存储”产品语义 | 全局入口改为“存储桶资源池”，移除默认桶展示与操作；App 设置改为“分发存储绑定”，明确 Debug/Release 是唯一包源；新增 `working/16-storage-pool-product-review.md` |
| 2026-10-18 | 收紧上传运行时绑定 | `create_upload` 不再回退全局默认桶；必须存在 App/channel binding，显式目标桶必须与绑定一致；新增 `STORAGE_BINDING_REQUIRED` / `STORAGE_BINDING_MISMATCH` |
| 2026-10-18 | 补齐绑定后的隔离 PostgreSQL 回归 | 测试 fixture 显式创建 ready 的 Debug/Release 绑定，普通包流使用本地确定性存储适配器；完整后端集成测试 `290 passed`，新增无绑定/错桶/停用桶拒绝用例 |
| 2026-10-18 | 清理归档页遗留 Release 语义 | 归档提示改为 COS 入库任务，管理入口改到“版本发布”，不再链接旧 GitHub Release 路径；前端测试 `186 passed`、类型检查通过 |
| 2026-10-18 | 修复应用管理 UI 细节 | 修复新建应用输入框重复焦点边框；区分存储桶、账号与缓存图标；应用列表文案补充存储桶/通知语义；前端测试 `186 passed`、lint 和类型检查通过 |
| 2026-10-18 | 支持桶根目录、共享凭据档案与 Joice 外层 ZIP | 前缀可留空并归一化；App channel 前缀可留空；新增 `storage_credentials` 与可复用凭据选择；仅对含唯一 APK/IPA、sha256、build-info 的 ZIP 安全解包 |
| 2026-10-18 | GitHub 连接收敛为通知入口 | 移除管理后台 GitHub 连接主入口和 App 仓库绑定主卡片；Actions 新规则不再依赖 connector；回调文档与默认 URL 切换为 `cos-events`；旧 GitHub API 保留兼容 |
| 2026-10-18 | 完成 COS-first 管理主流程重构 | 新增独立安装包批量扫描/解析/导入页；版本发布页增加最新 URL、活动 Release 和搜索列表；Actions 接入与飞书通知重新分工；文档/YAML 统一标准 ZIP 目录与 `archive-1` 内容 |

## 8. 本轮本地验证证据

- `make idl-check`：OpenAPI YAML/JSON、后端生成契约、前端生成类型均同步。
- `uv run --directory backend alembic upgrade head`：本地开发数据库迁移到 `0027_storage_credentials`；本地测试数据库同样从迁移头重建。
- 后端集成测试：独立临时 PostgreSQL 中 `290 passed`；覆盖 COS Debug/Release 事件首次接收、重复、冲突、对象校验、Parser 结果入库、Debug 自动 ready、Release `pending_publish`、发布前复核和失败重试。
- 前端：本轮 `pnpm test --run`（182 passed）、`pnpm lint`、`pnpm typecheck` 均通过；本轮生成类型后再次通过 `pnpm typecheck`。
- 浏览器本地验证：`http://localhost:5174/admin/apps/<本地测试 App>` 已显示“包存储绑定”卡片，验证编辑态及未绑定保存；未连接任何线上 COS。
- 上传路由集成测试：未指定存储位置的 Release 上传命中 App Release 绑定，独立测试库用例通过。
- COS 事件集成测试：独立临时 PostgreSQL 中覆盖首次接收、重复事件、同事件内容冲突、任务入队、fake adapter HEAD/下载、Parser 结果入库和失败重试；`test_actions_flow.py` 全部通过。
- COS ready 通知测试：验证入库事务创建 `DeliveryRecord` 与 `notification` 任务、绑定 Actions 规则目标，并由发送前的规则/App/群成员校验保护；通知失败可沿用现有投递重试入口。
- COS Release 管理页本地验证：登录本地 `http://localhost:5174` 后进入 App「版本发布」，可看到“COS Release 待发布”面板；无待发布记录时显示空态，未连接线上 COS。
- 本轮新增接口验证：`GET /api/v1/apps/{id}/package-ingestions?state=pending_publish` 返回 `publication_revision`，发布操作沿用 `If-Match`；COS Release 流程测试通过。
- 本轮新增接口验证：管理员可在本地为已绑定 Release channel 提交 COS 对象补导入；无 CI rule 时 `rule_id` 为空，接口返回 202，重复 payload 幂等，绑定缺失/越界对象被拒绝；定向测试通过。
- 本轮新增接口验证：`test_cloud_storage.py` 7 项通过；根前缀、共享凭据档案复用、Joice 外层 ZIP 的 APK/IPA + sha256 + build-info 校验通过；外层 ZIP 不满足完整结构时拒绝解析。
- 本轮新增接口验证：绑定 COS 对象列表只返回 APK/IPA/ZIP，排除 TXT 等无关对象，匹配同目录 manifest 并返回摘要；COS/OSS 分页响应归一化测试通过。

## 9. 每阶段完成定义

- 文档中的输入、输出、依赖、错误处理和回滚步骤已确认。
- 代码改动有单元测试、集成测试或可重复的本地验证命令。
- 至少有一条正常路径和一条失败路径验证证据。
- 相关配置、监控、告警、审计和运维说明已同步。
- index 中状态、问题、决策和验证记录已更新。
