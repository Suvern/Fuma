# 17 桶根目录布局与凭据档案

## 1. 本轮确认

用户的 COS 约定是桶根目录下直接放 `android/`、`ios/`，目录内是构建 ZIP；同一组 SecretId/SecretKey 可能服务多个 Debug/Release 桶。Fuma 不应强迫管理员为每个桶重复输入同一组密钥，也不应把 `/` 当成非法前缀。

## 2. 目标交互

### 新增桶

1. “Fuma 资源池路径前缀”改为可选。
2. 留空、输入 `/` 或输入带首尾 `/` 的值都会归一化为相对前缀；空值表示桶根目录。
3. 凭据选择改为“新建凭据档案 / 选择已有凭据档案”。已有档案只显示名称、云厂商、访问标识掩码和已绑定桶数量，不回显 Secret。
4. 新桶只保存 `credential_id`，同一凭据可绑定多个桶；旧位置仍可使用旧的桶专属密文。

### App channel 绑定

App 的 Debug / Release `object_prefix` 同样允许为空。此时绑定范围就是对应桶（和资源池前缀）下的根目录，`android/`、`ios/` 等平台目录由构建清单和对象 key 表达。

## 3. 数据模型

`storage_credentials` 保存凭据档案：名称、云厂商、访问标识掩码、启停和 revision，以及加密的当前/候选密文。密钥作用域为 `storage-credential:<id>`，不保存或返回 Secret 明文。

`storage_locations.credential_id` 指向档案。旧的 `encrypted_credentials` 和 `candidate_credentials` 暂留作为兼容镜像，以便旧 worker 回滚；新代码读取优先使用共享档案。

## 4. 安全边界

- 桶、地域、读取模式仍属于 `StorageLocation`，不能被凭据档案覆盖。
- 选择已有档案时，服务端校验 provider 一致且档案启用；客户端传入重复密钥会被拒绝。
- 空根前缀仍拒绝绝对路径、空路径段、`.`、`..`，只放宽“必须有专用非空前缀”的旧约束。
- Debug/Release 仍必须绑定不同桶；根目录不会绕过 App/channel 绑定。

## 5. 本地验收

- `prefix="/"` 和 `prefix=""` 创建结果均为 `prefix=""`。
- 第一桶创建凭据档案，第二桶仅选择 `credential_id` 即可创建；列表只显示掩码和绑定数量。
- 连接测试、凭据轮换、旧桶密文兼容测试通过。
- App channel 绑定可以保存空 `object_prefix`，对象校验允许 `android/<file>`、`ios/<file>`，仍拒绝越界 key。

## 6. 构建 ZIP 兼容边界

Fuma 的主格式是绑定桶下的标准归档：`android/<buildNumber>.zip`、`ios/<buildNumber>.zip` 或 `harmony/<buildNumber>.zip`。ZIP 内必须只有一个 APK/IPA、对应 `.sha256` 和 `build-info.json`；平台目录和内部包类型不一致、多个安装包、缺少摘要或元数据都会拒绝。分发原件仍是已校验的外层 ZIP，manifest 的 key/sha 指向外层 ZIP。

当前解析器已经对 Android/iOS 外层归档做完整校验；Harmony 目录先作为标准对象布局保留，若后续需要 Harmony 原生安装包，应在确认包扩展名和元数据字段后补充独立 Parser 契约，不把 Android Parser 误用于 Harmony。
