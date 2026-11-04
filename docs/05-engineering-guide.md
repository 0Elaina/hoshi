# Hoshi 工程指南

## 工程与环境

后端工程位于 `backend/`，使用 Java 21 和项目自带的 Maven Wrapper。父工程聚合 `hoshi-common`、`hoshi-user`、`hoshi-auth` 和 `hoshi-app`，启动类为 `com.nep.HoshiApplication`。通用基础代码与框架配置归 common；app 保留启动与模块装配、配置文件及 Flyway。

管理端工程位于 `frontend/admin/`，使用 pnpm 独立管理依赖，版本由 `package.json` 的 `packageManager` 固定为 `12.15.0`。Node.js 版本应满足同一文件中的 `engines.node`，CI 使用 Node.js 24；依赖版本以各工程的构建配置和锁文件为准。

运行、安装、构建和检查命令由开发者执行。

Lombok 由父 POM 统一声明 provided 并配置注解处理器，各 Java 模块继承，版本由 Boot 管理。Validation、SLF4J、Logback 和 HikariCP 沿用 common 中现有 starter 的传递依赖。

## 后端启动

本机共享容器在 `/home/nep/01-Own/infra`，应用复用已有 PostgreSQL 服务及账号。先在现有服务中检查 Hoshi 数据库：

```bash
docker compose --project-directory /home/nep/01-Own/infra exec postgres psql -U postgres -d postgres -c "SELECT datname FROM pg_database WHERE datname = 'hoshi';"
```

如果没有查询结果，用同一账号创建数据库；已存在则跳过：

```bash
docker compose --project-directory /home/nep/01-Own/infra exec postgres psql -U postgres -d postgres -c 'CREATE DATABASE hoshi;'
```

数据库准备好后，从仓库根目录进入后端工程，检查 Wrapper 使用的运行环境，再构建应用：

```bash
cd backend
./mvnw -version
./mvnw clean package
```

Java 版本应为 21。构建成功后，进入 app 目录，显式启用 dev：

```bash
cd hoshi-app
java -jar target/hoshi-app-0.0.1-SNAPSHOT.jar --spring.profiles.active=dev
```

后端使用 Boot 默认端口 `8080`，启动时连接数据源并运行 Flyway。没有业务迁移时，Flyway 会建立 history 表，无迁移提示可以正常出现。没有 Mapper 时也可能出现扫描提示；Mapper 随实际业务增加。

在另一个终端确认未定义路径的统一错误响应：

```bash
curl -i http://localhost:8080/
```

预期 HTTP 404，JSON 中 code 为 NOT_FOUND、data 为 null，具体结构见[API 通用约定](04-api-design/00-conventions.md)。

IDE 直接运行时，主类使用 `com.nep.HoshiApplication`，工作目录为 `backend/hoshi-app`，程序参数为 `--spring.profiles.active=dev`。修改 Maven 模块或依赖后，重新加载 Maven 工程。若需要生成模块编译输出，可在后端工程目录执行：

```bash
./mvnw -pl hoshi-app -am compile
```

## 管理端启动与构建

从仓库根目录进入管理端，按锁文件安装依赖，再启动开发服务：

```bash
cd frontend/admin
pnpm install --frozen-lockfile
pnpm dev
```

Vite 默认开发端口为 `5173`，端口被占用时可能选择其他端口，以终端输出的地址为准。根路径渲染空白内容，Router 和 Pinia 在应用入口注册，Tailwind 通过 Vite 插件和全局样式入口接入。

在管理端目录执行构建：

```bash
pnpm build
```

该命令同时执行类型检查与生产构建，产物位于管理端的 `dist/`。需要查看构建产物时执行 `pnpm preview`。

## 管理端代码检查

在管理端目录执行静态检查与格式检查：

```bash
pnpm lint
pnpm format:check
```

`lint` 依次运行 Oxlint 和 ESLint，一项失败仍继续检查另一项，不自动改写源码。需要自动修复或格式化时，分别执行 `pnpm lint:fix` 和 `pnpm format`。

构建已包含类型检查；单独检查类型时使用 `pnpm type-check`。

提交前在管理端目录执行 `pnpm install --frozen-lockfile`，然后执行 `pnpm ci:check`。后者按顺序运行 lint、格式检查、类型检查和生产打包，一项失败仍继续执行后续检查，任意一项失败都会使整个命令失败。CI 使用同一入口，类型检查与打包各执行一次。

修改 `packageManager` 或依赖清单后，先通过本地安装同步锁文件，再确认冻结安装与整套检查通过，一并提交相关清单和锁文件。

## 配置来源

| 位置 | 内容与加载方式 |
| --- | --- |
| `backend/hoshi-app/src/main/resources/application.yml` | 随应用打包的公共配置，包含应用名、Flyway、Mapper XML 扫描、MyBatis 日志实现与滚动日志策略 |
| `backend/hoshi-app/config/application-dev.yml` | 本地数据源 URL、已有用户名与密码、业务 Mapper 的 SQL 调试日志级别；以 app 为工作目录并启用 dev 时，由 Boot 默认的外部 config 搜索规则加载 |
| `/home/nep/01-Own/infra/compose.yaml`、同目录 `.env` | 本机共享容器声明及开发凭据来源；应用不会自行加载 infra 的 .env |
| `frontend/admin/vite.config.ts` | 管理端构建与开发服务配置；路由基础路径读取 Vite 的 `import.meta.env.BASE_URL` |

本地开发 YAML 已加入后端 Git 忽略，凭据不放入公共配置或文档。共享环境凭据变化时，同步本地开发 YAML。其他环境通过各自配置或环境变量提供数据源，不在公共 YAML 中默认激活 dev。

认证、其他中间件和前后端 API 代理在对应功能接入时配置，其配置位置与环境变量来源随实际实现补充。

## 后端日志

日志使用 SLF4J 与 Boot 默认 Logback，同时输出到控制台和应用日志文件。公共级别为 INFO，开发 SQL 日志仅对本地开发配置中的业务 Mapper 包启用 DEBUG，不使用 MyBatis 的标准输出日志实现。

默认日志文件为 `./logs/hoshi.log`，相对于应用启动工作目录；以 app 为工作目录时位于 `backend/hoshi-app/logs/`。环境变量 `LOG_FILE` 可以覆盖完整日志文件路径，目标目录需要可写。

归档模式为当前日志文件路径后接日期、分片序号和 `.gz`。按天及单文件 50MB 滚动，保留 30 个日周期，归档总量上限为 1GB；启动时清理过期归档。保留周期和总量限制同时生效，实际保留时间可能小于 30 天；总量限制针对归档，当前活动文件另计。

日志目录、活动日志和滚动归档已加入 Git 忽略。自定义输出路径时同样使用日志目录和 `.log` 文件扩展名。构建不会启动应用，也不会因此生成运行日志。

参考依据：[Boot 日志与滚动策略](https://docs.spring.io/spring-boot/reference/features/logging.html#features.logging.file-rotation)、[MyBatis-Plus XML 扫描](https://baomidou.com/reference/#mapperlocations)、[Lombok Maven 接入](https://projectlombok.org/setup/maven)。

接入依据：[Tailwind 官方 Vite 集成](https://tailwindcss.com/docs/installation/using-vite)、[Prettier CLI](https://prettier.io/docs/cli)、[ESLint CLI](https://eslint.org/docs/latest/use/command-line-interface)。

## Git 协作规则

项目使用公开 GitHub 仓库。`main` 保持可合并的稳定状态，每项完整改动在短期任务分支完成，通过 PR 合入 main；仓库初始化时的首个基线提交直接建立在 main。

分支采用英文类型加简短英文说明，例如 `feat/auth-login`、`fix/page-validation`、`docs/git-rules`、`ci/github-actions`。一个分支围绕一个明确目标组织改动。

普通开发提交遵循 Conventional Commits，使用英文类型、可选英文范围及中文说明，例如 `feat(auth): 添加登录校验`。常用类型为 `feat`、`fix`、`docs`、`refactor`、`perf`、`style`、`test`、`build`、`ci`、`chore`；每次提交表达一项完整、可说明的改动。Git 自动生成的 merge commit 保留默认格式。

PR 说明改动目的、最终行为与实际验证结果，CI 通过后使用普通 merge commit 合并，保留分支内提交历史。合并后同步本地 main，并清理已合并的任务分支。CI 失败时修复原因并重新检查，再合并。

Git 写操作由开发者执行。Agent 主动检查可见 Git 状态，适时提醒分支、提交、推送、PR、CI、合并和同步清理，给出必要命令；同一状态未变化时不重复催促。文档只记录长期操作规则，分支现状和待办从仓库与当前任务中获取。

提交源码、文档、依赖锁文件、Maven Wrapper 脚本及配置、迁移脚本。构建产物和缓存沿用各工程的忽略规则；本地开发 YAML、环境变量文件和个人凭据不提交，需要共享的环境示例只包含字段与示例值。

后端和各前端工程分别维护本工程的 `.gitignore`，根目录仅维护根目录特有规则。根目录的 Agent 指令、上下文及本地工具目录保留在本机并忽略提交；`docs/` 中的项目文档正常提交。忽略规则不影响已被 Git 跟踪的文件，首次提交前通过暂存清单确认实际提交范围。

## CI 规则

工作流位于 `.github/workflows/ci.yml`。面向 main 的 PR、main 推送和手动触发均运行检查；两个任务独立并行执行，检查名称保持稳定，供 main 分支保护引用。

| 检查名称 | 工作目录 | 环境 | 执行内容 |
| --- | --- | --- | --- |
| Backend | `backend/` | Java 21、Maven Wrapper | `sh ./mvnw --batch-mode --no-transfer-progress verify` |
| Admin | `frontend/admin/` | Node.js 24、清单声明的 pnpm 版本 | 锁文件安装，然后运行 `pnpm ci:check`，完整执行 lint、格式、类型检查及打包 |

CI 使用 GitHub 托管的 Ubuntu 24.04 runner、维护中的官方 Actions 和只读仓库权限，缓存 Maven 依赖与 pnpm store。每个任务超时为 15 分钟，同一 PR 或分支的新运行取消尚未结束的旧运行。

CI 只检查和构建代码，沿用工程维护的检查命令；不启动应用，不接入数据库，也不读取本地开发凭据。管理端 build 已包含类型检查。项目明确增加测试或检查入口时，同步纳入对应构建流程；工具版本或依赖变更时，同步维护清单、锁文件与 CI 配置。

首次推送后在 Actions 中确认两个任务的实际结果；本地命令执行成功不能代替远端 CI 结果。

## GitHub main 分支设置

在公开仓库为 main 设置分支保护：要求通过 PR 合并，并要求 `Backend`、`Admin` 两项状态检查通过；检查名称以首次运行在 GitHub 展示的结果为准。将规则应用于管理员操作，保持强推和分支删除关闭。

个人维护不设置必须由他人审批。仓库保留 merge commit 合并方式，关闭 squash 和 rebase 合并方式；不要求线性历史，以保留普通 merge commit。仓库设置由开发者操作，修改规则时同步维护本指南。

参考依据：[GitHub flow](https://docs.github.com/en/get-started/using-github/github-flow)、[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)、[GitHub Maven CI](https://docs.github.com/en/actions/tutorials/build-and-test-code/java-with-maven)、[GitHub 分支保护](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)。
