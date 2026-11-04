# Hoshi 项目概览

## 项目定位

Hoshi 是个人独立开发、个人长期维护、面向真实用户的在线音乐网站，以网易云音乐作为产品参考。平台自主维护曲库，管理端负责维护音乐内容及关联资源，用户端提供音乐浏览与在线播放。

项目价值体现在完整业务流程、可维护的工程结构和实际运行效果，形成能够在简历中说明个人职责、设计取舍与成果的实践经验。技术方案围绕真实业务问题选择，结合接入成本和长期维护成本判断收益。

工程质量以正确性、可读性和可维护性为要求。目录按中大型项目的职责边界组织，架构规模与个人维护能力及已确认需求匹配。先建设管理端的数据维护能力，再围绕可维护的数据开发用户端。功能范围随开发演进，每个开发单元均落实必要的数据契约、校验、权限控制、数据一致性和错误反馈；阶段划分用于安排开发顺序，质量要求保持一致。

## 产品参考

以网易云音乐作为功能组织与交互的产品参考，结合本项目的自主曲库和网站使用方式设计具体功能。

具体页面和业务能力在开发对应功能时，依据参考产品的实际页面、操作流程及本项目需求讨论确认。采用参考设计时，说明与当前业务的对应关系，以及浏览器操作和页面布局需要的适配。参考产品的能力经讨论确认后纳入功能需求。

曲库由站方通过管理端维护。管理端根据本项目的数据维护与运营需要设计，具体字段、操作和业务规则随相关功能讨论确定。

产品入口：[网易云音乐](https://music.163.com/)。

## 技术选型

以下技术构成项目的选型基础。用途和取舍是结合个人维护目标作出的项目决策，链接提供相应技术能力与接入要求的依据。

优先复用标准库、框架和已有依赖；现有能力不能满足需要时，评估成熟的企业或社区方案，再实现项目特有的业务逻辑。通用复杂能力采用成熟方案，简单、稳定的业务逻辑直接实现。新增依赖须说明适配性、维护状态、与现有版本的兼容性及接入成本。

### 后端与存储

| 技术 | 用途与适用条件 | 维护收益与取舍 | 参考来源 |
| --- | --- | --- | --- |
| Java 21 | 后端语言与运行基线 | 保留已选择的版本；与 Spring Boot 4 配合使用，初始化时核实所选 Boot 版本的支持范围 | [Boot 系统要求](https://docs.spring.io/spring-boot/system-requirements.html) |
| Spring Boot 4 | 应用启动、配置与框架集成 | 复用自动配置与依赖管理；接入第三方库时确认 Boot 4 兼容性 | [Boot 构建与依赖管理](https://docs.spring.io/spring-boot/reference/using/build-systems.html) |
| Spring Security | 认证、授权及 Web 安全控制 | 复用安全框架能力；具体登录与权限规则在认证相关功能设计时确定 | [Spring Security 官方文档](https://docs.spring.io/spring-security/reference/) |
| Maven | 后端依赖、构建与多模块聚合 | 利用模块依赖组织构建；维护者需要保持依赖方向清晰 | [Maven 多模块机制](https://maven.apache.org/guides/mini/guide-multiple-modules.html) |
| PostgreSQL | 业务关系数据的持久化、约束与事务 | 使用成熟关系数据库保障业务数据一致性；表结构与索引依据实际业务设计 | [PostgreSQL 官方介绍](https://www.postgresql.org/about/) |
| Flyway | 以版本化迁移管理数据库结构变更 | 结构变更随项目保存并可追溯；接入 PostgreSQL 时需要对应数据库支持模块 | [Flyway PostgreSQL 支持](https://documentation.red-gate.com/fd/postgresql-database-277579325.html) |
| MyBatis-Plus | 常规数据访问与 MyBatis 集成 | 减少重复 CRUD；复杂查询按实际需要编写 SQL，使用 Boot 4 专用 starter | [MyBatis-Plus 快速开始](https://baomidou.com/getting-started/) |
| Redis | 承担实际业务需要的缓存与临时数据 | 复用内存数据存储能力；每项用途在接入时明确数据寿命及与持久化数据的关系 | [Redis 官方文档](https://redis.io/docs/latest/) |
| RustFS | 自行部署对象存储，保存音频、封面等资源 | 复用对象存储服务；版本升级、存储运行与备份恢复由项目维护者负责，部署和接入细节在相关功能设计时确定 | [RustFS 部署说明](https://docs.rustfs.com/en/installation) |

媒体处理与播放方案在相关功能设计时，结合实际资源格式、浏览器支持和个人维护成本选择成熟能力。

### 管理端

管理端从 Vue 官方工程入口搭建，组合使用下列工具与组件库。

| 技术 | 用途与适用条件 | 维护收益与取舍 | 参考来源 |
| --- | --- | --- | --- |
| Vue 3 | 组件化构建管理端界面 | 沿用官方工程入口与生态能力，项目负责业务页面和交互编排 | [Vue 工程指南](https://vuejs.org/guide/quick-start) |
| TypeScript | 描述接口数据、组件及业务代码的类型契约 | 在开发和检查阶段发现类型问题；类型声明需要与真实数据保持一致 | [Vue 的 TypeScript 支持](https://vuejs.org/guide/typescript/overview) |
| Vite | 本地开发服务与生产构建 | 复用成熟构建工具；Node.js 与插件版本须满足所选 Vite 版本要求 | [Vite 官方指南](https://vite.dev/guide/) |
| Vue Router | 页面导航与路由组织 | 复用官方路由能力，具体路由随页面开发确定 | [Vue Router 官方介绍](https://router.vuejs.org/introduction.html) |
| Pinia | 跨组件、跨页面共享状态 | 集中维护确有共享需要的状态；局部状态保留在使用它的组件中 | [Pinia 官方介绍](https://pinia.vuejs.org/introduction.html) |
| Axios | HTTP 请求与响应接入 | 复用请求配置、拦截与取消能力；统一请求约定随接口接入确定 | [Axios 官方文档](https://axios-http.com/docs/intro) |
| Naive UI | 表格、表单、弹窗等通用界面组件 | 降低通用组件实现成本；组件外观优先通过组件属性和主题能力调整 | [Naive UI 官方仓库](https://github.com/tusen-ai/naive-ui) |
| Tailwind CSS | 页面布局、间距及局部样式 | 复用工具类组织样式；接入时确认基础样式与组件库的共同表现 | [Tailwind 的 Vite 集成](https://tailwindcss.com/docs/installation/using-vite) |
| pnpm | 各前端应用的依赖安装与脚本运行 | 应用独立维护依赖清单与锁文件；不使用 workspace，分别管理安装与升级 | [pnpm 安装说明](https://pnpm.io/cli/install) |

用户端的具体工程选型在对应开发工作中结合实际需求确定。

### 版本与依赖管理

- Java 使用 21，Spring Boot 使用 4 系列，Vue 使用 3 系列；具体发行版本在工程初始化时核实兼容性并锁定。
- Spring 配套依赖及 Boot 已管理的依赖优先跟随 Boot 的依赖管理，保持官方维护的版本组合。
- MyBatis-Plus 使用 `mybatis-plus-spring-boot4-starter`，其他独立依赖在接入时确认与所选版本的兼容性。
- PostgreSQL、Redis、RustFS、Node.js、pnpm 及前端依赖，在实际接入时选择受支持、适用的稳定版本并记录。官方资料中的滚动版本号不直接作为项目版本约定。
- 新增依赖先检查标准库、框架及已有依赖是否满足需要，再评估适配度、维护状态、兼容性和接入成本。

## 工程组织

### 仓库职责

同一仓库分开组织后端、前端和文档，目录职责如下。现有工程沿用已有位置，新增工程和业务目录在实际开发时建立。

| 位置 | 职责 |
| --- | --- |
| `backend/` | Maven 聚合工程、启动装配模块与业务模块 |
| `frontend/admin/` | 管理端独立前端工程 |
| `frontend/web/` | 用户端开始开发时建立的独立前端工程 |
| `docs/` | 已确认并需长期维护的项目事实与约定 |
| `CONTEXT.md` | 项目简介、关键约定与文档入口 |

### 后端模块

后端采用按业务拆分的 Maven 多模块，作为一个 Spring Boot 应用部署。聚合工程管理模块与依赖版本，启动装配模块负责应用入口和模块装配。

Java 根包使用 `com.nep`。启动装配模块为 `hoshi-app`，启动类为 `com.nep.HoshiApplication`，业务包位于该根包之下。

父工程聚合 `hoshi-common`、`hoshi-user`、`hoshi-auth` 和 `hoshi-app`。common 维护共享响应、业务异常、全局异常处理、分页、基础实体及 MyBatis-Plus 配置，并提供相关基础依赖；user、auth 依赖 common。app 依赖上述模块，保留启动入口与模块装配、配置文件及 Flyway 依赖和迁移资源。

业务模块围绕各自业务职责组织接口、业务逻辑和数据访问代码，业务逻辑归所属业务模块。模块名称及进一步拆分随具体业务确定。启动模块依赖业务模块，业务模块不反向依赖启动模块；跨模块通过明确的业务接口调用，数据访问由所属模块完成，避免直接操作其他模块的 Mapper。模块之间保持单向依赖，避免循环依赖。

公共能力在出现真实复用需要时集中维护，提取范围依据语义一致性和共同变化原因确定。模块划分服务于职责清晰与修改成本，不按尚未出现的扩展需求增加抽象。

组织依据：[Spring Boot 代码组织建议](https://docs.spring.io/spring-boot/reference/using/structuring-your-code.html)提供按业务组织代码的参考；[Maven 多模块机制](https://maven.apache.org/guides/mini/guide-multiple-modules.html)提供聚合与依赖构建能力；[Spring Modulith 模块边界](https://docs.spring.io/spring-modulith/reference/fundamentals.html)说明模块对外接口与内部实现的区分。本项目采用这些模块化思路，保留现有 Maven 多模块单体，是否引入 Spring Modulith 依据实际约束需要另行评估。

### 前端应用

管理端与用户端分别维护自己的 `package.json`、`pnpm-lock.yaml`、依赖安装目录及运行、构建脚本。依赖安装和命令执行以各自应用目录为工作目录，不使用 pnpm workspace。

管理端从 Vue 官方工程入口建立，通用界面使用 Naive UI，页面布局和局部样式使用 Tailwind CSS。应用内按业务集中组织页面、业务组件、请求和类型；布局、路由基础设施、HTTP 基础设施和通用组件单独维护。业务目录随实际功能建立，复用依据实际共同需求确定。

## 文档演进

项目概览记录长期定位、技术选型和工程约定；[功能需求](02-feature-requirements.md)记录已经确认的需求。功能范围和模块划分随开发演进，认证机制、缓存规则、音乐业务模型、媒体处理与播放方案和具体操作流程，在相关功能设计时讨论并归入对应文档。

工程环境建立后，在工程指南中记录真实启动方式、端口与环境变量来源。接口路由和字段在代码中确认后归档到 API 设计文档；表结构和索引在迁移或建表 SQL 执行后归档到数据库设计文档，均在对应任务结束前完成。具体格式遵循 [AGENTS.md](../AGENTS.md)。
