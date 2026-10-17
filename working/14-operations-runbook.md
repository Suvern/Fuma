# 14 运维与排障手册

## 1. 常见问题

### 事件返回 401/403

检查签名密钥版本、时间偏差、调用方权限和 endpoint 环境；不要把签名或 secret 写入工单。修复后使用相同 event_id 重试。

### 对象 404

确认 Joice 上传完成顺序、目标 bucket/prefix、区域和最终 key。若是通知早于对象可见，等待后重试；超过重试窗口转人工。

### checksum 不匹配

冻结对应 key 的 ingest，比较 Joice manifest、COS HEAD、下载流计算值和源构建产物。不得通过关闭校验强行 ready。

### Release 卡在 pending_publish

检查发布权限、对象是否仍存在、审计和通知 outbox；不要直接改数据库状态，使用 publish/retry API。

### 重复包

按 event_id、object key、SHA-256、App、channel、version 排查。若是同一对象重复事件，应是幂等命中；若 checksum 不同，应保留 conflict。

## 2. 告警建议

- v2 事件 5 分钟内连续 5xx。
- COS 下载失败率或 checksum 失败率超过基线。
- Debug ingestion 长时间不 ready。
- Release pending_publish 超过 SLA。
- 通知 outbox/dead-letter 持续增长。
- COS bucket/prefix 出现未绑定 App 的对象（如能通过审计扫描发现）。

## 3. 例行任务

- 每日抽样校验最新 Debug/Release 对象。
- 每周检查失败任务、未完成 multipart、死信和旧 binding。
- 每月核对 COS 用量、生命周期规则、GitHub 历史资产和迁移清单。
- 发布前后核对 feature flag、workflow 版本和审计记录。

## 4. 数据保留

保留 ingestion、checksum、manifest 摘要、发布审计和迁移清单；日志按现有合规周期留存。对象删除必须走明确的保留策略和审批，不由失败重试自动删除生产数据。
