# 19 COS-first 管理主流程与安装包导入页

## 1. 本轮目标

本轮把 Fuma 的管理端收敛为“COS 是包源，GitHub 只是构建通知和来源审计”：

- 安装包导入独立成页，统一扫描 Debug/Release 两个 App 绑定桶；通知丢失时不需要伪造 GitHub Release。
- 版本发布页显示最新可分发 URL、当前启用 Release，以及可搜索的其他 Release。
- Actions 接入页聚焦接入文档和构建事件；分发规则移到“飞书通知”页，避免把通知规则误解为 GitHub 连接。
- 用固定的 `android/ios/harmony/<buildNumber>.zip` 目录约定和 `archive-1` ZIP 内容约定约束构建方。

## 2. 安装包导入页

入口：`/admin/apps/:id/imports`，只读取当前 App 的 Debug/Release binding，不读取 GitHub Release，也不读取全局资源池默认桶。

### 扫描与解析

1. 页面并行扫描两个 channel 的绑定前缀，合并对象列表并按 `channel:key` 去重。
2. “一键解析 manifest”逐个调用 COS 对象解析接口。服务端仍会重新 HEAD、下载、校验外层 SHA、解压并校验内部安装包，前端不会绕过对象校验。
3. 文件名/路径只用于推荐导入模式：包含 `debug/dev/snapshot/qa` 推荐 Debug，包含 `release/prod/store` 推荐 Release，否则使用对象所属 binding 的 channel。
4. 选择对象后可逐项覆盖 Debug/Release；列表展示绑定来源、对象 key、大小、解析状态和推荐模式。

### 批量导入

- 选中多项后一次提交多个现有导入请求，当前实现是前端并发/串行 fan-out，后端仍以每个对象的幂等键独立落库。
- 扫描得到的 ZIP 只有归档文件名时，版本/构建号按 `build-info.json` 优先、纯数字父目录/文件名次之；人工导入缺少 GitHub 上下文时标记 `commit_sha=manual-import`、`workflow_run_id=manual-import`，不伪造来源。
- Debug 导入沿用自动 ready 和飞书通知状态机；Release 导入沿用 `pending_publish`，必须在版本发布页确认后才可分发。
- 导入失败项保留在任务中心，成功项可由刷新后的对象扫描结果再次核对；重复对象由服务端幂等处理。

## 3. 版本发布页

版本页使用已发布的 Release publication 生成管理视图：

- “最新版本 URL”指最新已发布 Release 的固定分发地址。
- “启用中的 Release”当前只展示一个：按最新已发布 publication 作为唯一活动版本的产品视图；其余已发布版本进入“其他使用中的 Release”，支持按版本号、构建号、平台和 key 搜索。
- 这是当前 UI 层的单活动约定。后端仍保留历史的按平台默认 publication 能力，若未来要强制跨平台真正只能有一个活动版本，需要新增 active-release 约束和迁移，不能仅依赖前端排序。

## 4. Actions 与飞书通知的信息架构

- “Actions 接入”同时展示接入说明和构建事件，链接使用 `#build-events` 定位到事件区域。
- “飞书通知”承载通知模板、通知群和 Actions 分发规则；规则编辑不再要求 GitHub connector。
- GitHub 连接、仓库绑定和 Release API 继续作为后台兼容层，但不出现在新 App 主导航和新接入说明中。

## 5. 标准 COS 目录与 ZIP 契约

```text
<bucket-root>/<optional-fuma-prefix>/
├── android/<buildNumber>.zip
├── ios/<buildNumber>.zip
└── harmony/<buildNumber>.zip
```

每个 ZIP 必须包含且只能包含：

```text
<package>.apk 或 <package>.ipa
<package>.apk.sha256 或 <package>.ipa.sha256
build-info.json
```

`build-info.json` 最少包含 `schema_version: "archive-1"`、`commit`、`version`、`build_number`。回调中的 `object.key` 指向外层 ZIP，`manifest.key` 与其相同，`manifest.sha256` 为外层 ZIP SHA-256；内部安装包摘要用于解压后的完整性校验。文件名只使用构建号，版本和渠道从归档元数据、对象路径与导入选择共同确定。

### Harmony 说明

目录约定已为 Harmony 预留，但当前后端平台枚举和 Parser 仍以 Android/iOS 为主。未确认 Harmony 原生包扩展名和 manifest 字段前，不把 `harmony/` 对象标记为可发布；扫描可以展示并允许人工核对，解析器应返回“待补充平台契约”，而不是套用 Android 规则。

## 6. 本地验证与回滚

验证顺序：

1. `make idl-check`，确保 Task 类型和 COS 扫描 query 参数同步。
2. `pnpm --dir frontend lint`、`typecheck`、`test -- --run`，覆盖导入页、规则编辑和旧路由兼容。
3. 本地浏览器打开 App 的“导入安装包”，扫描测试桶对象，解析一个 Debug 和一个 Release；确认 Release 进入待发布而不是自动公开。
4. 打开“版本发布”，确认最新 URL、活动 Release 和搜索列表；打开“飞书通知”，确认规则仍可编辑；打开“Actions 接入”，确认文档和构建事件同页。
5. 使用一个错误摘要或不符合 ZIP 契约的对象验证失败任务可见，随后删除测试对象或停用 binding 即可回滚，不涉及线上数据。

## 7. 已知边界与后续切片

| 项目 | 当前状态 | 后续建议 |
|---|---|---|
| 批量导入 API | 前端对现有幂等接口 fan-out | 稳定后增加服务端批量接口，返回逐项结果和统一任务组 |
| 单一活动 Release | UI 按最新 publication 展示一个 | 增加数据库 active-release 约束和发布切换审计 |
| 人工导入元数据 | 无 GitHub 上下文时使用 `manual-import` | 可选读取 `build-info.json` 的完整 CI 字段，但不从文件名猜 commit |
| Harmony 原生包 | 目录已预留，Parser 未启用 | 先确认真实产物和 manifest，再新增平台契约/测试 |
| 旧 GitHub Release | 后台兼容保留 | 完成调用方迁移后再清理 API、任务和历史数据 |
