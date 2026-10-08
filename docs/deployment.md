# 部署、升级与备份

本指南依据当前 [Compose](../deploy/compose.yml)、[Caddyfile](../deploy/Caddyfile) 和 Dockerfile 编写。已完成下述本地镜像验证；完整 Compose 部署、公网部署、证书签发和恢复演练仍待执行，首次部署须在目标环境完成文末验收。

2026-10-08 使用本机 Docker Engine 29.7.2（linux/arm64）完成后端、前端和解析器镜像构建，并在禁用网络、只读根文件系统的容器中验证：

- 三个镜像中的 MIT 许可证及第三方说明与仓库原文一致；后端携带 60 项 Python 依赖的许可正文。
- 后端以非 root 用户执行 cryptography 50.0.2 的 AES-GCM 加解密及 RSA 签名验证。
- Caddy 配置校验通过，首页、许可证和第三方声明可通过容器内 HTTP 访问；前端包含 27 项打包依赖的许可正文。
- 解析器可读取合成 IPA 的元数据并校验 SHA-256，拒绝包含越界路径的压缩包；Android 和 Java 工具可启动。

这些检查未覆盖数据库迁移、服务间协作、真实 APK 签名与 IPA 安装资格，也不代表镜像中系统软件和原生库的许可义务已全部完成。依赖数量仅对应本次构建。

## 部署结构

Compose 包含 PostgreSQL、Redis、一次性迁移、API、Worker、Scheduler、Parser 和 Web。仅 Web 发布宿主机 `5888` 端口；HTTPS 由部署者的外部反向代理终止，代理须保留原始 Host。

数据库、Redis 和 API 不发布宿主机端口。Parser 无网络，只有解析 inbox / outbox 卷，限制 1 CPU、2 GiB 内存和 64 个进程。不要给解析器挂载凭据、Docker socket 或完整状态卷。

准备 Docker Engine 与 Compose、自有域名、HTTPS 反代及足够磁盘空间。服务器需能访问镜像源、GitHub、飞书，以及启用的云存储服务。当前模板自带数据库和 Redis；接外部服务需要调整 Compose 环境和依赖，不能只修改本地默认主机变量。

## 生产配置

由部署者在仓库根目录创建本地 `.env`，不提交版本控制：

| 变量 | 要求 |
| --- | --- |
| `FUMA_DOMAIN` | 裸域名，例如 `fuma.example.com` |
| `FUMA_BIND` | 默认 `0.0.0.0`；同机原生反代建议 `127.0.0.1` |
| `FUMA_DATABASE_NAME` / `FUMA_DATABASE_USER` | 默认均为 `fuma`；已有数据库卷不得随意改名 |
| `FUMA_DATABASE_PASSWORD` | 必填，PostgreSQL 原始密码 |
| `FUMA_REDIS_PASSWORD` | 必填，Redis 原始密码 |
| `FUMA_REDIS_DB` | 默认 `0` |
| `FUMA_SESSION_TTL_SECONDS` | 默认 `28800` |
| `FUMA_IMAGE_TAG` | 默认 `local`；可设置版本号用于追踪本机构建镜像 |

Compose 固定站点为 `https://${FUMA_DOMAIN}`，启用 Secure Cookie；数据库和 Redis 分别使用容器服务名。密码由应用构造连接地址时编码，不要预先 URL 编码。含 `#`、`$` 或空格的 dotenv 值用单引号包住。

GitHub、飞书和云存储凭据通过管理页面设置，不进入前端构建。新实例自动生成根密钥，不设置 `FUMA_ENCRYPTION_KEY`。升级旧实例时，该变量仅用于导入原有密钥；不能生成新值替代旧密钥。

## 首次启动

在根目录执行，配置检查使用 `--quiet`，避免输出展开后的凭据：

```sh
docker compose --env-file .env -f deploy/compose.yml config --quiet
docker compose --env-file .env -f deploy/compose.yml up -d --build
docker compose --env-file .env -f deploy/compose.yml ps
```

迁移须成功后 API 才启动，API 就绪后再启动 Worker / Scheduler。`migrate` 退出码为 0 是正常结果；迁移失败不得绕过依赖门禁。当前镜像在本机构建，仓库尚未提供发布镜像流水线。

首次初始化时，通过受控终端查看 API 日志获取一次性的 admin 密码，访问 HTTPS 站点登录并改密。不要将日志截图或密码复制进工单。密码丢失时使用交互式重置：

```sh
docker compose --env-file .env -f deploy/compose.yml exec api python -m app.cli.reset_admin
```

更改数据库密码变量不会修改已有 PostgreSQL 卷内的账号密码；须先在数据库侧完成密码变更，再同步配置。已有状态卷也不会因重新创建容器而初始化新管理员。

## 反向代理与上传

同宿主机上的原生 Nginx 可在已配置证书的 HTTPS `server` 块中使用：

```nginx
location / {
    client_max_body_size 20m;
    proxy_read_timeout 180s;
    proxy_send_timeout 180s;
    proxy_request_buffering off;
    proxy_pass http://127.0.0.1:5888;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

容器内或其他机器上的反代需使用可达的宿主机地址，不能把指向自身的 `127.0.0.1` 当作 Fuma。防火墙仅允许反代来源访问 5888。Host 必须与配置域名一致；生产 Cookie 需要浏览器实际访问 HTTPS。

上传分片最大 16 MiB，外层代理须留出请求开销。单包上限为 4 GiB，同时还有上传预约配额和磁盘余量检查。出现 413 先检查整个代理链；解析超过五分钟无结果时检查 parser、目录权限和挂载。

默认 Caddy / Uvicorn 关闭可能暴露下载凭据的请求日志；外部反代也应关闭此类日志或脱敏 URI 与 OAuth 查询参数。生产 Caddy 屏蔽 `/api/docs`、`/api/openapi.json`。

**已知限制：** 当前 Uvicorn 禁用代理头解析，而登录按连接来源 IP 限流。默认拓扑下，来自同一 Caddy 的用户共享登录额度。部署验收应覆盖该场景；不能通过无条件信任任意转发头修复。此问题的代码调整列在[路线图](roadmap.md)。

## 持久卷与备份

| 数据 | 备份要求 |
| --- | --- |
| PostgreSQL | 账号、配置、任务、包与发布记录；使用逻辑备份或一致快照 |
| `instance_state` | 根密钥、正式包和上传暂存；必须与数据库备份对应，不能当缓存清空 |
| `package_cache` | GitHub 缓存；源被删除后可能是唯一文件副本 |
| `parser_inbox` / `parser_outbox` | 升级或恢复时保留同一时间点的解析交换状态 |
| Redis | 持久化队列；关键任务事实仍在数据库中 |
| Caddy 卷及外部反代配置 | 保留部署配置；公网证书由外部反代单独备份 |
| COS / OSS 对象 | 按云端备份策略保护，数据库备份不包含云文件 |

一致性备份先停止业务写入，保留数据库服务：

```sh
docker compose --env-file .env -f deploy/compose.yml stop web api worker scheduler parser
mkdir -p /srv/fuma-backups
chmod 700 /srv/fuma-backups
umask 077
docker compose --env-file .env -f deploy/compose.yml exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > /srv/fuma-backups/fuma.dump
```

随后对对应卷做受控备份或快照，再启动业务服务。备份应加密、限制访问，并包含恢复所需的部署配置。密钥文件丢失或与数据库指纹不匹配会阻止启动，不能靠重启生成替代值。

## 升级、恢复与回退

1. 记录代码版本和镜像标识，停止业务写入，完成数据库、密钥、正式文件与解析卷的一致备份。
2. 切换目标版本并构建镜像；先运行 `docker compose --env-file .env -f deploy/compose.yml run --rm migrate`。
3. 迁移成功后执行 `up -d`，检查服务就绪、任务恢复、解密、上传和下载。
4. 回退时恢复与旧版本对应的数据库及卷；没有确认逆向迁移兼容性时，不直接对业务库 downgrade，也不只降级镜像。

恢复演练在隔离环境进行，先隔离外部通知，避免重放生产消息。数据库回退不会删除已生成的云对象；公开副本的收回需要单独核实。普通 `down` 保留命名卷，`down -v` 会删除数据，不用于升级或排障。

## 部署验收

- 首次登录强制改密，重启不重建管理员；域名、HTTPS 和 Cookie 正常。
- 上传测试包经独立 parser 入库；版本发布、私有授权、公开收回、HEAD / Range 正常。
- 飞书同租户与不同租户分别验证允许和拒绝；管理权限不能绕过下载资格。
- GitHub 私有附件读取、Actions 回调、真实群投递及云对象访问按启用功能验收。
- 重启 Worker / Scheduler 后任务可恢复，未知通知不会自动重复发送。
- 在隔离实例实际恢复数据库与状态卷，验证凭据解密及包文件可用；真机下载不等同于安装成功。
