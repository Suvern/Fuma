# 10 Joice GitHub Actions 迁移

## 1. 目标 workflow

```text
build -> collect package -> generate manifest/checksum
      -> upload COS(debug/release prefix)
      -> POST Fuma v2 event
      -> record event response / retry on transient failure
```

GitHub Release 创建和资产上传步骤删除或置为显式 legacy workflow，不再作为主流程依赖。GitHub Actions 仍保留构建日志、commit、workflow run 和 artifact 元数据。

## 2. 上传步骤

- 统一产物命名：App、channel、version、build number、platform 可从 manifest 读取；key 由 workflow 根据已确认的 prefix 生成。
- 上传前生成 SHA-256；上传后用 HEAD 复核 size、content type、checksum metadata。
- 先上传 package，再上传 manifest，最后发送事件；manifest 必须声明 package key 和 checksum。
- 事件发送失败时 workflow 重试，仍失败则输出 event_id 供人工重放，不删除已上传对象。

## 3. v1/v2 兼容发布

过渡期可以为同一构建保留一个手动触发的 legacy GitHub Release workflow，但主 workflow 不再上传 Release。Fuma 侧用 object checksum 去重，避免 v2 与 legacy 同时到达产生两条记录。

## 4. 密钥与权限

- Actions 使用最小权限的 COS 上传凭证和 Fuma webhook 签名密钥。
- secret 只配置在 GitHub Environment/Secret Manager，不写入 YAML、manifest、日志或文档。
- Debug 与 Release 使用不同 credential 或至少不同 prefix policy；Release 上传权限不能允许写 Debug prefix。

## 5. 分阶段切换

1. 新增 `cos-upload-dry-run` job，只生成 key/manifest/checksum，不上传。
2. 开启真实 COS 上传，但继续执行旧 GitHub Release 流程，Fuma v2 先 shadow ingest 或不自动 ready。
3. 开启 Fuma v2 Debug ready，观察一个完整版本周期。
4. Release 切换为 v2 ingest + 人工 publish。
5. 删除主 workflow 中 GitHub Release 上传步骤；保留独立 legacy 回滚 workflow。
