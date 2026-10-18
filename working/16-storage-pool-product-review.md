# 16 存储桶资源池与 App 分发绑定复核

## 1. 审查范围

本次只审查本地 Fuma 管理端，不访问线上环境。复核页面：

- `/admin/settings/storage`：存储资源管理入口
- `/admin/apps/:id`：App 的 Debug / Release 分发绑定入口
- 安装包上传器：按 channel 选择原件存储位置的交互
- 后端上传默认路由：`POST /api/v1/apps/{id}/uploads`

本地审查时间：2026-10-18。浏览器使用当前本地登录会话，API 为本地 `127.0.0.1:8000`。

## 2. 用户目标

管理员应先登记并验证可用的 COS / OSS 存储桶，再在每个 App 内分别绑定 Debug 和 Release 的包源。之后：

1. 所有上传、COS 通知、扫描补导入都按 App + channel 的绑定路由。
2. Debug 与 Release 默认使用不同存储桶；不能用“全局默认桶”隐式决定来源。
3. GitHub 只提供 Actions workflow/run/commit 的来源审计，不成为包源或 Release 附件入口。

## 3. 当前走查结论

### 优点

- App 已经有 `AppStorageBinding` 数据模型和 Debug / Release 两个独立字段。
- 绑定保存时服务端和前端都拒绝相同 bucket，能避免用不同 prefix 假装分桶。
- COS 事件和手工补导入已经按 App/channel/prefix 校验对象范围。
- 安装包页已有按当前 channel 展示绑定桶的只读提示。

### 主要风险

1. 原 `/admin/settings/storage` 标题为“对象存储”，描述“默认位置只影响新上传”，并提供“设为默认”。这会让管理员误以为全局默认是 Fuma 的包分发来源。
2. App 绑定区域原名为“包存储绑定”，但没有把“唯一来源”放在标题层级，无法一眼区分资源池和 App 路由。
3. 走查时发现后端 `create_upload` 原本保留“没有 App binding 时回退 `StorageLocation.is_default`”的兼容分支；显式传入任意 `storage_location_id` 也没有在该入口再次核对 App/channel binding。这是本轮已修复的运行时约束缺口。
4. 全局资源模型仍保留 `is_default` 字段及 API，适合做旧客户端兼容，但不应继续出现在新产品路径中。

## 4. 本轮已执行调整

- 全局导航“对象存储”改为“存储桶资源”。
- 存储页改名为“存储桶资源池”，明确这里只管理可复用桶资源、凭据、健康状态，不决定 App 分发来源。
- 移除资源卡片中的“默认”展示和“设为默认”按钮；旧 API 暂不删除，作为兼容层保留。
- 新增从资源池直接进入“应用管理”的引导，要求完成 App/channel 绑定。
- App 区块改为“分发存储绑定”，明确它是该 App 的唯一包来源配置。
- Debug / Release 字段改为“包源存储桶”，对象前缀说明改为“该 App 的该 channel 只会读取和写入这个前缀”。
- 无可绑定资源时直接链接到“存储桶资源池”。
- 安装包上传器的只读提示改为“Debug / Release 包源存储桶”。

## 5. 目标信息架构

```text
存储桶资源池（全局资源登记）
  ├─ 新增 COS / OSS 连接
  ├─ 连接测试、凭据轮换、启停
  └─ 去应用管理绑定

App 设置（唯一分发路由）
  └─ 分发存储绑定
       ├─ Debug 包源：bucket + prefix
       └─ Release 包源：bucket + prefix

安装包 / COS 事件 / 补导入
  └─ 只接受当前 App + channel 绑定范围内的对象
```

## 6. 已完成的运行时收紧

本轮已将后端从“兼容回退”收紧为“绑定优先且不可绕过”：

1. `create_upload` 先读取 `AppStorageBindingRecord(app_id, channel)`；无绑定返回 `STORAGE_BINDING_REQUIRED`。
2. 请求中显式传入的 `storage_location_id` 必须等于该绑定，否则返回 `STORAGE_BINDING_MISMATCH`。
3. GitHub legacy import、旧 Debug persist 只允许走兼容迁移开关，不得成为新安装包上传的旁路。
4. `StorageLocation.is_default` 暂留数据库字段和旧 API，但新接口、新前端、新 Actions 文档不得依赖它。
5. 补充无绑定、显式错桶、绑定被停用、Debug/Release 同桶四类后端测试。

## 7. 本地验证清单

- [x] 存储页标题和导航显示“存储桶资源 / 存储桶资源池”。
- [x] 页面不再展示“默认”字样或“设为默认”按钮。
- [x] 存储页能链接到应用管理。
- [x] App 绑定标题、字段和空态明确表达 App/channel 唯一来源。
- [x] 后端拒绝无绑定上传。
- [x] 后端拒绝显式指定非绑定桶上传。
- [ ] 绑定停用后上传、COS 通知、补导入均返回可解释错误。
- [ ] 同一 App 的 Debug/Release 不同桶和不同前缀均有独立集成测试。

## 8. 产品决策

| 决策 | 结论 |
|---|---|
| 全局存储页定位 | 资源池，不是包分发配置 |
| App 分发来源 | App + channel binding 唯一决定 |
| Debug / Release | 默认独立桶；服务端拒绝同桶 |
| `is_default` | 兼容字段，退出新产品路径 |
| GitHub Release | 不在 Fuma 主导航和主流程出现 |
| 通知丢失 | 从绑定 COS 对象扫描并补导入 |
