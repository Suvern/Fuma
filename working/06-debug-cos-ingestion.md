# 06 Debug COS 接入

## 1. 目标状态机

```text
received -> validating -> downloading -> parsing -> ready
                                      \-> failed_retryable
                                      \-> failed_terminal
```

Debug 通过所有校验后自动进入 `ready`。重复事件命中同一 `event_id` 或同一 `object sha256` 时返回原记录；若同一 key 的 checksum 变化，必须创建冲突错误，不覆盖已 ready 记录。

当前实现到达 `received -> validating -> verified`（`verified` 代表对象和 manifest 已完成
HEAD、流式下载及 SHA-256 校验），尚未进入 `parsing` 和 `ready`。因此本阶段不会把远端
对象直接暴露为 Debug 可下载记录。

## 2. 任务步骤

1. 接收 v2 事件，落库 `PackageIngestion`，返回任务 ID。
2. 校验 App、channel、binding 和 key prefix。
3. HEAD 对象，校验 size/content type/metadata。
4. 流式下载并计算 SHA-256；大小或 checksum 不符则失败。
5. 若为 ZIP，执行安全解包并读取 manifest。
6. 将 APK/IPA 交给现有 Parser；校验包名、版本、平台。
7. 在事务中创建或更新 DebugRecord、CacheRecord、来源信息。
8. 提交后发送 ready 通知；通知失败不回滚包记录，使用独立 outbox 重试。

## 3. API 与异步任务

- `POST /apps/{appId}/packages/events`：接收 v2 事件，快速返回 202。
- `GET /package-ingestions/{id}`：查询阶段、错误、对象信息和关联 DebugRecord。
- `POST /package-ingestions/{id}/retry`：仅允许可重试失败，生成新的 attempt。

任务应有最大重试次数、指数退避、死信状态和人工重试入口。API 请求不能同步等待整个 COS 下载和解析。

## 4. 通知

通知 payload 使用 Fuma 内部 record ID、App、版本、platform、source、对象摘要和状态，不发送长期可访问 secret URL。需要下载时由 Fuma 临时签发短时 URL，或让客户端走授权 API。

## 5. 本地验证

- 使用本地 S3/COS 兼容服务或 fake adapter 覆盖：正常 APK、正常 IPA、ZIP、checksum 错误、对象不存在、私有权限失败、重复事件、同 key 不同 checksum。
- 验证 Debug 自动 ready，通知失败可独立重试，任务失败不会产生半条 ready 记录。
