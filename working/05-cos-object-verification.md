# 05 COS 对象校验与安全边界

## 1. 信任边界

Fuma 只信任：App 的存储 binding、服务端凭证、v2 签名、对象 key 规范、对象 checksum 和解析结果。事件中的 `url`、`bucket`、`endpoint` 不得直接用于下载；如保留字段，只能用于与 binding 严格比对并记录诊断。

当前已落地的第一步是：事件只能引用 App 已绑定且 `ready` 的存储位置，object/manifest
key 必须落在 `location.prefix + binding.object_prefix` 下，拒绝空路径、`.`、`..` 和目录对象。
后台任务使用服务端 Adapter 做 HEAD，校验对象大小；若云端返回 `sha256` 元数据则同时比对，随后通过短时签名 URL 流式下载对象和 manifest，计算并比对完整 SHA-256。由于 Joice 上传是否能写入自定义元数据尚未确认，元数据只作为加速校验，不能替代内容摘要。

## 2. 私有桶

- Fuma 使用服务端配置的最小权限读取凭证，至少限制到指定 bucket/prefix 的 `HeadObject`、`GetObject`。
- 凭证通过现有 secret manager 或运行环境注入，数据库只存引用，不存明文。
- 下载过程使用流式读取和大小上限，避免一次性把超大包载入内存。
- 对象下载失败区分权限、网络、对象不存在和 checksum 不匹配，便于重试。

## 3. 公开桶

- 公开可读不等于可信；仍须校验 bucket/prefix、size、checksum、manifest 和包内容。
- 优先使用服务端 SDK 访问或构造固定域名 URL；禁止接受事件携带的任意外链。
- 若必须使用 CDN URL，应由 binding 配置域名和 key 拼接，禁止重定向到未配置域名。

## 4. ZIP 安全

- ZIP 解包到每次任务独立临时目录；目录放在运行时临时目录，不写入仓库。
- 拒绝绝对路径、`..` 路径、符号链接、过深目录、压缩炸弹和超出解压后大小上限的压缩包。
- manifest 指定唯一 APK/IPA；多包时必须按明确规则选择，不能按目录遍历顺序随机选。
- 解包后再次计算内层文件 checksum；Parser 只接收允许扩展名和声明的文件。
- 任务结束清理临时文件；失败时只保留审计所需的 key、checksum 和错误摘要。

## 5. 元数据校验

至少校验：App ID、channel、版本、build number、包名、平台、对象 key、对象大小、SHA-256、上传时间。解析出的包名/版本与 manifest 不一致时拒绝 ready。

## 6. 审计与观测

记录 `event_id`、object key、resolved storage location、checksum、开始/结束时间、校验阶段、失败分类、操作者（如人工 publish）。日志禁止打印 access key、secret、完整签名和长期 URL。
