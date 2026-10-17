# 13 测试与验收矩阵

## 1. 单元测试

- prefix 规范化与同桶冲突判断。
- v2 schema、签名、时间窗、幂等键。
- 事件 channel 到 binding 的解析；拒绝任意 URL/bucket。
- SHA-256、size、manifest 和 APK/IPA 元数据比对。
- ZIP 路径穿越、符号链接、压缩炸弹和多包选择。
- Debug/Release 状态机和 publish 权限。

## 2. 集成测试

| 场景 | 期望 |
|---|---|
| 私有 Debug 桶正常对象 | 自动 ready 并通知 |
| 公开 Debug 桶正常对象 | 仍完成 binding、checksum 校验后 ready |
| Debug/Release 不同桶 | 各自读取正确桶 |
| 同桶不同 prefix | 不跨 prefix 读取 |
| 同桶相同/父子 prefix | 配置保存被拒绝 |
| 重复 v2 事件 | 返回原结果，不重复建记录 |
| 同 key checksum 变化 | 进入 conflict，不能覆盖 |
| COS 对象不存在 | 可重试失败 |
| checksum 错误 | 终止，不 ready |
| Release ingest | pending_publish，不自动 published |
| 无权限 publish | 403/拒绝且无状态变化 |
| 发布前对象被替换 | publish 拒绝 |
| v1 GitHub callback | 兼容原结果 |

## 3. Joice workflow 验证

- 构建失败时不发送事件。
- 上传成功、通知失败时可重试通知，不重复上传。
- manifest 的 key、size、checksum 与 COS HEAD 一致。
- Debug 和 Release 的 key/prefix 不交叉。
- 主 workflow 不创建 GitHub Release 资产；legacy workflow 仍可手动执行。

## 4. 验收证据

每个环境保留 validation record：请求/事件摘要、ingestion ID、对象 key、checksum、状态变化、日志链接和截图/命令输出（脱敏）。使用 [验证模板](./templates/validation-record.md)。
