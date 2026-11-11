# Hoshi 本地工程指南

## 启动管理端

在 `frontend/` 使用 Node.js 26 LTS 和 pnpm `12.15.0`。锁文件生成后，使用 `pnpm install --frozen-lockfile` 安装 workspace 依赖。执行 `pnpm run dev` 启动管理端，访问 `http://127.0.0.1:5173/`。该端口被占用时，Vite 会报告启动失败。 [pnpm 安装依赖](https://pnpm.io/cli/install) · [Vite 开发服务配置](https://vite.dev/config/server-options)

管理端从同源 `/api` 发起请求。Vite 开发服务将原路径转发给 `http://127.0.0.1:8080`。后端地址变化时，可在启动 Vite 的进程环境或 `frontend/apps/admin/.env.local` 中设置 `HOSHI_API_PROXY_TARGET`。部署环境由站点代理转发 `/api`。 [Vite 开发代理](https://vite.dev/config/server-options#server-proxy)

| 命令 | 用途 |
| --- | --- |
| `pnpm run dev` | 启动管理端开发服务 |
| `pnpm run build` | 对 workspace 应用执行类型检查并构建 |
| `pnpm run typecheck` | 检查 workspace 应用和共享包的 TypeScript 类型 |
| `pnpm run lint` | 运行 workspace ESLint 检查 |
| `pnpm run lint:fix` | 修复 ESLint 可以自动修复的问题 |
| `pnpm run format` | 使用 Prettier 格式化 workspace 文件 |
| `pnpm run format:check` | 检查 workspace 文件格式 |
| `pnpm run check` | 依次执行格式检查、Lint 和类型检查 |

## 启动后端

在 `backend/` 下使用 Go 1.27 执行 `go run ./cmd/server`。应用从进程环境读取以下配置。PostgreSQL 和 Redis 的连接参数取自共享基础设施的实际配置。凭据只保存在本地环境中。

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `HOSHI_HTTP_ADDR` | `127.0.0.1:8080` | Gin 的监听地址 |
| `HOSHI_POSTGRES_DSN` | 必填 | 指向共享 PostgreSQL 的 `hoshi` 库，沿用现有账号 |
| `HOSHI_REDIS_ADDR` | `127.0.0.1:6379` | 共享 Redis 的宿主机地址，端口以 Compose 的实际映射为准 |
| `HOSHI_REDIS_PASSWORD` | 必填 | 共享实例的 `REDIS_PASSWORD` |

本机 PostgreSQL DSN 可使用 `host=127.0.0.1 port=5432 dbname=hoshi user=现有角色 password=现有密码 sslmode=disable` 的形式，按共享实例的实际配置替换地址、端口和凭据。Redis 使用共享实例的默认逻辑库 `0`，客户端在首次执行 Redis 命令时建立连接。 [GORM PostgreSQL 连接指南](https://gorm.io/docs/connecting_to_the_database.html) · [go-redis 连接指南](https://redis.io/docs/latest/develop/clients/go/)

## 共享容器

本机各项目的共享容器由 `/home/nep/01-Own/infra` 统一配置。Hoshi 复用该目录中已有的 `postgres`、`redis` 和 `rustfs` 服务。 [共享 Compose 配置](../../../../infra/compose.yaml)

下表列出 Compose 的默认宿主机连接地址。实际连接时，先查看 `/home/nep/01-Own/infra/.env` 中的 `BIND_IP` 和对应端口变量。如果启动 Compose 时通过 Shell 环境或 `--env-file` 覆盖了配置，以该次启动解析出的端口映射为准。 [Docker Compose 变量插值规则](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)

| 服务 | 默认宿主机地址 | 端口变量 | 凭据来源 |
| --- | --- | --- | --- |
| PostgreSQL 16 | `127.0.0.1:5432` | `POSTGRES_PORT` | 共享 `.env` 的 `POSTGRES_USER` 和 `POSTGRES_PASSWORD` |
| Redis 7 | `127.0.0.1:6379` | `REDIS_PORT` | 共享 `.env` 的 `REDIS_PASSWORD` |
| RustFS S3 API | `http://127.0.0.1:9000` | `RUSTFS_PORT` | 共享 `.env` 的 `RUSTFS_ACCESS_KEY` 和 `RUSTFS_SECRET_KEY` |
| RustFS 控制台 | `http://127.0.0.1:9001` | `RUSTFS_CONSOLE_PORT` | 同一组 RustFS 凭据 |

本机连接凭据保留在本地环境配置中。Hoshi 的 S3 客户端使用 RustFS 的 S3 API 地址，控制台地址用于人工管理。 [RustFS S3 接口](https://docs.rustfs.com/en/administration/protocols/s3)

## Hoshi 数据库

搭建环境时，维护者先使用有建库权限的现有 PostgreSQL 角色连接共享实例，检查 `hoshi` 是否已存在。缺失时只创建 `hoshi` 这一个数据库，所有者使用现有的 `POSTGRES_USER` 对应角色。后端连接配置中的数据库名填写 `hoshi`，登录凭据沿用共享实例的现有账号。 [PostgreSQL 16 建库文档](https://www.postgresql.org/docs/16/sql-createdatabase.html)

管理员账号属于 Hoshi 应用。维护者通过数据库操作开通该身份，具体操作随认证模块确定。

创建数据库后，应用表结构由 `backend/migrations/` 中的版本化 SQL 迁移管理，使用 Goose 执行。 [Goose 文档](https://pressly.github.io/goose/)

## Git 与持续集成

- `main` 是默认分支。日常改动从最新的 `main` 创建短分支，分支名采用 `<type>/<英文短名>`，如 `ci/repository-checks`。推送后创建以 `main` 为目标的 PR。 [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow)
- 提交标题和 PR 标题采用 `<type>: <简短中文动作>`，例如 `ci: 配置持续集成`、`fix: 修正分页校验`。通过 merge commit 合并并保留分支提交，合并提交标题采用 PR 标题。合并后清理已合并的短分支。 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/) · [GitHub 合并提交设置](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/configuring-commit-merging-for-pull-requests)
- `main` 通过 PR 更新。分支须与 `main` 同步，前后端 CI 均通过后由维护者合并。检查的触发条件和命令见 [CI 工作流](../.github/workflows/ci.yml)。
