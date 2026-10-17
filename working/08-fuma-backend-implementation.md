# 08 Fuma 后端改造实施顺序

## 1. 第一步：模型与迁移

- 新增 App storage binding 或对应字段；增加 channel、prefix、source_type、object_key、object_sha256、manifest 信息。
- 新增 `package_ingestions`、事件幂等表、通知 outbox/attempt 表（如现有模型没有等价能力）。
- 所有新增字段先可空；部署迁移后再启用 v2，确保旧 v1 代码能读取旧记录。

## 2. 第二步：存储抽象

扩展 StorageLocation adapter，统一提供：`head`、`getStream`、`put`（迁移工具用）、`copy`、`exists`、`buildSafeObjectKey`。adapter 不接受未经 binding 校验的 endpoint/bucket。

## 3. 第三步：事件与任务

- 新增 v2 controller、签名 middleware、schema validator、idempotency service。
- 将下载/解包/解析放入异步 worker；现有 GitHub v1 逻辑转换为同一内部 ingestion command，但保留来源标识。
- 明确事务边界：对象校验和解析可重试；记录写入使用唯一约束；通知使用 outbox。

## 4. 第四步：状态与查询

- Debug 和 Release 使用明确的状态枚举，不用布尔字段隐式表达。
- 查询接口返回 source、object identity、verification result 和 publish state。
- 旧记录缺少对象字段时返回 legacy，不强行补造 checksum。

## 5. 第五步：观测

指标：v2 接收量、验证失败率、COS 下载耗时、解析失败率、ready 延迟、pending_publish 数量、通知失败重试数、重复事件数、按 channel/bucket 分组的错误量。

日志采用 event_id/ingestion_id 关联；告警区分上传未通知、通知未处理、处理失败和 publish 卡住。

## 6. 每次提交的验证

每个小提交都应能运行：迁移检查、单元测试、controller contract test、worker happy path、失败重试测试。不要把 schema、模型、worker、前端和 Joice workflow 混在一个不可回滚提交中。
