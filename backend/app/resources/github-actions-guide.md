# 接入 Fuma GitHub Actions

本说明可直接交给修改源应用仓库的 agent。仅配置 FUMA_CI_TOKEN 不会触发通知。
流程：构建 APK / IPA → 上传 GitHub Release 附件 → 回调 Fuma → workflow 结束 → Fuma 准备文件并发卡片。

## 当前部署的回调 URL

```text
{{CALLBACK_URL}}
```

{{RULE_HINT}}

## 开始前确认

- 管理员在 Fuma 创建并启用规则，选择通知群；机器人已加入目标群。
- 规则的源仓库、Workflow 路径、可信分支 / Tag 和文件匹配规则与实际构建一致。
- Fuma GitHub 连接具备 Contents 与 Actions 读取权限。
- 源仓库的发布 job 使用 GITHUB_TOKEN，授予 contents: write。
- 当前接入读取 Release 附件，不读取仅存在于 Actions artifact 的文件。

## 配置源仓库

1. Settings → Secrets and variables → Actions → Secrets：添加 FUMA_CI_TOKEN，值为对应规则签发的令牌。
2. 同页 Variables：添加 FUMA_CALLBACK_URL，值为上方完整回调 URL。
3. 修改实际 build workflow：保留原构建环境和命令，在构建产物就绪后上传 Release 附件，再执行回调。
4. 多 job 构建应先把文件传到发布 job。已有 Release 上传步骤时复用其 Release / asset IDs，不重复创建 Release。
5. 以下 Android 示例的 JDK、Gradle 命令、文件路径、分支和 workflow 保存路径必须按源仓库调整。IPA 使用对应 macOS 构建流程并筛选 .ipa。

## 完整 Android 示例

```yaml
{{WORKFLOW_EXAMPLE}}
```

## 回调协议与完成条件

POST 上方 URL；Authorization: Bearer <FUMA_CI_TOKEN>；Content-Type: application/json。
字段 repository_id、run_id、head_sha 来自当前 GitHub 上下文；run_attempt 为整数；release_id、asset_ids 来自实际上传结果，数字 ID 以字符串传输。
不接受任意下载 URL 或群 ID。多条规则分别使用对应的令牌与 URL。

HTTP 202 仅表示已接收，不等于已通知。响应含 event_id、duplicate、state；重复回调可能返回原事件。
回调步骤返回后立即结束，不要在同一 workflow 中轮询等待 Fuma 完成：Fuma 会等待整个 run 成功。
网络错误可重试相同上下文；不要通过更换 run/attempt 伪造新事件。不要打印令牌或把它提交到仓库。

## 验收与排障

1. 从规则允许的可信分支 / Tag 触发 workflow，确认 APK / IPA 出现在 Release 附件中。
2. 回调获得 202，workflow 最终成功。
3. Fuma「构建事件」依次完成来源核验、等待构建、准备文件和通知投递；验证目标群实际收到卡片。
4. 确认固定分发页面可访问；下载仍按 Fuma 的身份和权限规则执行。

- 401/403：检查 Secret 是否存在、规则是否启用、令牌是否撤销，以及令牌 / URL 是否来自同一规则。
- 来源核验失败：核对仓库、Workflow 路径、分支 / Tag、SHA、run、Release 与附件归属。
- 等待构建：检查整个 workflow 是否仍在运行或失败；不要形成等待 Fuma 的循环。
- 文件失败：检查附件存在、文件规则和 GitHub 读取权限。
- 通知失败：检查机器人、目标群可发送状态，在事件详情按允许的阶段恢复。
- 投递结果待确认：可能已发送，先核对群消息；不要盲目重发导致重复卡片。
- fork PR 没有仓库 Secret：从已配置的可信分支触发发布，不绕过隔离。

Token 只能在 GitHub Secret 中保存；本页和链接不会包含 Token，也不会读取规则的仓库、群聊或私有配置。
