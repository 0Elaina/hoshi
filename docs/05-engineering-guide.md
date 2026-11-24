# Hoshi 本地工程指南

## 启动管理端

在 `frontend/` 使用 Node.js 26 LTS 和 pnpm `12.15.0`。使用 `pnpm install --frozen-lockfile` 安装 workspace 依赖。执行 `pnpm run dev` 启动管理端，访问 `http://127.0.0.1:5173/`。该端口被占用时，Vite 会报告启动失败。 [pnpm 安装依赖](https://pnpm.io/cli/install) · [Vite 开发服务配置](https://vite.dev/config/server-options)

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

使用 Python 3.12 和 uv，在 `backend/` 执行后端命令。首次启动时复制 `.env.example` 为 `.env`，按共享 PostgreSQL 和 Redis 实例的配置填写连接信息。Pydantic Settings 优先读取进程环境，其次读取当前工作目录的 `.env`。 [Pydantic Settings](https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/) · [uv 锁定与同步](https://docs.astral.sh/uv/concepts/projects/sync/)

| 环境变量 | 未配置时 | 用途 |
| --- | --- | --- |
| `HOSHI_APP_ENV` | `production` | 设为 `development` 时开放 OpenAPI 和 Swagger UI |
| `HOSHI_LOG_LEVEL` | `INFO` | 应用与 Uvicorn 日志级别（`DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`） |
| `HOSHI_LOG_FILE` | `logs/hoshi.log` | 按天滚动日志文件路径（相对于工作目录） |
| `HOSHI_DB_HOST` | `127.0.0.1` | 共享 PostgreSQL 的宿主机地址 |
| `HOSHI_DB_PORT` | `5432` | 共享 PostgreSQL 的宿主机端口 |
| `HOSHI_DB_NAME` | `hoshi` | Hoshi 数据库名 |
| `HOSHI_DB_USER` | 必填 | 共享 PostgreSQL 用户 |
| `HOSHI_DB_PASSWORD` | 必填 | 共享 PostgreSQL 密码 |
| `HOSHI_ADMIN_ORIGIN` | `http://127.0.0.1:5173` | 管理端浏览器 Origin，生产环境须配置为实际 HTTPS Origin |
| `HOSHI_REDIS_HOST` | `127.0.0.1` | 共享 Redis 的宿主机地址 |
| `HOSHI_REDIS_PORT` | `6379` | 共享 Redis 的宿主机端口 |
| `HOSHI_REDIS_PASSWORD` | 空 | 本机共享实例使用 `REDIS_PASSWORD` |
| `HOSHI_JWT_SECRET` | 必填 | 标准 Base64 编码的 HS256 密钥，解码后不少于 32 字节 |
| `HOSHI_JWT_ISSUER` | `hoshi` | 签发与验签使用的 JWT `iss` 声明 |
| `HOSHI_JWT_ACCESS_TTL` | `300` | 访问令牌有效期（单位：秒） |
| `HOSHI_JWT_ADMIN_REFRESH_TTL` | `86400` | 管理端刷新令牌与会话有效期（单位：秒） |
| `HOSHI_JWT_USER_REFRESH_TTL` | `2592000` | 用户端刷新令牌与会话有效期（单位：秒） |

首次填写 `.env` 时，可用以下命令生成符合长度要求的 `HOSHI_JWT_SECRET`：

```bash
openssl rand -base64 32
```

启动后端前先确认共享 PostgreSQL 与 Redis 已运行，并在 `backend/` 应用数据库迁移：

```bash
uv python install
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked uvicorn hoshi.main:create_app --factory --host 127.0.0.1 --port 8080 --reload
```

同时启动管理端开发服务后，可通过 Vite 同源代理（`http://127.0.0.1:5173/api/v1/admin/auth/login`、`/refresh`、`/logout`）联调管理端登录、续签与登出；用 `curl` 直接调试时需显式携带 `Origin: http://127.0.0.1:5173` 请求头，并配合 `-c` / `-b` 传递 `hoshi_admin_refresh` Cookie。

调试受保护的管理端接口（如 `GET /api/v1/admin/accounts/me`）时，在请求头携带登录或刷新获得的访问令牌：`Authorization: Bearer <accessToken>`。后续新增管理端业务路由须统一挂载到 `hoshi.api.v1.admin` 中的 `protected_admin_api`，以自动继承 Bearer 访问令牌校验与 `AccountType.ADMIN` 入口检查；需要读取身份载荷时注入 `AdminAccountDependency`。

管理端接入 `/refresh` 时，客户端须对同一 Cookie 下的并发刷新请求做合并/排队（Single-Flight）：后端每次刷新都会轮换 `refresh_jti`，旧刷新令牌被重放会触发整条会话撤销；若刷新响应在客户端保存前丢失，后续续签也会失败并要求重新登录。

开发环境的 Swagger UI 位于 `/api/docs`，OpenAPI JSON 位于 `/api/openapi.json`。管理端开发服务启动后，也可经 `http://127.0.0.1:5173/api/docs` 打开 Swagger UI。访问未注册的路径可检查 `404 / ROUTE_NOT_FOUND` 响应。以 `HOSHI_APP_ENV=production` 重启时，两个文档路径均返回 `404`。 [FastAPI OpenAPI URL](https://fastapi.tiangolo.com/tutorial/metadata/#openapi-url) · [Uvicorn 配置](https://www.uvicorn.org/settings/)

| 命令 | 用途 |
| --- | --- |
| `uv lock` | 按 `pyproject.toml` 更新依赖锁文件 |
| `uv run --locked ruff check` | 执行后端静态检查 |
| `uv run --locked ruff format --check` | 检查后端代码格式 |

### AI 与向量服务配置约定

后续接入 LangChain、LangGraph 与 Qdrant 模块时，新增环境变量继续沿用 `HOSHI_` 前缀并在 `backend/src/hoshi/core/config.py` 中声明。Qdrant 优先连接本机共享实例（见下文 [共享容器](#共享容器)），OpenAI 兼容模型与 Embedding 服务通过环境变量配置基址、密钥与默认模型名称，不将模型密钥写入仓库。

### OpenAPI 契约

使用 FastAPI 路由和 Pydantic 请求、响应模型生成 OpenAPI。字段类型、必填性和长度由契约本身表达。字段单位、业务含义和特殊示例可在模型字段或路由上补充。 [FastAPI 响应模型](https://fastapi.tiangolo.com/tutorial/response-model/)

## 共享容器

本机各项目的共享容器由 `/home/nep/01-Own/infra` 统一配置。Hoshi 复用该目录中已有的 `postgres`、`redis`、`qdrant`、`rustfs` 及按需接入的 `rabbitmq` 服务。 [共享 Compose 配置](../../../../infra/compose.yaml)

下表列出 Compose 的默认宿主机连接地址。实际连接时，先查看 `/home/nep/01-Own/infra/.env` 中的 `BIND_IP` 和对应端口变量。如果启动 Compose 时通过 Shell 环境或 `--env-file` 覆盖了配置，以该次启动解析出的端口映射为准。 [Docker Compose 变量插值规则](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)

| 服务 | 默认宿主机地址 | 端口变量 | 凭据来源 |
| --- | --- | --- | --- |
| PostgreSQL 16 | `127.0.0.1:5432` | `POSTGRES_PORT` | 共享 `.env` 的 `POSTGRES_USER` 和 `POSTGRES_PASSWORD` |
| Redis 7 | `127.0.0.1:6379` | `REDIS_PORT` | 共享 `.env` 的 `REDIS_PASSWORD` |
| Qdrant HTTP API | `http://127.0.0.1:6333` | `QDRANT_PORT` | 本地共享实例未启用 API Key |
| Qdrant gRPC | `127.0.0.1:6334` | `QDRANT_GRPC_PORT` | 本地共享实例未启用 API Key |
| RustFS S3 API | `http://127.0.0.1:9000` | `RUSTFS_PORT` | 共享 `.env` 的 `RUSTFS_ACCESS_KEY` 和 `RUSTFS_SECRET_KEY` |
| RustFS 控制台 | `http://127.0.0.1:9001` | `RUSTFS_CONSOLE_PORT` | 同一组 RustFS 凭据 |
| RabbitMQ AMQP | `127.0.0.1:5672` | `RABBITMQ_PORT` | 共享 `.env` 的 `RABBITMQ_DEFAULT_USER` 和 `RABBITMQ_DEFAULT_PASS` |
| RabbitMQ 管理台 | `http://127.0.0.1:15672` | `RABBITMQ_MGMT_PORT` | 同一组 RabbitMQ 凭据 |

本机连接凭据保留在本地环境配置中。RustFS 的 S3 API 地址用于应用接入，控制台地址用于人工管理。Qdrant 接入时通过集合命名前缀及 `user_id`、`character_id` Payload 字段完成逻辑隔离。 [RustFS S3 接口](https://docs.rustfs.com/en/administration/protocols/s3) · [Qdrant 文档](https://qdrant.tech/documentation/)

Hoshi 使用共享 Redis 的 DB 0，业务键以 `hoshi:` 开头。FastAPI 为每个应用进程管理一个异步 Redis 客户端，连接在首次执行 Redis 命令时建立。HTTP 路由通过 `get_redis` 依赖取得客户端。 [redis-py 异步客户端](https://redis.io/docs/latest/develop/clients/redis-py/async/) · [Redis SELECT](https://redis.io/docs/latest/commands/select/)

## Hoshi 数据库

搭建环境时，维护者先使用有建库权限的现有 PostgreSQL 角色连接共享实例，检查 `hoshi` 是否已存在。缺失时只创建 `hoshi` 这一个数据库，所有者使用现有的 `POSTGRES_USER` 对应角色。后端连接配置中的数据库名填写 `hoshi`，登录凭据沿用共享实例的现有账号。 [PostgreSQL 16 建库文档](https://www.postgresql.org/docs/16/sql-createdatabase.html)

管理员账号属于 Hoshi 应用，由维护者通过命令行哈希脚本与数据库写入开通：

### 手工开通管理员账号

1. 在 `backend/` 运行密码哈希脚本，按提示输入一次原始密码，复制标准输出的整行 Argon2 哈希：

```bash
uv run --locked python scripts/hash_password.py
```

2. 连接 `hoshi` 数据库执行 `INSERT` 开通账号。`username` 使用 3–32 位小写 ASCII 字母、数字或下划线，`nickname` 去首尾空白后为 1–32 个字符，`account_type` 与 `role` 均填 `admin`，`status` 填 `active`，省略 `id`、`created_at` 与 `updated_at` 由数据库生成：

```sql
INSERT INTO user_accounts (
    username,
    nickname,
    password_hash,
    account_type,
    role,
    status
)
VALUES (
    '<username>',
    '<nickname>',
    '<脚本输出的完整 Argon2 哈希>',
    'admin',
    'admin',
    'active'
)
RETURNING id, username, account_type, role, status, created_at, updated_at;
```

接入 Alembic 前，用 PostgreSQL 客户端只读核对 `hoshi` 的表清单。本项目使用默认的 `public` schema，在 `psql` 中可用 `\dt public.*` 查看业务表及 `flyway_schema_history`。发现已有表或旧迁移历史时，先核对实际表结构和历史，再确定接入方式。 [psql 命令](https://www.postgresql.org/docs/16/app-psql.html)

Alembic 使用应用的数据库配置和 `Base.metadata`。新增 ORM 模型时，在迁移环境导入模型，再生成和 Review 修订。`uv run --locked alembic current` 用于验证连接并查看当前版本。部署时在启动应用之前执行 `uv run --locked alembic upgrade head` 应用已存在的修订。 [Alembic 自动生成迁移](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)

应用为访问数据库的 HTTP 请求提供独立的 `AsyncSession`。业务用例用 `async with session.begin():` 包住数据库读写，块内的仓储调用共用会话。正常离开该块时提交，有异常离开时回滚。用 `uv run --locked python -m asyncio` 打开异步控制台，可通过应用的引擎和会话工厂验证连接。输入带缩进的语句后，用一个空行执行该块，预期输出 `1`。 [SQLAlchemy 异步会话](https://docs.sqlalchemy.org/en/21/orm/extensions/asyncio.html)

```python
from sqlalchemy import text
from hoshi.core.config import Settings
from hoshi.db.session import create_db_engine, create_session_factory

engine = create_db_engine(Settings().database_url())
sessions = create_session_factory(engine)
async with sessions() as session, session.begin():
    print(await session.scalar(text("SELECT 1")))

await engine.dispose()
```

## Git 与持续集成

- `main` 是默认分支。日常改动从最新的 `main` 创建短分支，分支名采用 `<type>/<英文短名>`，如 `ci/repository-checks`。推送后创建以 `main` 为目标的 PR。 [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow)
- 提交标题和 PR 标题采用 `<type>: <简短中文动作>`，例如 `ci: 配置持续集成`、`fix: 修正分页校验`。通过 merge commit 合并并保留分支提交，合并提交标题采用 PR 标题。合并后清理已合并的短分支。 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/) · [GitHub 合并提交设置](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/configuring-commit-merging-for-pull-requests)
- `main` 通过 PR 更新。分支须与 `main` 同步，前后端 CI 均通过后由维护者合并。CI 在推送 `main` 或提交以 `main` 为目标的 PR 时运行。后端执行 `uv sync --locked` 和上文的两项 Ruff 检查。前端执行 `pnpm install --frozen-lockfile`、`pnpm run check` 和 `pnpm run build`。 [CI 工作流](../.github/workflows/ci.yml)
