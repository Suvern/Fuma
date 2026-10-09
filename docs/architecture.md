# 当前架构

Fuma 采用模块化单体 API、独立异步进程和离线安装包解析器。每套部署绑定一个飞书租户，业务状态以 PostgreSQL 为准；安装包文件不存入数据库。

## 服务与职责

| 服务 | 职责 | 关键依赖 |
| --- | --- | --- |
| Web | Caddy 提供 React 静态资源并转发 `/api` | API；外部 HTTPS 反向代理 |
| API | 登录、鉴权、查询、上传分片、创建持久任务、下载授权 | PostgreSQL、Redis、共享卷 |
| Worker | 下载缓存、导入解析协调、云存储、发布收回和通知 | PostgreSQL、Redis、共享卷、外部服务 |
| Scheduler | 扫描待执行及租约过期的任务、周期检查和清理 | PostgreSQL、Redis |
| Parser | 在受限子进程中解析 APK / IPA | 只读 inbox、可写 outbox；无网络 |
| Migrate | 运行 Alembic 迁移后退出 | PostgreSQL |

生产入口为外部 HTTPS 反代 → 宿主机 5888 → Caddy → API。容器内 Caddy 使用 HTTP，不负责本模板的公网证书；完整配置见[部署指南](deployment.md)。API、Worker 共用状态、缓存和解析交换卷。当前拓扑主要面向单机，不提供现成的多机共享文件方案。

## 技术栈和代码入口

后端使用 Python 3.13、FastAPI、Pydantic、同步 SQLAlchemy、psycopg、Celery 和 Redis 客户端。前端使用 React、TypeScript、Vite、React Router、TanStack Query、openapi-fetch 和 Semi Design。

- `backend/app/api/`：HTTP 路由、请求依赖、契约及权限入口。
- `backend/app/domains/`：账号权限、应用、GitHub、分发、正式包库、存储、审计和系统状态。
- `backend/app/integrations/`：飞书及 GitHub 调用和错误转换；云存储适配器位于 storage 领域。
- `backend/app/workers/`：Celery 包装、任务调度与重试。
- `parser/`：文件交换服务及 APK / IPA 解析命令。
- `frontend/src/features/`：功能页面；`m1` 是历史目录名称，并不表示其中只包含首期功能。
- `idl/`：手写 OpenAPI YAML 及生成链，详见[接口说明](../idl/README.md)。

常规数据库端点使用同步 Session；流式上传异步读取请求体，将数据库操作移入线程池。Session 不跨请求或进程共享。API 不自动建表，迁移作为独立步骤执行。

## 安装包与发布流程

上传先登记大小、平台、模式及目标存储，分片带 SHA-256；提交后创建数据库任务。Worker 合并、校验分片，把待解析文件及请求放入 inbox。Parser 写出受限大小的元数据结果，Worker 再校验摘要、包标识和构建号冲突，保存正式包。

正式包、版本、平台发布分别建模。入库不自动发布；发布后文件集合冻结，默认展示版本单独指定。云公开发布使用独立副本，不将私有原件直接改为公开。下架先阻止新授权，再执行公开副本收回；收回失败必须保留可见状态并重试。

旧 Debug 条目保留 GitHub 来源快照和本机缓存流程，可显式持久化到正式包库。普通 Release 规则导入、正式包导入与 Actions Debug 分发的发布语义不同，不能把所有导入都理解为正式发布。

## 身份和安全边界

内置本地 admin 用于初始化、管理与救援，完成首次改密后可使用当前会话浏览下载门户和下载私有安装包，无需再登录飞书。管理员下载仍校验账号、会话以及应用、平台和发布状态。飞书用户可被授予全局管理员、指定 App 维护者或仅下载身份，下载时仍需通过飞书租户、配置版本和资格有效期校验。

浏览器使用服务端会话；生产 Cookie 为 Secure、HttpOnly、SameSite=Lax。Cookie 写请求检查 Origin 和 CSRF。部分资源修改要求 `If-Match`，异步命令按契约使用幂等键。后台资源范围由服务器检查，执行中的人工任务也复查发起者权限。

外部凭据加密存储，持久根密钥与数据库指纹绑定。日志和审计避免记录原始 provider 响应、认证头及临时下载 URL。初始管理员密码只在首次创建时输出到 API 日志。

私有下载先鉴权再签发短时链接；链接有效期内可能被转发使用，已下载文件不能收回。公开副本收回有异步失败边界。详细接入约束见[第三方接入](integrations.md)。

## 异步恢复与可观察性

任务先落 PostgreSQL，Redis 负责投递。Scheduler 扫描排队和租约过期的任务，Worker 记录阶段、结果和重试条件。进程重启后按数据库状态恢复，不把 Redis 当成唯一业务记录。

通知的“成功”指提供方接受请求；结果未知时不自动重发，避免重复消息。健康接口分别说明进程存活及数据库 / Redis 连通性；管理页另外展示 Worker / Scheduler 心跳，它们不能代替业务链路验收。

分发统计只覆盖代码记录的授权及本机传输请求、字节；云直链实际读取和设备安装不在本机可观察范围内。当前限制和后续工作见[功能状态](roadmap.md)。
