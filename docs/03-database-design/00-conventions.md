# 数据库与持久化约定

## 开发数据库

本机共享基础设施位于 `/home/nep/01-Own/infra`。Hoshi 复用其中的 PostgreSQL 容器与已有 `postgres` 账号，使用独立的 `hoshi` 数据库，应用数据与 Flyway history 位于 `public` schema。

容器编排声明的镜像为 `pgvector/pgvector:pg16`，宿主机访问地址为 `127.0.0.1:5432`。连接密码沿用共享环境的已有值，只保存在本地开发配置中。启动步骤见[工程指南](../05-engineering-guide.md)。

## 迁移管理

Flyway 的 starter、PostgreSQL 支持模块和迁移资源归 `hoshi-app`。迁移脚本存放在该模块的 `src/main/resources/db/migration/`，采用 Flyway 版本化 SQL 命名，例如 `V1__create_users.sql`；该文件名仅说明格式，不代表已定义用户表。

命名校验已开启，错误命名的迁移文件会阻止迁移。已执行的版本化迁移保持内容不变，结构调整通过后续迁移表达。Flyway 沿用迁移前校验、禁用 clean、关闭自动 baseline 的默认设置。

没有业务迁移时，Flyway 可以建立 `flyway_schema_history` 并正常完成启动；日志中的无迁移提示不表示需要创建占位 SQL。实际业务表和索引在迁移执行后归档到相应模块文档。

## 公共时间字段

需要统一创建和更新时间的实体继承 `com.nep.common.entity.BaseEntity`。公共字段约定如下，具体业务表的完整结构与约束在对应迁移中确定。

| Java 字段 | Java 类型 | 数据库列 | PostgreSQL 类型 | 填充行为 |
| --- | --- | --- | --- | --- |
| createdAt | OffsetDateTime | created_at | TIMESTAMPTZ | 插入时未赋值则填充 UTC 当前时间，不参与 MP 基于实体生成的更新 SET |
| updatedAt | OffsetDateTime | updated_at | TIMESTAMPTZ | 插入时未赋值则填充 UTC 当前时间，更新时覆盖为 UTC 当前时间 |

一次插入对两个未赋值字段使用同一个时间点。实体对象创建后、执行插入前允许字段为 null；采用自动填充写入时，在 SQL 执行前由处理器赋值。时间通过 Boot 默认的 Jackson 3 集成输出为 ISO 日期时间字符串。

PostgreSQL 的 TIMESTAMPTZ 保存时间点，不保存原始时区或偏移；pgJDBC 对应使用 OffsetDateTime，并以 UTC 偏移读取。

MyBatis-Plus 自动填充依赖实体及字段填充元数据。`update(entity, wrapper)` 的 entity 必须非空；只传 Wrapper 的更新或自定义 SQL 需要显式维护更新时间。公共实体不统一声明主键、版本号、逻辑删除或操作人，具体表按业务需要增加。

## MyBatis-Plus 使用

MP 组件通过官方 BOM 统一为 `3.5.18.1`，使用 Boot 4 专用 starter，并显式引入分页所需的解析器依赖。

common 中的 `com.nep.common.config.MybatisPlusConfiguration` 按顺序注册乐观锁、防全表更新删除、PostgreSQL 分页插件，并在另一个 Bean 中匿名实现字段填充处理器。分页最大条数复用 `PageQuery.MAX_PAGE_SIZE`，越界页不回到第一页。

乐观锁依赖具体实体的 `@Version` 字段及受支持的更新方法；影响零行时的业务反馈由对应服务决定。防全表插件用于拦截可识别的危险 UPDATE/DELETE，不能代替业务查询条件或数据库权限控制。Mapper 随业务增加，使用 `@Mapper` 标记，由 starter 在应用根包下发现。

Mapper XML 存放在各业务模块的 `src/main/resources/mapper/<模块名>/` 下。公共 YAML 显式设置 `mybatis-plus.mapper-locations` 为 `classpath*:/mapper/**/*.xml`，扫描 app 与依赖模块的资源。XML 的 namespace 使用对应 Mapper 接口全限定名，语句 id 对应接口方法名。

MyBatis 日志实现使用 `org.apache.ibatis.logging.slf4j.Slf4jImpl`，SQL 日志进入统一日志系统。开发配置仅为 `com.nep.user.mapper`、`com.nep.auth.mapper` 启用 DEBUG；新增业务 Mapper 包时在本地开发配置中按需增加，公共日志级别保持 INFO。

参考依据：[MyBatis-Plus 自动填充](https://baomidou.com/guides/auto-fill-field/)、[分页插件](https://baomidou.com/plugins/pagination/)、[乐观锁插件](https://baomidou.com/plugins/optimistic-locker/)、[pgJDBC 时间类型](https://jdbc.postgresql.org/documentation/query/#using-java-8-date-and-time-classes)、[Flyway PostgreSQL 支持](https://documentation.red-gate.com/fd/postgresql-database-277579325.html)。
