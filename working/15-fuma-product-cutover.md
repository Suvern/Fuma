# 15 Fuma 产品主流程切换（COS-first）

## 1. 走查结论

本地走查覆盖应用设置、安装包、版本发布、Debug 包、Actions 规则和通知模板。原界面存在四个容易误导使用者的问题：

1. “GitHub Releases”仍是一级 Tab，用户容易把 Release 当作包源。
2. Debug 页面仍写“从 Release 导入”，并展示 Release/Asset ID；这与 COS 主路径冲突。
3. 安装包页把 GitHub 作为来源筛选项，手工上传没有明确说明最终写入哪个桶。
4. Actions 指引仍要求创建 Release 和 `contents: write`，会让新 workflow 继续消耗 GitHub Release 配额。

## 2. 已执行的产品调整

- 移除 Fuma 管理导航中的 GitHub Releases Tab。
- 旧 `/admin/apps/:id/releases` 链接安全重定向到“版本发布”，避免书签失效，但不再渲染 GitHub Release 管理页。
- 应用设置、安装包、Debug、Actions、飞书通知模板统一改为 COS-first 文案。
- Debug 页面改为“COS Debug 包管理”，移除“从 Release 导入”和 Release/Asset ID 展示。
- 安装包来源筛选以 COS/手工上传为主，历史 GitHub 来源只显示为兼容数据标签。
- 管理页手工上传器按当前 Debug/Release channel 自动锁定 App 绑定 bucket，不再让管理员选择系统默认或其他任意存储位置。
- 新配置时服务端拒绝 Debug/Release 绑定同一 bucket；前端同步给出明确提示。
- Actions 示例改为“构建 → 上传绑定 COS → 回调 Fuma”，不创建 GitHub Release，GitHub 只提供 run/commit 来源审计。

## 3. 主流程与边界

```text
GitHub Actions 构建
        │
        ├─ Debug 产物 → Debug 独立 bucket/prefix → Fuma COS 事件 → 自动 ready/通知
        └─ Release 产物 → Release 独立 bucket/prefix → Fuma COS 事件 → pending_publish → 人工发布

通知丢失：Fuma 管理员从绑定 bucket 扫描对象并补导入
```

GitHub Release API、旧数据模型和 legacy 组件暂不删除，以便后续数据清理和回滚；它们不再出现在主导航、主流程或新接入文档中。

## 4. 本地验收

- 浏览器检查 `/admin/apps/:id`：导航不再出现 GitHub Releases。
- 直接访问旧 `/admin/apps/:id/releases`：跳转到 `/admin/apps/:id/versions`。
- 应用设置绑定相同 bucket：前端阻止提交，服务端返回 `STORAGE_BUCKET_CONFLICT`。
- 安装包页：来源筛选显示 COS；上传说明明确写入当前 mode 的绑定 bucket。
- Actions 页面：不再出现“上传 Release 附件”或 `contents: write` 作为前置条件。

## 5. 后续明确工作

- 为 COS 上传动作补充真实 provider CLI/action 的本地 mock 示例，避免示例中的上传命令仍需人工替换。
- Joice workflow 下一阶段删除 `gh release create/upload`，改为 Debug/Release 分桶上传和 v2 回调。
- 旧 Release 同步完成并核对数量、摘要、manifest 后，再评估是否下线后台 legacy API。
