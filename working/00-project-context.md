# 00 项目上下文与术语

## 1. 目标

本方案解决 Joice GitHub Release 配额耗尽问题，并将 Fuma 的包管理切换为“以 COS 为唯一主来源，GitHub 只负责构建通知与来源审计”。方案不要求一次性切换所有历史数据，先改 Fuma，再改 Joice，最后按批次迁移历史 Release。

## 2. 术语

| 术语 | 定义 |
|---|---|
| App | Fuma 中承载一个应用的逻辑实体。存储绑定挂在 App 维度。 |
| Debug 包 | 面向测试/内测的构建产物，通常来自 Debug 构建；默认自动 ready。 |
| Release 包 | 面向正式发布的构建产物；自动入库后需要人工确认才 publish。 |
| v1 | 现有 GitHub Release 回调协议，使用 `release_id` 和 `asset_ids`。 |
| v2 | COS 上传完成后的事件协议，携带对象标识和构建元数据。 |
| StorageLocation | Fuma 已有的存储位置抽象，可表示 COS/OSS 等对象存储。 |
| prefix | 对应 channel 桶内的逻辑目录前缀，例如 `debug/`、`release/`；新配置不依赖同桶隔离。 |
| ready | Fuma 已完成下载、校验、解析并可供 Debug 使用的状态。 |
| publish | Release 包经过人工确认后，成为对外可见的正式包。 |
| 旧 Release | 已存在于 GitHub 的历史 Release 及其 APK/IPA 资产。 |

## 3. 范围内

- Fuma：配置模型、COS 对象读取、事件接收、解包解析、Debug/Release 状态机、管理界面和 OpenAPI。
- Joice：GitHub Actions 产物上传 COS、发送 v2 通知、移除 GitHub Release 上传步骤。
- 历史数据：GitHub Release 资产同步到 COS、清单、校验、重跑和失败处理。
- 兼容性：旧 v1 GitHub API 暂保留为后台兼容；新配置要求 Debug/Release 分别绑定独立存储桶；私有/公开桶可用。

## 4. 不在范围内

- 不改变 APK/IPA 业务解析规则；只增加 ZIP 外层处理和元数据校验。
- 不在本阶段替换所有现有对象存储供应商。
- 不删除 GitHub 历史 Release；迁移后是否清理由单独的容量与合规决策决定。

## 5. 总体约束

1. Fuma 的信任根是已配置的 App 存储位置和服务端凭证，而不是客户端传入的任意 URL。
2. 所有上传、通知、下载、入库、发布接口必须可幂等重试。
3. 任何“自动 ready”都必须建立在对象完整性、包类型、包名、版本号和 App 归属校验通过之上。
4. 人工发布必须保留操作者、时间、来源对象、校验值和确认结果的审计记录。
