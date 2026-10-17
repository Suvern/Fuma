# 02 目标架构与流程

## 1. 逻辑分层

```text
Joice CI
  ├─ build APK/IPA
  ├─ package manifest + checksum
  ├─ upload COS (debug/release binding)
  └─ POST Fuma v2 event
          │
          ▼
Fuma Event API
  ├─ authenticate + verify signature/idempotency
  ├─ resolve App storage binding
  ├─ verify bucket/prefix/object metadata
  ├─ download / stream / unzip
  ├─ parse APK/IPA and persist package record
  └─ Debug: ready + notify / Release: pending_publish
```

## 2. App 存储绑定

每个 App 配置：

- `debug_storage_location_id`：Debug 默认来源。
- `release_storage_location_id`：Release 默认来源。
- `debug_prefix`、`release_prefix`：同桶时隔离；即使分桶也保留显式 prefix。
- 读权限引用：不在 App 表保存明文 secret，引用 Fuma 的凭证管理机制。

v2 事件只声明 `channel=debug|release` 和对象 key。Fuma 根据 channel 解析目标 StorageLocation；事件中若出现 bucket、endpoint、URL，仅作为诊断信息或严格比对，不作为信任来源。

## 3. Debug 流程

1. Joice 上传对象并完成 manifest。
2. Joice 发送 v2 `debug` 事件。
3. Fuma 校验签名、幂等键、对象存在性、bucket/prefix、大小、checksum 和构建元数据。
4. Fuma 解压外层 ZIP（如有），只允许 manifest 声明的 APK/IPA，禁止路径穿越和多余高风险文件。
5. Fuma 解析包并创建/更新 DebugRecord。
6. 所有校验通过后自动置 `ready`，发送通知；失败则保留可重试的失败记录。

## 4. Release 流程

1. Joice 上传对象并发送 v2 `release` 事件。
2. Fuma 完成同样的下载、校验、解析和入库，但状态为 `pending_publish`。
3. 有权限的操作者在 Fuma 界面查看 manifest、checksum、解析结果和差异。
4. 操作者确认后执行 publish；Fuma 再次检查对象仍存在且 checksum 未变化。
5. publish 产生审计记录并通知下游；拒绝则状态为 `rejected`，允许重新提交新构建。

## 5. 兼容矩阵

| 来源 | channel | 行为 | 备注 |
|---|---|---|---|
| GitHub Release v1 | debug | 现有流程 | 迁移期间保留 |
| GitHub Release v1 | release | 现有流程或转为 pending_publish | 由兼容层映射 |
| COS v2 | debug | 自动 ready | 新主路径 |
| COS v2 | release | 自动 ingest，人工 publish | 新主路径 |
| Debug/Release 不同桶 | 对应 channel | 按 channel 绑定读取 | 推荐生产配置 |
| Debug/Release 同桶 | 对应 channel | 严格 prefix 隔离 | 必须拒绝跨 prefix |
| 私有桶 | 任一 | 服务端凭证读取 | 不暴露长期签名 URL |
| 公开桶 | 任一 | 仍需对象和 prefix 校验 | 不能仅凭 URL 信任 |
