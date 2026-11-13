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

使用 Java 21。开发环境连接配置放在 `backend/hoshi-app/config/application-dev.yml`，该文件由 Git 忽略。PostgreSQL 的用户名、密码和端口取自共享基础设施，数据库名为 `hoshi`。Redis 的端口和密码取自同一共享配置。应用默认激活 `dev`，Wrapper 从 `backend/` 调用，应用以 `hoshi-app/` 为工作目录并自动加载该目录下的 `config/application-dev.yml`。进程环境变量优先于配置文件。 [Spring Boot 外部配置](https://docs.spring.io/spring-boot/reference/features/external-config.html) · [Boot 插件工作目录](https://docs.spring.io/spring-boot/maven-plugin/run.html#goals-run-parameters-details-workingDirectory)

| 环境变量 | 未配置时 | 用途 |
| --- | --- | --- |
| `SPRING_DATASOURCE_URL` | 从本地配置读取 | PostgreSQL JDBC URL，例如 `jdbc:postgresql://127.0.0.1:5432/hoshi` |
| `SPRING_DATASOURCE_USERNAME` | 从本地配置读取 | 共享 PostgreSQL 用户 |
| `SPRING_DATASOURCE_PASSWORD` | 从本地配置读取 | 共享 PostgreSQL 密码 |
| `SPRING_DATA_REDIS_HOST` | 本地配置，其次 `HOSHI_REDIS_HOST` 或 `127.0.0.1` | 共享 Redis 的宿主机地址 |
| `SPRING_DATA_REDIS_PORT` | 本地配置，其次 `HOSHI_REDIS_PORT` 或 `6379` | 共享 Redis 的宿主机端口 |
| `SPRING_DATA_REDIS_PASSWORD` | 本地配置，其次 `HOSHI_REDIS_PASSWORD` | 共享实例的 Redis 密码 |

```bash
./mvnw -pl hoshi-app -am spring-boot:run
```

Maven Wrapper 使用 Maven 3.10.0。上游模块参与构建，`hoshi-app` 启动并默认监听 `127.0.0.1:8080`。用启动日志确认应用与 Flyway 初始化成功。Redis 在首次执行 Redis 命令时连接，默认使用逻辑库 `0`。 [Spring Boot Maven 启动](https://docs.spring.io/spring-boot/maven-plugin/run.html) · [Spring Data Redis 配置](https://docs.spring.io/spring-boot/reference/data/nosql.html#data.nosql.redis)

开发环境可直接打开后端的 `/swagger-ui.html`，OpenAPI JSON 位于 `/v3/api-docs`。当前使用 Spring Security 的临时用户 `user` 和启动日志中生成的密码。部署时通过 `SPRING_PROFILES_ACTIVE` 选择部署环境的 profile，Springdoc 只在 `dev` 下启用。 [Spring Boot 默认安全配置](https://docs.spring.io/spring-boot/reference/web/spring-security.html)

| 命令 | 用途 |
| --- | --- |
| `./mvnw -B -ntp verify` | 构建整个后端并执行 Maven 验证 |
| `java -jar target/hoshi-app-0.0.1-SNAPSHOT.jar` | 从 `backend/hoshi-app/` 运行打包后的应用 |

### OpenAPI 注解

优先由 Springdoc 从 Java 类型、Spring MVC 映射和 Bean Validation 约束推断文档。只有字段单位、业务含义或特殊示例无法推断时，才使用一个文档注解补充。字段类型、必填性和长度等已有信息由代码和校验约束统一表达。 [Springdoc 文档](https://springdoc.org/)

## 共享容器

本机各项目的共享容器由 `/home/nep/01-Own/infra` 统一配置。Hoshi 复用该目录中已有的 `postgres`、`redis` 和 `rustfs` 服务。 [共享 Compose 配置](../../../../infra/compose.yaml)

下表列出 Compose 的默认宿主机连接地址。实际连接时，先查看 `/home/nep/01-Own/infra/.env` 中的 `BIND_IP` 和对应端口变量。如果启动 Compose 时通过 Shell 环境或 `--env-file` 覆盖了配置，以该次启动解析出的端口映射为准。 [Docker Compose 变量插值规则](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)

| 服务 | 默认宿主机地址 | 端口变量 | 凭据来源 |
| --- | --- | --- | --- |
| PostgreSQL 16 | `127.0.0.1:5432` | `POSTGRES_PORT` | 共享 `.env` 的 `POSTGRES_USER` 和 `POSTGRES_PASSWORD` |
| Redis 7 | `127.0.0.1:6379` | `REDIS_PORT` | 共享 `.env` 的 `REDIS_PASSWORD` |
| RustFS S3 API | `http://127.0.0.1:9000` | `RUSTFS_PORT` | 共享 `.env` 的 `RUSTFS_ACCESS_KEY` 和 `RUSTFS_SECRET_KEY` |
| RustFS 控制台 | `http://127.0.0.1:9001` | `RUSTFS_CONSOLE_PORT` | 同一组 RustFS 凭据 |

本机连接凭据保留在本地环境配置中。RustFS 的 S3 API 地址用于应用接入，控制台地址用于人工管理。 [RustFS S3 接口](https://docs.rustfs.com/en/administration/protocols/s3)

## Hoshi 数据库

搭建环境时，维护者先使用有建库权限的现有 PostgreSQL 角色连接共享实例，检查 `hoshi` 是否已存在。缺失时只创建 `hoshi` 这一个数据库，所有者使用现有的 `POSTGRES_USER` 对应角色。后端连接配置中的数据库名填写 `hoshi`，登录凭据沿用共享实例的现有账号。 [PostgreSQL 16 建库文档](https://www.postgresql.org/docs/16/sql-createdatabase.html)

管理员账号属于 Hoshi 应用。维护者通过数据库操作开通该身份，具体操作随认证模块确定。

Flyway 使用应用数据源，在启动时校验并执行 `backend/hoshi-app/src/main/resources/db/migration/` 中的版本化 SQL。脚本使用 `V<版本>__<说明>.sql` 命名。已有旧迁移或业务表的库，先核对 schema 和迁移历史，再确定 Flyway 接入方式。 [Spring Boot 的 Flyway 集成](https://docs.spring.io/spring-boot/how-to/data-initialization.html#howto.data-initialization.migration-tool.flyway)

需要跨多次读写保持原子性的业务操作，在 Spring 应用服务方法上用 `@Transactional` 定义事务边界，所属 Mapper 通过同一个应用数据源参与事务。

## Git 与持续集成

- `main` 是默认分支。日常改动从最新的 `main` 创建短分支，分支名采用 `<type>/<英文短名>`，如 `ci/repository-checks`。推送后创建以 `main` 为目标的 PR。 [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow)
- 提交标题和 PR 标题采用 `<type>: <简短中文动作>`，例如 `ci: 配置持续集成`、`fix: 修正分页校验`。通过 merge commit 合并并保留分支提交，合并提交标题采用 PR 标题。合并后清理已合并的短分支。 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/) · [GitHub 合并提交设置](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/configuring-commit-merging-for-pull-requests)
- `main` 通过 PR 更新。分支须与 `main` 同步，前后端 CI 均通过后由维护者合并。检查的触发条件和命令见 [CI 工作流](../.github/workflows/ci.yml)。
