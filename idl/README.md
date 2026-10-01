# 接口 IDL

`openapi.yaml` 是 **M1 全量接口的手写权威契约**。先修改并评审 YAML，再由后端与前端按同一契约实现。`openapi.json` 是 YAML 生成的版本快照，`frontend/src/generated/api.d.ts` 从 JSON 生成，均不得手改。

```sh
# 仓库根目录；无需启动数据库、Redis 或 API
make idl
make idl-check

# M1 发布门禁：全部设计路由、方法与 operationId 必须实现
uv run --directory backend python -m app.cli.export_openapi --check --check-implementation
```

生成器只读取 YAML，不再通过 FastAPI 的当前实现覆盖设计。`make idl-check` 验证 YAML → JSON → 前端类型同步；后端契约测试同时要求已实现接口是设计契约的子集。开发中子集检查通过不代表 M1 完成；交付时必须额外通过完整实现门禁，并对请求、响应、权限和业务行为运行集成测试。

- [M1 协作约定](M1-CONTRACT.md)：模块边界、请求约束、安全、状态和联调。
- [权威 YAML](openapi.yaml)：路径、具名请求 / 响应 Schema、枚举与稳定 operationId。
- [JSON 快照](openapi.json)：供类型生成及工具消费。
- [M1 范围](../docs/milestones/m1.md)：产品与验收要求。

运行时 `/api/openapi.json` 和 `/api/docs` 仅反映已实现接口，不能当成设计契约的替代品。完整 API 使用 `/api/v1`，时间为 UTC ISO 8601，内部 ID 为 UUID，外部 GitHub 数字 ID 为字符串。
