# 07 Release 入库与人工发布

## 1. 状态机

```text
received -> validating -> downloading -> parsing -> pending_publish
                                                \-> rejected
pending_publish -> publishing -> published
                              \-> publish_failed (retryable)
```

Release 的 ingest 与 publish 必须是两个独立动作。当前 COS Release 已完成 ingest：Parser 成功后创建
`PackageRecord`、`VersionRecord`、草稿 `PublicationRecord`，并将 `PackageIngestion.state` 设为
`pending_publish`；入库成功不等于对外可见。现有 Publication 发布 API 仍负责最终状态转换和公开副本任务。

当前切片的关联字段：`PackageIngestion.package_id`、`PackageIngestion.publication_id`。重复执行同一事件会复用相同 Package/Publication，不重复创建 Debug 条目。

新增确认入口：`POST /package-ingestions/{id}/publish`。该入口只接受 `pending_publish` 的 Release，复用 Publication 的权限、`If-Match` 修订校验和审计；发布前会对 `source_kind=cos` 的 canonical 对象重新执行 HEAD/完整摘要校验。校验失败时保持草稿，不改变对外状态。

## 2. 人工确认页面信息

页面至少展示：App、channel、版本、build number、commit、workflow run、对象 key、bucket/prefix（脱敏）、size、SHA-256、manifest、包解析结果、与上一版本的差异、来源类型、ingest 时间和失败/重试记录。

操作按钮：`确认发布`、`拒绝`、`重新校验`。确认发布前再次 HEAD 对象并比对 checksum，防止对象被替换。

## 3. 权限与审计

- 只有拥有 Release publish 权限的用户可确认。
- 发布 API 必须带幂等 key；重复点击返回已发布结果。
- 审计记录操作者、时间、IP/客户端（若现有审计模型支持）、source object、checksum、前一状态和目标状态。
- 拒绝必须填写原因；拒绝后的对象不自动删除，是否清理由保留策略处理。

## 4. 发布产物

发布成功后更新 Fuma 对外查询索引/缓存，生成可追踪的发布版本；若需要复制到另一个公开位置，应以 CopyObject + 目标 checksum 校验完成后再更新索引。

## 5. 验证

- Release 事件不能自动变成 published。
- COS Release 事件只能变为 `pending_publish`，必须由人工调用既有 Publication 发布操作。
- 无权限用户不能 publish；重复 publish 不产生第二次发布。
- 对象在确认前被替换时 publish 必须拒绝。
- `POST /package-ingestions/{id}/publish` 的重复或过期修订请求不能绕过 Publication 状态机。
- publish 后通知失败可重试，不回退已审计的发布状态。
