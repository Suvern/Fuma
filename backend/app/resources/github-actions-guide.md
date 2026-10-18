# 接入 Fuma GitHub Actions（COS 主路径）

本说明可直接交给修改源应用仓库的 agent。仅配置 FUMA_CI_TOKEN 不会触发通知。
新流程：构建 APK / IPA → 上传已绑定的 COS bucket/prefix → 回调 Fuma v2 → workflow 结束 → Fuma 校验对象并处理。
GitHub Release 不再是 Fuma 的主数据源，也不要求 workflow 创建或上传 Release 资产。

如果通知丢失，管理员可在 Fuma 中先扫描绑定 prefix，再选择 COS 对象补提交一次导入；导入接口仍会重新 HEAD、下载、校验 manifest 和解析，不能绕过对象校验。

## 当前部署的回调 URL

```text
{{CALLBACK_URL}}
```

{{RULE_HINT}}

## 开始前确认

- 管理员在 Fuma 创建并启用规则，选择通知群；机器人已加入目标群。
- 规则的 Workflow 路径、可信分支 / Tag 和文件匹配规则与实际构建一致；这些字段用于接入说明，不需要 GitHub API 连接。
- Fuma 中已为 App 配置并启用对应 channel（Debug/Release）的 COS 存储绑定。
- workflow 使用最小权限的 COS 上传凭证；bucket、prefix、区域和 endpoint 必须与 Fuma 绑定一致。
- Release channel 仍会进入 Fuma 的人工发布确认，不因上传到 COS 而自动公开。

## 配置源仓库

1. Settings → Secrets and variables → Actions → Secrets：添加 FUMA_CI_TOKEN，值为对应规则签发的令牌。
2. 同页 Variables：添加 FUMA_CALLBACK_URL，值为上方完整回调 URL。
3. 修改实际 build workflow：保留原构建环境和命令，在构建产物就绪后将 APK/IPA 和 manifest 上传到与 channel 对应的 COS prefix，再执行 v2 回调。
4. 多 job 构建应先把文件传到发布 job；回调中的 object key、size、sha256、manifest key 和 build 元数据必须来自实际上传结果。
5. 以下 Android 示例的 JDK、Gradle 命令、文件路径、分支和 workflow 保存路径必须按源仓库调整。IPA 使用对应 macOS 构建流程并筛选 .ipa。

## 完整 Android 示例

```yaml
{{WORKFLOW_EXAMPLE}}
```

## 回调协议与完成条件

POST 上方 URL；Authorization: Bearer <FUMA_CI_TOKEN>；Content-Type: application/json。
字段 app_id、channel 和 build 元数据来自当前 workflow；object key、size、sha256 和 manifest 摘要必须来自 COS 上传结果。
不接受任意下载 URL、bucket 或群 ID；Fuma 只使用服务端 App/channel 绑定。多条规则分别使用对应的令牌与 URL。

HTTP 202 仅表示已接收，不等于已通知。响应含 event_id、duplicate、state；重复回调可能返回原事件。
回调步骤返回后立即结束，不要在同一 workflow 中轮询等待 Fuma 完成；Fuma 会独立处理 COS 对象并投递通知。
网络错误可重试相同上下文；不要通过更换 run/attempt 伪造新事件。不要打印令牌或把它提交到仓库。

## 验收与排障

1. 从规则允许的可信分支 / Tag 触发 workflow，确认 APK / IPA 与 manifest 出现在绑定的 COS prefix 中。
2. 回调获得 202，workflow 最终成功。
3. Fuma「任务中心」依次完成对象校验、解析、缓存和通知投递；验证目标群实际收到卡片。
4. 确认固定分发页面可访问；下载仍按 Fuma 的身份和权限规则执行。

- 401/403：检查 Secret 是否存在、规则是否启用、令牌是否撤销，以及令牌 / URL 是否来自同一规则。
- 对象校验失败：核对 App/channel 绑定、对象 key、大小、SHA-256 和 manifest 内容。
- 文件失败：检查对象存在、绑定 prefix、对象扩展名、大小、SHA-256 和 manifest 内容。
- 通知丢失：在 Fuma 版本页按相同 channel 选择“从 COS 导入”，填写对象 key、size、SHA-256、manifest key/SHA-256 和构建元数据；不要创建虚假的 GitHub Release。
- 对象扫描为空或摘要缺失：确认对象已上传到 App/channel binding 的 prefix，且上传端写入了对象 SHA-256 metadata；也可以继续手工填写并由 Fuma 异步复核。
- 通知失败：检查机器人、目标群可发送状态，在事件详情按允许的阶段恢复。
- 投递结果待确认：可能已发送，先核对群消息；不要盲目重发导致重复卡片。
- fork PR 没有仓库 Secret：从已配置的可信分支触发发布，不绕过隔离。

Token 只能在 GitHub Secret 中保存；本页和链接不会包含 Token，也不会读取规则的仓库、群聊或私有配置。

## GitHub Release 兼容入口（legacy）

历史 v1 GitHub Release 回调暂时保留，用于旧构建和回滚，不是 COS 主路径的前置条件。新 workflow 不应依赖 `release_id`、`asset_ids` 或 `contents: write`；在确认所有调用方完成迁移后，再单独评估关闭 legacy 入口。
