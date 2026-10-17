# 12 灰度、发布与回滚

## 1. Feature flags

建议至少拆分：

- `fuma_v2_event_enabled`
- `fuma_cos_debug_ready_enabled`
- `fuma_cos_release_ingest_enabled`
- `fuma_release_manual_publish_enabled`
- `joice_cos_upload_enabled`
- `joice_github_release_upload_enabled`（legacy，默认逐步关闭）

开关按环境、App 或 channel 生效，并记录修改者和时间。

## 2. 灰度顺序

1. 开发环境：fake COS + fake webhook，完成自动化测试。
2. 测试环境：真实 COS 测试桶，Debug 和 Release 分开 prefix，运行一周观测。
3. 生产单 App：Joice 上传 COS，Fuma v2 shadow/ingest，旧路径仍可用。
4. 生产 Debug 全量：开启自动 ready。
5. 生产 Release：开启自动 ingest，保留人工 publish。
6. 观察稳定后关闭主 workflow 的 GitHub Release 上传；保留 legacy workflow 作为应急回退。

## 3. 回滚场景

- v2 endpoint 异常：关闭 `joice_cos_upload_enabled` 或将事件发送切回 v1，COS 对象保留。
- Fuma 解析异常：关闭自动 ready，保留 ingest 记录，修复后 retry，不丢对象。
- 错桶/错 prefix：立即关闭对应 App binding，禁止继续 ingest；已入库记录根据 object identity 处理，不批量删除。
- publish 误操作：按现有发布撤销/下线流程处理，保留审计；禁止用回滚开关篡改审计记录。

## 4. 回滚验证

回滚后至少验证：旧 v1 回调仍能成功、Fuma 可读取旧来源、Joice 能完成构建、COS 未产生越权访问、待处理任务不会被重复消费。
