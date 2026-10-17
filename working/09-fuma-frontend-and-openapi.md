# 09 Fuma 前端与 OpenAPI

## 1. 配置页

在 App 设置中新增 Debug/Release 两行存储配置：StorageLocation、prefix、桶模式（私有/公开由 location 提供）、连接测试按钮。新配置要求两个 channel 使用独立 bucket，并展示规范化后的 key 示例。

保存前调用 validate；保存后展示最后校验时间、操作者和失败原因。secret 只能通过已有凭证管理入口配置，页面不回显。

## 2. 包列表与详情

列表增加来源（GitHub v1/COS v2）、channel、状态、版本、build、checksum 摘要、ingest 时间。详情展示对象 identity、manifest、校验步骤、任务 attempts 和通知状态。

## 3. Release 发布页

只对 `pending_publish` 展示发布操作；发布按钮显示二次确认和 checksum。发布后显示审计记录。拒绝必须填写原因，操作结果可刷新而不重复请求。

## 4. OpenAPI 文档

为 v2 event、ingestion 查询、retry、storage binding、release publish 补齐 schema、错误码、签名 header 和示例。示例中的 URL、bucket、secret 必须使用占位符，不能引用真实配置。

## 5. 前端本地验证

- mock API 验证独立 bucket 配置校验、异步任务轮询和失败重试。
- mock `pending_publish`、`published`、`rejected` 验证按钮权限和状态刷新。
- 用旧 v1 数据验证列表不会因新增字段为空而崩溃。

## 6. 第一条垂直切片实现记录（2026-10-17）

已完成：

- `AppStorageBinding` 组件已挂载到应用设置页，展示 Debug/Release 存储位置和对象前缀。
- 使用生成的 OpenAPI 类型调用 `GET/PUT /api/v1/apps/{id}/package-storage`；保存携带服务端返回的 `app_revision`，避免覆盖并发修改。
- 同一存储位置下的相同/父子 prefix 在客户端先提示；后端会再次校验，并覆盖不同 StorageLocation 的 prefix 基础路径判断。
- 无 ready 存储时页面明确提示先配置对象存储；凭据仍只在对象存储管理页处理。

本轮补齐：

- `GET /api/v1/apps/{id}/package-ingestions?channel=release` 返回按 App/channel 过滤的 COS 入库记录，并带关联 Publication 的 `publication_revision`。
- 版本发布页新增“COS Release 待发布”面板，展示版本、build、对象 key、事件 ID 和入库时间；确认发布前带二次确认，使用 `If-Match` 调用 `POST /api/v1/package-ingestions/{id}/publish`。
- 面板同时展示失败的 Release 及错误码/错误信息，使用幂等重试按钮调用 `POST /api/v1/package-ingestions/{id}/retry`；发布或重试成功后由统一查询失效机制刷新列表和版本列表；无记录、加载失败和 publication revision 缺失均有安全态。
- OpenAPI 新增 `POST /api/v1/apps/{id}/package-ingestions/import`，用于通知丢失时从已绑定 COS 对象补导入；请求必须携带对象/manifest 摘要和构建元数据，服务端异步复核后按 Debug/Release 状态机处理。
- 安装包页和版本发布页均提供“通知丢失？从已绑定 COS 导入”折叠表单，分别提交 Debug/Release 元数据；表单不上传文件、不接收 URL，打开时会列举绑定前缀下的 APK/IPA/ZIP，并在 manifest 和摘要齐全时自动带入表单。

待后续补齐：跨页 COS 对象分页浏览、连接测试结果、对象 key 示例、v2 事件记录/重试、Release 拒绝/重新校验、发布后通知和迁移进度展示。当前手工补导入已可通过表单或 OpenAPI 验证。
