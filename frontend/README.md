# Frontend

React + TypeScript + Vite，React Router 提供前后台路由，TanStack Query 管理查询，openapi-fetch 使用 `idl/` 生成的契约类型。M1 页面连接真实 API；测试中的替身不参与运行时。

## 运行与检查

```sh
pnpm install --frozen-lockfile
npm run dev
pnpm lint
pnpm test
pnpm build
pnpm check:api
```

在 `frontend/` 运行 `npm run dev`（也可用 `pnpm dev`），访问 `http://127.0.0.1:5173`，即可热更新调试本地前端，无需启动本地后端、数据库或 Redis。`/api` 默认代理到 `https://fuma.joice.tech`，页面上的修改会写入该远程服务。

可通过进程环境变量切换远程服务（填写站点地址，不包含 `/api`）：

```sh
FUMA_API_PROXY_TARGET=https://your-fuma.example.com npm run dev
```

代理保留 `/api` 路径，适配远程 Host、同源请求的 Origin，以及生产会话 Cookie，使本地 HTTP 页面可以登录并提交表单。请在本地登录页重新登录，远程域名的登录态不会自动共享。飞书 OAuth 仍使用远程服务登记的回调地址，该流程及依赖远程绝对地址的下载需在远程站点验证。

需要连接本机 `127.0.0.1:8000` 时运行 `npm run dev:local`（或 `pnpm dev:local`）；后端及原生 PostgreSQL / Redis 启动顺序见[开发文档](../docs/development.md)。开发服务仅监听回环地址 `127.0.0.1:5173`。Vite 不读取 `.env`，凭据只配置在服务端。代理配置参考 [Vite server.proxy](https://vite.dev/config/server-options#server-proxy)。

生产 [Dockerfile](Dockerfile) 将 `pnpm build` 结果交给 Caddy，使用同一域名提供 SPA 与 `/api` 反向代理；缓存文件不复制到静态目录。镜像构建及部署尚未验证，步骤见[部署文档](../docs/deployment.md)。

## 界面规范

前后台统一使用 Semi Design 默认主题，React 19 对应 `@douyinfe/semi-ui-19`，图标来自 `@douyinfe/semi-icons`。颜色、圆角与字体使用 Semi tokens；`src/app/styles.css` 仅维护布局、响应式和业务内容排列，不覆盖组件的设计语言。

组件按路径导入，入口加载 Semi 基础主题；业务路由按需加载。共用控件位于 `src/shared/ui/`：保留原生 FormData、约束校验、只读和提交语义，渲染 Semi Input / Checkbox / Button；弹窗、确认、导航、筛选、分页及数据表使用 Semi 组件。移动端使用 SideSheet 导航与可滚动表格。

Fuma 品牌头像采用风马的银白面甲、蓝色额纹与暖白双眼，由 `BrandMark` 统一用于前后台导航和登录页；登录卡片顶部突出展示头像与 Fuma 字样。页面资源为 `src/assets/fuma-mark.png`（256px 透明 PNG）；浏览器图标位于 `public/favicon.ico`（16/32/48px）及 `public/icons/`，同时提供 Apple 触屏图标（180px）和 manifest 图标（192/512px）。更新品牌时需同步这些尺寸；业务应用各自上传的图标不属于 Fuma 品牌资源。

仓库绑定使用远程搜索 Select，300ms 防抖，支持分页追加、空结果、错误重试、键盘选择及手动填写。连接 ID 和搜索条件隔离查询缓存，切换连接清空仓库选择，并将 AbortSignal 传给请求；只有点击「验证并绑定」才保存。测试覆盖迟到响应、分页选择、失败重试和旧选择不遮挡空结果。

## 页面

| 路由                                               | 功能                                                                    |
| -------------------------------------------------- | ----------------------------------------------------------------------- |
| `/login`                                           | 使用启动日志中的随机初始密码登录 admin、飞书错误返回                    |
| `/`、`/apps/:id`                                   | 飞书身份守卫、App 目录、搜索和平台过滤、Debug 列表                      |
| `/debug/:id`                                       | 文件与版本详情、缓存准备、临时下载、有效期、固定页面分享和二维码        |
| `/admin`                                           | 服务健康、Worker / Scheduler 心跳、模块入口                             |
| `/admin/apps`、`/admin/apps/:id`                   | App 创建、编辑、启停、删除、平台与仓库绑定                              |
| `/admin/connectors`                                | GitHub PAT 创建与替换、测试 Contents / Actions 权限、启停和删除         |
| `/admin/apps/:id/releases`                         | 完整同步快照检索、Tag / 预发布 / 文件筛选、批量选择安装包               |
| `/admin/apps/:id/debug`、`/admin/debug/:id`        | Debug 条目与来源快照、启停、缓存与重试                                  |
| `/admin/settings/feishu`                           | 自建应用配置、管理员 OAuth 绑定证明、单机器人、所在群分页搜索、测试卡片 |
| `/admin/apps/:id/actions`                          | workflow / ref / 文件规则、选择群、CI token 签发 / 轮换 / 撤销          |
| `/admin/apps/:id/events`、`/admin/events/:id`      | 构建状态、逐阶段和逐文件结果、失败阶段重试                              |
| `/admin/notifications`、`/admin/notifications/:id` | 群通知、卡片内容、投递结果与明确确认后的未知结果重试                    |
| `/admin/tasks`、`/admin/tasks/:id`                 | 任务查询、轮询、错误与重试                                              |
| `/admin/audit`                                     | 按关键词、操作和时间范围查询审计摘要                                    |
| `/admin/settings/cache`                            | 缓存预算、临时链接 TTL、并发与安全清理                                  |
| `/admin/settings/account`                          | 首次登录强制改密、密码修改、撤销旧会话并轮换当前会话                    |

## 代码组织

- `src/features/m1/`：M1 业务页面及流程测试。
- `src/shared/api/http.ts`：契约类型、CSRF、版本条件、幂等标识和标准错误。
- `src/shared/ui/`：表单、分页、状态、操作反馈、固定页面分享。
- `src/app/`：会话守卫后的布局、路由、QueryClient 和响应式样式。
- `src/generated/api.d.ts`：仅由 `pnpm generate:api` 生成，IDL 修改使用根目录 `make idl`。

首次启动由服务端自动创建 `admin`，随机初始密码仅写入 API 启动日志；Docker Compose 部署可运行 `docker compose --env-file .env -f deploy/compose.yml logs api` 查看。首次登录跳转改密页，修改前不会挂载其他后台页面或发起其业务请求；新密码不能与旧密码相同。改密后刷新服务端会话，再返回原页面。

全部写请求先读取浏览器上下文获得 CSRF；支持的修改携带 `If-Match`，异步命令携带 UUID 幂等键。网络失败后手动重试复用同一意图键；不会自动重放令牌签发或外部通知。登录、退出和改密清空旧身份的查询缓存。服务端仍需独立实施权限校验。

临时下载 URL 仅存于组件内存；不写入 QueryClient、localStorage、日志或分享二维码。冷缓存响应 202 后轮询 preparation，就绪后再次授权，使用新幂等键获取链接。大文件通过普通下载链接交给浏览器，不读取为 Blob。链接截止后 UI 移除入口，服务端负责最终过期判定。

## 验证边界

Vitest 覆盖请求安全头、CSRF 失败停止写入、站内返回地址、管理员和下载者隔离、冷缓存授权流程、未知投递确认、登录清缓存和手动重试。测试替身不能证明飞书可用范围、机器人权限、真实 GitHub Actions、域名 HTTPS 或手机安装；这些需要准备真实资源后联调。
