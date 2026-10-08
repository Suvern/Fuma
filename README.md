# Fuma

Fuma 是面向飞书团队的自托管移动端安装包管理与分发工具，使用 FastAPI、React 和 TypeScript。支持 Android / iOS 包管理、GitHub Release 导入、正式版本发布、临时下载授权及飞书群通知。

## 当前能力

- 本地管理员初始化与救援、飞书登录、全局管理员和应用维护者权限。
- GitHub PAT / GitHub App 连接、Release 检索、文件规则导入和定时同步。
- 分片上传、独立 APK / IPA 解析、正式包库、版本和按平台发布。
- 本机及 COS / OSS 存储、私有下载授权、独立公开副本与收回。
- GitHub Actions 来源复核、构建事件、飞书群卡片、持久任务与审计。

Android 灰度、TestFlight 和客户端自动更新协议尚未实现。功能边界、已知限制及公开发布前待办见[功能状态与路线图](docs/roadmap.md)。

## 本地开始

准备 Python 3.13、uv 0.12.7、Node.js 22.12+ 的 22 系列、pnpm 12.4.1，以及 Docker / Compose。在仓库根目录执行：

```sh
make setup
make infra-up
make migrate
make backend
```

API 保持运行；Worker、Scheduler 和前端分别在三个新的根目录终端启动，每个终端执行一条：

```sh
make worker
make scheduler
make frontend
```

访问 `http://127.0.0.1:5173/login`，使用 API 首次初始化日志中的随机 admin 密码登录并改密。开发数据库与 Redis 仅绑定本机端口，代码默认配置与之匹配。

完整上传流程还需要独立 parser，启动方式见[开发指南](docs/development.md)。前端 `pnpm dev` 从 `frontend/.env` 读取代理地址，未配置时连接本地；上述 `make frontend` 或 `pnpm --dir frontend dev:local` 始终连接本地后端。

## 文档与代码

| 入口 | 内容 |
| --- | --- |
| [文档目录](docs/README.md) | 开发、部署、架构、接入和功能状态 |
| [部署、升级与备份](docs/deployment.md) | Compose、外部 HTTPS 反代、持久卷及恢复要求 |
| [第三方接入](docs/integrations.md) | 飞书、GitHub、Actions 和 COS / OSS |
| [后端](backend/README.md) | API、领域服务、任务和数据库迁移 |
| [前端](frontend/README.md) | 页面、开发代理、请求安全和检查命令 |
| [接口契约](idl/README.md) | OpenAPI YAML 及 DTO / 类型生成 |
| [Actions 示例](deploy/github-actions-example.yml) | 源应用构建并回调 Fuma 的工作流 |

修改接口先编辑 IDL，再运行 `make idl` 同步契约。完整 `make check` 需按开发指南启动独立测试 PostgreSQL，设置测试入口与显式创建开关；测试会创建并回收随机数据库，不能使用业务实例。

本轮文档整理未执行 Docker 部署、真实第三方联调或手机安装验收。上线前应在目标环境完成登录、解析、发布下载、通知和备份恢复验证；IPA 可下载不表示设备可安装。

## 许可证

本项目使用 [MIT License](LICENSE)。
