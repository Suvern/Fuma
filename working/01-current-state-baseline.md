# 01 现状基线

## 1. Fuma 当前行为

根据当前代码，Fuma 已有以下能力：

- 接收 GitHub Release 相关回调，并根据 `release_id`、`asset_ids` 查询 GitHub API。
- 下载 APK/IPA 资产，使用现有 Parser 解析包名、版本等信息。
- 创建 DebugRecord，并在 `FUMA_CACHE_DIR` 下保留本地 CacheRecord。
- 已存在 StorageLocation、COS/OSS 适配和公开对象发布能力，但 DebugRecord 当前没有按 App 绑定 Debug/Release 存储位置的完整模型。
- Parser 主要处理 APK/IPA；如果 Joice 上传的是包含 APK/IPA 的 ZIP，必须在 Fuma 侧增加外层 ZIP 校验、解包和选择规则。

## 2. Joice 当前行为

当前发布链路仍以 GitHub Actions 为中心，典型步骤包括：

1. 构建 APK/IPA。
2. 使用 `upload-artifact` 保存工作流产物。
3. 使用 `download-artifact` 在发布 job 取回产物。
4. 创建/更新 GitHub Release 并上传 Release 资产。
5. 通过现有回调触发 Fuma。

迁移后应将第 2-4 步改造成：在发布 job 中拿到构建产物，上传到已配置的 COS bucket/prefix，生成 manifest 和校验值，然后调用 Fuma v2 通知接口；GitHub Release 不再上传资产。

## 3. 已知风险

- 现有回调若直接接受下载 URL，可能被用于 SSRF 或跨桶读取；v2 必须只接受对象 key/版本化资源标识。
- COS 私有桶不能要求 Fuma 依赖浏览器签名 URL；服务端应使用凭证读取或后端签发短时 URL。
- Debug 与 Release 复用同桶时，若 prefix 约束不严格，会出现跨环境取包。
- 上传成功但通知失败、通知成功但 Fuma 入库失败、Fuma 入库成功但 ready 通知失败，均需要可重试且不重复建记录。
- Release 自动入库后若直接对外发布，无法满足人工确认要求；必须拆分 ingest 和 publish。

## 4. 需要实施前锁定的代码事实

- Fuma 当前 App、StorageLocation、DebugRecord、CacheRecord 的字段和迁移方式。
- GitHub callback controller/service、GitHub client、Parser、COS adapter 的具体接口。
- Joice 工作流文件及其 secret/variable 名称；禁止把 secret 写进文档或日志。
- 现有通知渠道、重试策略、任务队列和观测系统。

## 5. 基线验证清单

- [ ] 本地启动 Fuma，使用现有 v1 样例完成一次 Debug 入库。
- [ ] 本地使用测试对象存储读取一个 APK/IPA。
- [ ] 记录现有 DebugRecord 状态变化和可见下载地址。
- [ ] 记录 Joice 工作流产物名称、大小、SHA-256 和版本元数据。
- [ ] 保存一份不含 secret 的现状配置快照，用于迁移前后对比。
