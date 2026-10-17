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

当前本地首轮实现复用每条 Actions Rule 的一次性可轮换 Bearer token，入口为
`POST /api/v1/integrations/github-actions/{rule_id}/cos-events`。这样可以先验证
Joice 工作流和 Fuma 状态机，不新增未确认的密钥来源。最终接入前仍需把
`X-Fuma-Event-Id`、`X-Fuma-Timestamp`、`X-Fuma-Signature` 的 HMAC 方案定稿，并把
时间窗、重放保护和签名验证加入同一入口。

## 3. 服务端处理

1. 校验 Bearer token、规则状态、App 状态和 `schema_version`。
2. 用 `event_id` 建唯一索引；重复事件返回原处理结果，不重新下载；同事件不同内容返回 409。
3. 校验 `app_id`、`channel`、已绑定存储的有效状态、key prefix 和包扩展名。
4. 创建 `PackageIngestion` 记录和 `cos_package_ingest` 任务，API 返回 `202 Accepted` 和任务 ID。
5. 后台首轮任务只做 provider HEAD、大小和（若有）对象元数据摘要校验；完整 GET/SHA 和 manifest 校验属于下一阶段。

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

## 6. 通知丢失时的 COS 手工补导入

管理员可调用 `POST /api/v1/apps/{id}/package-ingestions/import`，提交 `channel`、对象 key/size/SHA-256、manifest key/SHA-256 和构建元数据；`event_id` 可选，未提供时由这些摘要生成稳定幂等标识。该入口不是上传接口：对象必须已经存在于 App/channel 绑定的 COS prefix 下，Fuma 仍会异步执行 HEAD、流式 SHA-256、manifest 校验和 APK/IPA 解析。

- 没有 binding、binding 不可用、对象 key 越界或扩展名不支持时，API 立即拒绝。
- 同一导入标识和相同 payload 返回 `duplicate=true`；相同标识但 payload 不同返回 409。
- Debug 导入最终进入 `ready` 并按现有规则通知；Release 导入最终进入 `pending_publish`，仍需人工确认。
- 该入口不读取 GitHub Release，不接受任意下载 URL，也不允许通过伪造 metadata 绕过 COS 内容校验。
