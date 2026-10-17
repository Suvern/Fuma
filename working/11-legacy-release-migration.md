# 11 旧 GitHub Release 同步到存储桶

## 1. 目标

把历史 GitHub Release 的 APK/IPA 复制到对应 COS bucket/prefix，生成可审计清单，并允许 Fuma 以历史来源记录或 v2 ingest 记录引用它们。迁移工具必须可 dry-run、可断点续跑、可 verify-only，不因单个版本失败而中断全量任务。

## 2. 前置准备

- 确认每个 App 的 Debug/Release binding、目标 bucket、prefix 和保留策略。
- 获取 GitHub Release 列表和资产元数据：release id、tag、资产 id、name、size、download URL、发布时间。
- 预估目标对象数量、总大小、网络带宽、COS 费用和执行窗口。
- 明确历史 release 到 channel 的映射：没有明确标记时，默认归入 release，或列入待人工分类清单。

## 3. 清单格式

建议保存 `migration-manifest.jsonl`（放在安全的迁移产物目录，不提交仓库），每行包含：

```text
app_id
github_release_id
github_asset_id
tag_name
asset_name
source_size
source_sha256
channel
target_storage_location_id
target_bucket
target_key
target_size
target_sha256
status
attempts
error_code
started_at / finished_at
```

清单是重跑和审计的依据；不要把 GitHub token、COS secret 或签名写入清单。

## 4. 推荐执行步骤

1. `discover`：只读 GitHub 元数据，生成待迁移清单，检查命名、channel 和 prefix 冲突。
2. `dry-run`：不写 COS，验证每个源资产可访问、目标 key 唯一、预计大小和权限。
3. `copy`：从 GitHub 流式下载，计算源 SHA-256，再上传 COS；优先使用 multipart upload。
4. `verify`：对目标对象 HEAD/GET 校验 size、metadata、目标 SHA-256；不通过则标记 `unverified`。
5. `ingest`：为已 verified 的对象发送 Fuma v2 事件；历史 Release 默认进入 `pending_publish` 或 legacy 状态，不应自动对外 publish。
6. `report`：输出成功、跳过、冲突、不可访问、校验失败和需要人工分类的报告。

## 5. 幂等与冲突

- 目标 key 已存在且 checksum 相同：标记 `already_synced`，不重复上传。
- 目标 key 已存在但 checksum 不同：标记 `conflict`，禁止覆盖，等待人工决定新 key 或保留现状。
- 下载中断：从清单恢复；临时 multipart 未完成片段按 COS 生命周期清理。
- GitHub 资产被删除或权限不足：标记 `source_unavailable`，不伪造成功。

## 6. 本地/小批验证

- 先用 1 个 release、1 个 APK 做 dry-run/copy/verify/ingest 全链路。
- 再选包含 IPA、ZIP、多资产、重复 tag 和失败资产的小批量。
- 验证中断后重跑不会重复对象；验证 checksum 错误会阻止 ingest。

## 7. 完成标准

只有 `verified` 且已记录目标 key、size、checksum 的资产才算迁移完成。最终报告需包含总数、成功数、跳过数、失败数、未分类数和可重试命令。
