# GitHub 连接收敛为通知入口

## 结论

在 COS-first 模式下，Fuma 不需要 GitHub API 连接、PAT、GitHub App、仓库绑定或 Release 读取权限。GitHub Actions 只负责：

1. 执行构建；
2. 将安装包和 manifest 上传到当前 App/channel 已绑定的 COS；
3. 使用规则令牌向 Fuma 的 `cos-events` 地址发送通知。

Fuma 的包身份、对象内容、下载地址和发布状态均以绑定 COS 为准。通知丢失时，管理员可以从同一个 App/channel 的 COS 绑定扫描并补导入，因此通知不是唯一数据入口。

## 本次代码调整

- 管理后台侧栏移除“GitHub 连接”；首页不再查询、统计或引导创建 GitHub 连接。
- 应用设置移除仓库绑定卡片，改为“GitHub Actions 通知”说明和 Actions 配置入口。
- 新建 Actions 通知规则不再要求 App 先绑定 GitHub 仓库或 connector。
- Actions 规则回调 URL 默认使用 `/integrations/github-actions/{rule_id}/cos-events`。
- `ActionsRule.repository_id` / `repository_full_name` 改为可空，仅为旧 v1 事件数据保留兼容字段。
- 接入文档和 YAML 示例明确禁止创建 GitHub Release、禁止 GitHub API 读取，并要求上传 COS 后回调。

## 仍保留的兼容边界

旧 `/connectors/github`、App repository API、GitHub Release API 和 `/events` v1 回调暂不删除，避免旧书签、旧脚本或历史数据无法读取；它们不出现在新导航和新规则创建流程中。

旧 v1 回调仍要求 repository/connector 绑定，新的 COS 规则不应调用它。后续完成旧调用方盘点后，可以删除 connector 表、repository JSON 字段、GitHub Release 任务和 v1 回调。

## 验证

- `make idl-check` 通过。
- `uv run --directory backend ruff check app ../parser` 通过。
- `pnpm --dir frontend typecheck`、`pnpm --dir frontend lint` 通过。
- `pnpm --dir frontend test -- --run`：182 passed。
- 后端公共测试：124 passed，166 skipped（本地未提供隔离测试数据库）；`tests/test_integration_docs.py` 已更新并通过。

## 后续删除清单

在确认没有旧调用方后，再按独立提交删除：

1. GitHub connector CRUD、GitHub App 凭据和连接测试；
2. App repository bind/unbind 及仓库搜索；
3. GitHub Release 列表、刷新、导入和 policy；
4. legacy `/integrations/github-actions/{id}/events` 以及相关 GitHub 校验 worker；
5. `github_connectors`、`github_repository_syncs`、`github_release_policies` 及 App `repository` 字段。

