# 03 App 存储绑定与配置模型

## 1. 设计目标

把“包从哪里来”从隐含的 GitHub 配置提升为 App 的显式 COS 配置。Debug 和 Release 默认且新配置必须使用不同存储桶，避免把环境隔离寄托在 prefix 约定上。配置变更必须可审计、可校验、可回滚。

## 2. 建议数据模型

不直接在 App 表增加过多供应商字段，优先复用 `StorageLocation`：

```text
App
  debug_storage_location_id  -> StorageLocation.id
  release_storage_location_id -> StorageLocation.id
  debug_object_prefix
  release_object_prefix
  storage_binding_version
  updated_at / updated_by
```

如当前 ORM 不适合直接扩展 App，可增加 `app_package_storage_bindings`：

```text
app_id
channel                 # debug | release
storage_location_id
object_prefix
enabled
created_at / updated_at
created_by / updated_by
```

同一 App + channel 只允许一个 active binding。历史 binding 不删除，便于回溯旧包。

## 3. 校验规则

- `debug_storage_location_id` 和 `release_storage_location_id` 必须不同；两个 channel 的 bucket identity 不能相同。
- prefix 必须是规范化相对 key 前缀，禁止以 `/` 开头、禁止 `..`、控制字符和空白歧义。
- prefix 仍需规范化，并且只能在对应 channel 的独立 bucket 内使用；不再支持同桶 prefix 隔离。
- binding 保存前执行一次“列举/HEAD 测试对象”能力检查；生产环境必须避免把真实 secret 回显到错误信息。
- 变更 binding 不自动重写历史记录；新事件按事件到达时的 binding 处理，历史记录保留 resolved location/key。

## 4. 管理 API

建议提供：

- `GET /apps/{appId}/package-storage`：查看当前 Debug/Release 绑定、prefix、连通性状态。
- `PUT /apps/{appId}/package-storage`：幂等保存配置，返回规范化配置和校验结果。
- `POST /apps/{appId}/package-storage/validate`：不落库地验证 bucket、prefix、读权限和写入/读取测试对象。
- `GET /apps/{appId}/package-storage/audit`：查看绑定变更审计。

权限：配置写入至少要求 App 管理权限；Release binding 变更建议增加管理员权限或二次确认。

## 5. 迁移顺序

1. 增加可空字段/表和索引，不改变现有 v1 行为。
2. 为现有 App 生成兼容 binding：先把原有默认存储映射为 release 或 legacy binding。
3. 补齐 Debug/Release 配置页和 API。
4. 完成配置校验后，再开启 v2 事件。

## 6. 本地验证

- 使用内存数据库或测试数据库覆盖：不同桶、同桶拒绝、缺少 binding、禁用 binding。
- 对同一 App 并发更新 binding，确认不会产生两个 active 配置。
- 用伪造 bucket/URL 的 v2 事件验证 Fuma 仍按服务端 binding 读取。

## 7. 第一条垂直切片实现记录（2026-10-17）

已落地但仍属于迁移中间态的能力：

- 新增 `app_storage_bindings` 表，主键为 `app_id + channel`，`channel` 限定为 `debug/release`；外键关联 App 和 `StorageLocation`。
- 新增 `GET/PUT /api/v1/apps/{id}/package-storage`，写入使用 `If-Match` 校验 App revision，变更写入审计事件 `app.package_storage.update`。
- 服务端会 trim 首尾 `/`，拒绝空前缀、`.`、`..`、控制字符；Debug/Release 绑定相同 bucket 时拒绝。
- 只允许 `enabled=true` 且 `status=ready` 的 StorageLocation；不回显凭据。
- App 设置页新增 Debug/Release 两组选择与 prefix 编辑，明确标注“存储桶”；前端和服务端都拒绝相同 bucket，未绑定 channel 的 COS 操作直接拒绝。
- 现有分片上传接口始终按上传 `mode` 读取 App 绑定；管理页上传器不再提供系统默认/本机选项。显式传入的 `storage_location_id` 也必须与当前 App/channel 绑定一致；无绑定或错桶直接返回 `STORAGE_BINDING_REQUIRED` / `STORAGE_BINDING_MISMATCH`。

本切片暂未实现：连接测试对象、旧 binding 自动迁移和对象级审计历史。这些能力分别在第 5、11 阶段实现。COS v2 webhook 和“从 COS 导入”均强制要求对应 channel 存在可用 binding；未绑定时直接拒绝，不接受事件或请求中的任意 bucket/URL。现有 GitHub Release v1 和本地上传兼容入口暂不删除，但不属于 COS 主路径。
