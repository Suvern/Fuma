# 接口契约

[openapi.yaml](openapi.yaml) 是手写权威契约。先修改并评审 YAML，再同步实现和生成文件；契约定义不代表某个功能已经完成真实环境验收。

| 文件 | 来源 |
| --- | --- |
| `openapi.yaml` | 手写路径、请求 / 响应 Schema、枚举与 operationId |
| `openapi.json` | YAML 生成的 JSON 快照 |
| `../backend/app/api/contracts.py` | YAML 生成的后端 DTO |
| `../frontend/src/generated/api.d.ts` | JSON 生成的前端类型 |

在仓库根目录执行，无需启动数据库、Redis 或 API：

```sh
make idl
make idl-check
uv run --directory backend python -m app.cli.export_openapi --check --check-implementation
```

`make idl-check` 验证生成文件同步；完整实现检查核对路由、方法和 operationId。二者都不能替代请求响应校验、权限、生命周期和失败恢复测试。

API 使用 `/api/v1`，时间为 UTC ISO 8601，内部 ID 为 UUID，GitHub 数字 ID 使用字符串。运行时 `/api/openapi.json` 和 `/api/docs` 反映已实现接口；生产 Caddy 屏蔽这两个入口。

[M1-CONTRACT.md](M1-CONTRACT.md) 保留历史文件名，内容为当前接口协作约定。功能范围与限制见[功能状态](../docs/roadmap.md)，启动和测试方式见[开发指南](../docs/development.md)。
