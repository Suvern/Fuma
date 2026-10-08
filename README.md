<p align="center">
  <img src="frontend/public/icons/fuma-512.png" width="128" height="128" alt="Fuma Logo">
</p>

<h1 align="center">Fuma</h1>

<p align="center">
  <strong>面向飞书团队的自托管移动端安装包管理与分发工具</strong>
</p>

<p align="center">
  从安装包入库到版本发布，让团队在一个地方管理、分发和获取 Android / iOS 安装包。
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-0284c7?style=flat-square" alt="原创代码与文档：MIT License"></a>
  <img src="https://img.shields.io/badge/Platform-Android%20%2F%20iOS-0f766e?style=flat-square" alt="支持平台：Android / iOS">
</p>

<p align="center">
  <a href="docs/deployment.md">部署指南</a> ·
  <a href="docs/development.md">开发指南</a> ·
  <a href="docs/integrations.md">第三方接入</a> ·
  <a href="docs/roadmap.md">功能与路线图</a>
</p>

---

## 为团队集中管理安装包

Fuma 将安装包、发布版本与下载权限放在同一套工作流中。开发者可以上传 APK / IPA，或从 GitHub Release 导入构建产物；团队通过飞书登录获取下载资格，并通过群通知了解发布动态。

**上传或导入 → 解析入库 → 发布版本 → 授权下载**

| 能力 | 可以做什么 |
| --- | --- |
| **安装包管理** | 分片上传、SHA-256 校验、独立 APK / IPA 解析，区分 Android / iOS 与 Debug / Release 包。 |
| **GitHub 导入** | 通过 PAT 或 GitHub App 连接仓库，检索 Release、按文件规则导入并定时同步。 |
| **版本发布** | 管理正式包和版本，按平台发布、设置默认版本或下架；入库与发布分别控制。 |
| **权限与下载** | 飞书登录、全局管理员与应用维护者权限、私有下载授权和临时下载链接；支持本地管理员初始化与救援。 |
| **文件存储** | 使用本机、腾讯云 COS 或阿里云 OSS，管理独立的云端公开副本及其收回。 |
| **飞书通知** | 接收 GitHub Actions 构建事件、复核来源，并通过飞书群卡片传递结果；提供持久任务与审计记录。 |

## 开始使用

### 自托管部署

准备 Docker Engine / Desktop、Compose、自有域名与外部 HTTPS 反向代理，按[部署、升级与备份指南](docs/deployment.md)完成配置与启动。

部署模板包含数据库、Redis、API、Worker、Scheduler、隔离 Parser 和 Web。指南覆盖首次登录、反向代理、持久卷、升级以及备份恢复；飞书、GitHub 与云存储配置见[第三方接入](docs/integrations.md)。

### 本地开发

基于 **FastAPI · React · TypeScript**，接口通过 OpenAPI 契约维护。

<details>
<summary><strong>展开本地启动步骤</strong></summary>

准备 Python 3.13、uv 0.12.7、Node.js 22.12+ 的 22 系列、pnpm 12.4.1，以及 Docker / Compose。在仓库根目录执行：

```sh
make setup
make infra-up
make migrate
make backend
```

保持 API 运行，等待首次初始化完成；再分别打开三个位于仓库根目录的新终端，每个终端执行一条命令：

| 终端 | 命令 |
| --- | --- |
| Worker | `make worker` |
| Scheduler | `make scheduler` |
| 前端 | `make frontend` |

访问 [本地登录页](http://127.0.0.1:5173/login)，使用 API 首次初始化日志中的随机 `admin` 密码登录并改密。开发数据库与 Redis 仅绑定本机端口，代码默认配置与之匹配。

**完整上传流程还需要独立 Parser。** 按[开发指南](docs/development.md#启动隔离-parser)启动解析容器，否则安装包不会完成解析。

`make frontend` 始终连接本机后端。普通 `pnpm dev` 会从 `frontend/.env` 读取代理地址，未配置时也连接本机；配置方式见[前端说明](frontend/README.md)。

修改接口先编辑 IDL，再运行 `make idl` 同步契约。运行完整 `make check` 前，需按[开发指南](docs/development.md#测试与检查)准备独立测试 PostgreSQL，设置测试入口与显式创建开关；测试会创建并回收随机数据库，不能使用业务实例。

</details>

## 文档导航

| 场景 | 入口 |
| --- | --- |
| 了解项目 | [文档目录](docs/README.md) · [当前架构](docs/architecture.md) · [功能状态与路线图](docs/roadmap.md) |
| 部署与运维 | [部署、升级与备份](docs/deployment.md) |
| 配置外部服务 | [飞书、GitHub、COS / OSS 接入](docs/integrations.md) · [GitHub Actions 示例](deploy/github-actions-example.yml) |
| 参与开发 | [开发指南](docs/development.md) · [后端](backend/README.md) · [前端](frontend/README.md) · [接口契约](idl/README.md) |

## 项目状态

后端、前端与解析器已通过本地 Docker 镜像构建及独立容器检查，具体环境和验证范围见[部署指南](docs/deployment.md)。完整 Compose 联调、真实第三方服务和真机安装仍待验收；上线前应在目标环境验证登录、解析、发布下载、通知与备份恢复。

Android 灰度、TestFlight 和客户端自动更新协议尚未实现。IPA 可以下载不代表设备具备安装资格。已知限制与后续方向见[功能状态与路线图](docs/roadmap.md)。

## 名称与版权

项目名称 **Fuma** 来自《泰迦奥特曼》中的“风马奥特曼”（Ultraman Fuma），角色介绍见[圆谷官方资料](https://m-78.jp/news/post-5101)。

项目 Logo / 头像版权属于圆谷公司（円谷プロダクション / Tsuburaya Productions）。© 円谷プロダクション。本项目为非官方项目，与圆谷公司不存在隶属、赞助或认可关系。

头像、角色形象及相关第三方品牌素材不属于本项目 MIT 许可证的授权范围；版权标注不代表已获得素材使用或再分发授权。

## 许可证

本项目原创代码与文档使用 [MIT License](LICENSE)。第三方依赖遵循各自许可证，Logo / 头像及相关角色素材的权利说明见上文。

发布产物中的声明位置和第三方许可边界见[第三方声明](THIRD_PARTY_NOTICES.md)，生成及校验方法见[开发指南](docs/development.md#发布前安全与许可证检查)。
