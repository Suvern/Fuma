# M1 前后端接口协作约定

状态：设计先行；契约定义不代表功能已实现。范围以 [M1](../docs/milestones/m1.md) 为准。

## 修改与分工

1. 修改 `openapi.yaml` 并运行 `make idl`；评审后前后端才能基于新增接口并行实现。
2. 后端提供契约规定的稳定 `operationId`、校验、服务端鉴权、持久化与异步任务；前端从生成类型读取 DTO，不私自猜测字段或填充模拟成功状态。
3. 业务模块：账号与 App；GitHub 与 Debug 缓存；飞书 SSO / 单机器人 / 群；Actions 与通知；任务 / 审计 / 运维。实现各模块时先契约单元测试，再前后端联调。
4. 临时 URL、一次性 CI token、密码、应用密钥不得写入前端持久存储、普通请求日志、审计 payload 或错误正文。唯一例外是 API 首次成功创建 admin 后，在服务器启动日志中输出一次随机初始密码；重启不重复输出。Secrets 写入字段均 `writeOnly`，查询只返回 `has_token/has_secret` 等状态。
5. API DTO 与 DB 模型分开。前台 `CatalogEntry` 不含仓库、Connector、内部任务等后台字段。提供方错误转义为标准错误，不直接透传原始响应。

## 统一请求与响应

- 路径统一 `/api/v1`；资源 ID 为 UUID；GitHub repository / run / release / asset ID 是十进制字符串，避免 JavaScript 数字精度丢失。
- 分页从 1 开始，默认 20，最大 100；`{items,page,page_size,total}` 中 total 是完整授权结果数量。搜索在全量同步快照上执行，不能仅搜索上游第一页。
- mutable DTO 含 revision，查询返回 `ETag: "1"`；修改携带 `If-Match`，过时 412。修改表单不允许空 PATCH；slug 和源文件身份不可变。
- 标注 `Idempotency-Key` 的命令以 UUID 识别一次用户意图；重试复用键，同键异体 409；先重验权限才返回已有结果。下载授权过期后新点击必须新键。轮换令牌不持久化明文重放结果，超时先查询状态再明确重试。
- 201 为同步创建；202 仅表示可靠写库。通用异步返回 `TaskAccepted`，前台冷缓存返回 `Preparation`，CI 回调返回 `BuildEventAccepted`，三者不能混用。
- 标准错误固定 `error.code/message/field_errors/retryable` 和 `request_id`。401 未登录，403 不允许，前台受限资源 404，409 状态冲突，412 版本冲突，422 字段错误，429 限流，503 依赖不可用。
- 常用 code：`AUTHENTICATION_REQUIRED`、`CSRF_INVALID`、`PASSWORD_CHANGE_REQUIRED`、`INVALID_CREDENTIALS`、`RECENT_AUTH_REQUIRED`、`TENANT_MISMATCH`、`ELIGIBILITY_UNVERIFIED`、`RESOURCE_NOT_AVAILABLE`、`REVISION_MISMATCH`、`IDEMPOTENCY_CONFLICT`、`SOURCE_CHANGED`、`SOURCE_NOT_AVAILABLE`、`CACHE_CAPACITY_EXCEEDED`、`DOWNLOAD_EXPIRED`、`RANGE_NOT_SATISFIABLE`、`PROVIDER_RATE_LIMITED`、`DEPENDENCY_UNAVAILABLE`、`EXTERNAL_RESULT_UNKNOWN`。code 可按模块追加，不能改变现有含义。

## 身份、CSRF 与首次租户绑定

- 本地 admin 只管理后台；飞书 session 只用于下载身份。不能用 admin 身份跳过下载资格。当前浏览器会话具有明确 kind，切换登录会轮换 session。
- 生产 Cookie `__Host-fuma_session`（Secure、HttpOnly、SameSite=Lax、Path=/）；本地 HTTP 使用 `fuma_session`。会话数据库只存随机 token hash；过期、退出和改密撤销由服务端检查。
- API 启动事务自动创建唯一 admin，不再提供 `POST /auth/bootstrap`；`GET /auth/bootstrap-status` 仅保留 initialized / sso_enabled 状态。SessionUser 增加 `must_change_password`，首次登录后只有自身上下文、改密、退出可用；服务端管理依赖拒绝业务访问，前端同步强制改密。改密提交 old_password / new_password，撤销全部旧会话并返回当前浏览器的新 SessionResponse。
- `GET /auth/browser-context` 返回匿名或已登录上下文及 CSRF；匿名上下文不授予权限。全部 Cookie 写接口要求同源 Origin 与 `X-CSRF-Token`，包括 login、改密、下载授权。前端登录后重新读取上下文并清除旧身份查询缓存。
- 根密钥自动生成并以 0600 保存到 `FUMA_STATE_DIR/encryption.key`，默认 `~/.local/share/fuma/state`；Compose 使用 `/data/state` 独立 instance_state 卷。system_state 指纹校验失败或已有实例密钥丢失则拒绝启动；旧 `FUMA_ENCRYPTION_KEY` 仅兼容一次原值导入，不作为新部署必填项或 API 输入。
- admin 配置候选飞书 App ID / Secret 后，通过 `/settings/feishu/binding/start` 发起 purpose=bind 的 OAuth；state 绑定管理员 session、候选配置 revision、用途、站内返回路径，单次消费。
- callback 对 bind 用途只建立服务端一次性 proof，不把 admin 替换为下载用户。`binding/proof` 返回当前 admin 的候选租户，`binding/confirm` 消费同 session 的未过期 proof 才激活可信租户；请求里的 tenant_key 只是预期值。
- 普通 SSO start/callback 只针对已验证的部署租户；仅允许同源站内返回路径，不接受协议相对 URL。取消 / 错误需回安全错误页，不能暴露 code 或 state。
- 列表、详情、preparation、grant 都检查当前飞书资格。资格缓存最大 300 秒，失效或无法确认则拒绝新访问 / 授权，不能降级公开。

## GitHub、缓存与下载

- App 绑定经过 Connector 验证的 repository_id；PAT 只负责 Contents read，Actions 核对另需 Actions read。Release / asset 查询绝不向前台透传私有下载 URL。
- Debug 由管理员选择或明确 CI 规则决定；draft 不可分发。版本未填写时 source Tag 只能标记为 Tag，不能伪称包内版本。
- Debug source snapshot 不可变；源大小、更新时间或 digest 变化需重新选择。并发 cache task 合并，流式暂存、校验、原子就绪；半文件不服务。
- grant 就绪返回 200 `DownloadGrant`，冷缓存 202 `Preparation`；前端轮询 preparation 就绪后重新 POST grant，再次检查资格。禁止对普通用户暴露 `/tasks/{id}`。
- 临时文件 GET / HEAD 只依靠不透明 bearer token，有效期内可转发；每个新请求检查截止时间。GET 支持单 Range（含 suffix）与 206，非法 / 多 Range 由下载处理器统一返回 416，并带 `Content-Range: bytes */size`。HEAD 忽略 Range、返回完整文件头，所有状态都不返回 body。已经开始的传输可以完成，新请求过期 410。
- grant 响应及下载 `Cache-Control: no-store`，固定分享页面不得嵌临时 URL。前端用普通浏览器导航 / 下载链接，不把大包完整读入 Blob。
- 清理跳过有效 grant 和 active transfer lease；缓存失效不改变条目 enabled。未认证不得浏览缓存目录。失败必须区分 quota、源删除、源变更和提供方临时不可用。

## 飞书机器人、Actions 与任务

- 机器人只能来自 SSO 同一自建应用。配置读取、机器人身份、全群分页、发卡片能力分别记录检查；不得用 token 成功假装所有能力就绪。
- 群同步先拉完整分页再原子替换，失败保留旧完整结果并标记错误；关键词在所有已同步群中搜索。只能选择机器人所在群，不提供全租户群或个人收件人。
- Actions rule 的 repository 来自 App 绑定，workflow/path、可信 branch/tag、asset glob、目标群和 Debug 模式由 admin 固定。CI token 仅本 rule 可用，只存 hash，轮换 / 撤销立即生效。
- callback 只收 repo/run/attempt/SHA/release/assets，无 URL、群或 shell 参数。`202` 前可靠保存；后台复核 provider 的 repository、workflow、head SHA、attempt 与可信 ref，并校验 Release Tag 所指 commit、asset 所属关系。可信信息不能只使用请求体。
- source run 可能尚未完成；callback 立即返回，Worker 等 run success 再缓存与通知。不能让同一 workflow 的回调 step 等待自己的 run success。
- 稳定事件唯一键：rule + repository + run + attempt + release + 排序去重 asset IDs。重复回调返回相同 event，不能重复建包或自动通知。
- 缓存就绪才发可下载卡片；部分失败只给 ready 文件入口。通知成功指提供方接受，不代表阅读或安装。未知投递结果 `unknown` 不自动重放；只有明确确认可能重复的专用 retry 可重发。
- 任务 / 事件重试复用原业务对象和成功子结果。服务重启依据 DB 状态恢复，Redis 不是业务状态唯一来源。

## 联调与发布检查

`make idl-check` 只证明生成同步；后端 subset 契约测试只证明现有路由不偏离设计。M1 完成时执行 `python -m app.cli.export_openapi --check --check-implementation`，再以 Schema 响应断言、安全 / 生命周期测试和真实链路覆盖验收。路由存在、返回 200 或测试替身通过都不能代替业务完成证据。
