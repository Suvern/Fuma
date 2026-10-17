# 04 v2 COS 事件契约

## 1. 设计原则

- 事件描述“哪个 App 的哪个 channel 有哪个对象”，不把任意 URL 变成下载授权。
- 事件可重复投递；Fuma 以 `event_id` 或 `idempotency_key` 去重。
- manifest 是对象内容的一部分或同 prefix 的伴随对象；Fuma 必须校验其关联关系。
- v1 与 v2 共存，不能复用同一状态迁移逻辑造成重复入库。

## 2. 建议请求体

```json
{
  "schema_version": "2",
  "event_id": "joice-build-<build-id>",
  "app_id": "<fuma-app-id>",
  "channel": "debug",
  "build": {
    "version": "1.2.3",
    "build_number": "123",
    "commit_sha": "<sha>",
    "workflow_run_id": "<run-id>",
    "created_at": "2026-10-16T10:00:00Z"
  },
  "object": {
    "key": "debug/1.2.3/123/package.zip",
    "size": 12345678,
    "sha256": "<hex>",
    "etag": "<optional>",
    "content_type": "application/zip"
  },
  "manifest": {
    "key": "debug/1.2.3/123/manifest.json",
    "sha256": "<hex>"
  }
}
```

签名放在 HTTP header，例如 `X-Fuma-Event-Id`、`X-Fuma-Timestamp`、`X-Fuma-Signature`；签名内容必须包含规范化 body，防止重放和字段替换。

## 3. 服务端处理

1. 读取原始 body，校验时间窗、签名和 schema version。
2. 用 `event_id` 建唯一索引；重复事件返回原处理结果，不重新下载。
3. 校验 `app_id`、`channel`、key prefix、对象大小上限和允许扩展名。
4. HEAD/GET 对象并计算 SHA-256；若 manifest 也有 checksum，双向比对。
5. 创建 `PackageIngestion` 任务，API 返回 `202 Accepted` 和任务 ID。

## 4. 错误语义

| HTTP | 场景 | 是否可重试 |
|---|---|---|
| 400 | schema、key、channel 不合法 | 否，修正请求 |
| 401/403 | 签名或调用方无权限 | 否，修正配置 |
| 404 | App 或对象不存在 | 对象上传尚未完成时可重试 |
| 409 | 同 event_id 内容不一致 | 否，人工排查 |
| 413 | 超过对象/请求大小限制 | 否，调整产物 |
| 429 | 限流 | 是，指数退避 |
| 500/503 | Fuma/COS 暂时失败 | 是，指数退避 |

## 5. v1 兼容策略

- 保留原 endpoint 和 payload，不强迫 Joice 一次性升级。
- v1 处理结果增加 `source_type=github_release_v1`，v2 使用 `source_type=cos_v2`。
- 同一 GitHub Release 资产若已由 v2 入库，v1 回调到达时以 checksum/object identity 去重。
- 兼容期结束前保留 v1 监控和回滚开关，删除前先统计调用方。
