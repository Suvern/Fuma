# 前端

React、TypeScript、Vite、React Router、TanStack Query、openapi-fetch 和 Semi Design。页面使用生成的 API 契约，测试替身不参与运行时。

## 本地运行与检查

在 `frontend/` 执行：

```sh
pnpm install --frozen-lockfile
pnpm dev:local
```

访问 `http://127.0.0.1:5173`，API 代理到本机 `127.0.0.1:8000`。数据库、API、Worker、Scheduler 和 parser 的启动方式见[开发指南](../docs/development.md)。

普通 `pnpm dev` 从 `frontend/.env` 读取 `FUMA_API_PROXY_TARGET`，未配置时连接本机后端。可将 `frontend/.env.example` 复制为 `frontend/.env` 后修改地址；`.env` 仅留本地，示例文件不包含实际实例地址。修改后重启开发服务。

进程环境变量优先于文件配置。调试自己控制的远程实例时，也可以临时指定站点地址：

```sh
FUMA_API_PROXY_TARGET=https://fuma.example.com pnpm dev
```

地址只能包含 HTTP(S) 协议、主机及可选端口，不包含凭据、`/api`、查询参数或片段。`pnpm dev:local` 始终忽略代理配置，连接 `127.0.0.1:8000`。

远程模式的页面操作会写入所选服务。代理适配 Host、Origin 和 Cookie；须在本地页面重新登录。飞书 OAuth 及依赖远程绝对地址的下载仍须在远程站点验证。本地配置只供开发服务器读取，不注入浏览器；构建、预览和测试不加载本机 dotenv。第三方凭据仍只保存在后端。

```sh
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm check:api
```

生产 [Dockerfile](Dockerfile) 将构建结果交给 Caddy，使用同域名提供 SPA 和 `/api`。本轮文档重建未执行镜像部署；生产拓扑见[部署指南](../docs/deployment.md)。

## 页面与代码

| 页面范围 | 功能 |
| --- | --- |
| `/login`、`/auth/error` | 登录、首次改密引导、飞书错误返回 |
| `/`、`/apps/:id`、`/debug/:id` | 私有 Debug 目录、缓存准备、临时下载和固定页面分享 |
| `/releases`、`/releases/:id` | 正式发布列表及详情 |
| `/docs/github-actions` | Actions 接入说明 |
| `/admin/apps` 及应用详情 | 应用、平台、包标识、仓库、归档与恢复 |
| 应用内 Releases、Debug、Packages、Versions | GitHub 导入、Debug 管理、正式包库、版本发布 |
| `/admin/connectors`、`/admin/settings/storage` | GitHub Connector 与存储位置 |
| `/admin/settings/feishu`、`/admin/settings/members` | 飞书租户、机器人、成员角色及应用范围 |
| Actions、Events、Notifications、Tasks | 规则、构建阶段、通知和异步任务 |
| `/admin/audit`、Cache、Account | 审计、缓存预算、账号和会话 |

实际路由以 [router.tsx](src/app/router.tsx) 为准。`src/features/m1/` 是历史目录名，包含多个阶段的业务；正式包和存储页面位于 `src/features/library/`。

- `src/app/`：路由、布局、QueryClient 和样式。
- `src/shared/api/`：CSRF、版本条件、幂等标识、标准错误与生成类型接入。
- `src/shared/ui/`：共用表单、分页、状态与交互控件。
- `src/generated/api.d.ts`：生成文件，通过根目录 `make idl` 同步，不手动修改。

## 交互与安全约定

使用 Semi Design 默认主题和 tokens，共用布局适配桌面及移动端。导航与登录页统一使用 `BrandMark`；更新品牌素材时同步浏览器图标和 manifest 图标。服务端决定权限，前端守卫只负责交互引导。

Cookie 写请求先获取浏览器上下文及 CSRF。契约规定的修改携带 `If-Match`，异步命令使用 UUID 幂等键。网络失败后，明确重试同一意图时复用键；不自动重放令牌签发或外部通知。登录、退出及改密后清理旧身份缓存。

临时下载链接只放组件内存，不进入持久存储、日志或分享二维码。冷缓存返回 202 后轮询准备状态，就绪后重新鉴权获取链接。大文件交给浏览器下载，不完整读入 Blob；固定分享页与临时下载 URL 分开。

Vitest 检查请求及界面行为，不能证明飞书可用范围、真实 GitHub Actions、云对象收回或手机安装成功。完整接入边界见[第三方接入](../docs/integrations.md)。
