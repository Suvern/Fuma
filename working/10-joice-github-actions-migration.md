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

## 6. 对现有 Joice workflow 的本地审计（2026-10-17）

当前 `../Joice/.github/workflows/android-release.yml` 的 `publish` job 已经执行 COS 上传和 webhook，但仍包含以下旧链路：

- `gh release upload/create` 继续写 GitHub Release，和迁移目标冲突；应移到显式手动 legacy workflow，主 workflow 删除该步骤。
- `npm run release:webhook` 发送 `release.published` v1 兼容 payload，不是 Fuma v2 `schema_version=2` 的 COS 对象事件；应改为带 `Authorization: Bearer <rule token>` 的 `/api/v1/integrations/github-actions/{rule_id}/cos-events` 请求。
- 现有 `upload-release-assets.ts` 把 APK、校验文件和 `build-info.json` 打成 `${versionCode}.zip` 上传。Fuma Parser 会直接把 COS package 对象当 APK/IPA ZIP 解析，Android 包要求对象根部包含 `AndroidManifest.xml`；因此 v2 package 对象应直接上传 APK（IPA 同理），manifest 作为独立 JSON 对象上传。
- 事件必须引用上传后的 package key、size、SHA-256 与 manifest key、SHA-256；先上传 package，再上传 manifest，最后发送事件。事件失败时不删除对象，使用 event_id 重试。

下一次 Joice 改造只修改 workflow/scripts，不覆盖当前 `../Joice` 工作区中与聊天功能相关的未提交改动；改造前需要确认 Fuma App ID、Actions rule ID、COS Debug/Release binding prefix 以及 GitHub Environment secret 名称。
