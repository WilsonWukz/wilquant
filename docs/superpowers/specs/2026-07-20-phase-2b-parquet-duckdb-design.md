# Personal A-Share Quant Lab：Phase 2B 规范化行情发布与 DuckDB 只读分析层设计

- 状态：待书面复核
- 日期：2026-07-20
- 基线：bef0af3929c2c9709075ba92037e453009c2fc04
- 分支：phase-2b-parquet-duckdb
- 范围：显式发布、不可变 Parquet、SQLite 发布控制面、DuckDB 受控只读查询
- 非范围：Phase 2C、策略、回测、交易、Broker、PAPER、LIVE、vn.py、QMT、XtQuant、实时或外部行情

## 1. 目标与边界

Phase 2B 将 Phase 2A 已上传、检查、标准化、预览并通过质量门禁的行情数据发布为项目管理的不可变 Parquet 数据集。

~~~text
Upload → Inspect → Normalize → Preview → Quality Review
→ Explicit Publish → Re-normalize and Fingerprint Check
→ Staging → Validate → Atomic Directory Promotion
→ SQLite Finalization → DuckDB Controlled Query
~~~

优先级为：数据不可变性 > 文件与数据库一致性 > 可恢复性 > 幂等性 > 数据血缘 > 查询安全 > 性能 > 界面。系统继续只有 RESEARCH。

Phase 2B 复用 Phase 2A 的受控上传、Provider、显式字段映射、标准化、质量校验、issue 去重、错误脱敏、runtime root 和安全脚本。Preview Bar 继续只存在于有界内存，不生成私有 Parquet 或准正式快照。未来 Preview 快照只能通过独立 ADR 评估。

## 2. 固定版本

~~~text
local_csv@1 / local_parquet@1
market-bar@1
a-share-daily-normalization@1
a-share-daily-quality@1
quality-issue-sha256@2
preview-sha256@1
parquet-market-bars@1
daily-exchange-year@1
market-bars-manifest@1
~~~

Provider 公开固定版本；其余版本由单一版本模块提供。Publish 必须使用 Preview 保存的相同版本。当前程序不支持旧版本时返回 RULE_VERSION_MISMATCH，ImportBatch 进入 STALE，不得用新规则静默解释旧 Preview。

## 3. Preview 持久化

0004 为 import_batches 增加：

~~~text
source_file_size
field_mapping_json
provider_version
normalization_version
quality_rules_version
preview_fingerprint_version
preview_fingerprint
preview_completed_at
~~~

已有字段继续保存不可变上传 SHA-256、安全 storage key、Provider 名称、Schema 版本和统计。字段映射以 key 排序的 canonical JSON 保存，只允许标准字段白名单，源列必须来自 inspect 结果。

Preview 完成事务必须同时保存映射、所有版本、accepted/rejected/warning 统计、Preview fingerprint、完成时间和 issue 集合。0004 不猜测历史批次的映射或 fingerprint；旧批次重新 Preview 前返回 PREVIEW_REQUIRED。

## 4. Quality issue fingerprint v2

0003 历史不修改；0004 引入 quality-issue-sha256@2，增加 issue_fingerprint_version 和可空 normalized_value，再迁移已有 issue。

Canonical payload 至少包含：

~~~json
{
  "row_number": 2,
  "instrument_id": "600000.XSHG",
  "symbol": "600000",
  "severity": "ERROR",
  "issue_code": "HIGH_BELOW_LOW",
  "field_name": "high",
  "canonical_raw_value": "9",
  "canonical_normalized_value": null
}
~~~

明确排除本地化 message、Python 异常文本、数据库 ID、创建时间、耗时和路径。row_number 与规范标的身份防止不同源行被错误去重。

Raw value 区分 null 与空字符串，统一 Unicode NFC 和换行符但保留有意义的首尾字符；normalized value 使用规范日期、枚举、整数和 Decimal 表示。迁移后若 v2 身份重合，按确定性顺序保留第一条，再恢复 (batch_id, issue_fingerprint) 唯一索引。message 只用于展示。

## 5. Preview fingerprint

Preview fingerprint 是完整标准化和质量结果的 SHA-256，不是文件 Hash 或映射的别名。Canonical envelope 覆盖：

~~~text
fingerprint version
source SHA-256与size
Provider name/version
Schema、标准化和质量规则版本
按标准字段名排序的显式映射
全部行的确定性结果
row/accepted/rejected/warning汇总
~~~

成功规范化行覆盖：源行号、instrument_id、symbol、exchange、frequency、trade_date、UTC 微秒 timestamp、OHLC、volume、amount、adjustment_type、quality_status 和排序后的 issue fingerprint。解析失败行也覆盖源行号、PARSE_REJECTED 和 issue fingerprint。

行按源行号升序，因为时间逆序和相邻涨幅规则依赖输入顺序。每行 issue 按 severity、issue_code、field_name、issue_fingerprint 排序。

序列化使用 UTF-8、JSON key 排序、无额外空白、禁止 NaN/Infinity。Decimal 使用非指数定点字符串并去除无意义尾零；日期为 ISO；timestamp 为 UTC 微秒精度。

排除 ingested_at、batch/request ID、数据库 ID、临时路径、执行/日志时间、耗时、Python 对象表示。Provider 已在 envelope 表达，逐行 data_source 和 source_batch_id 不参与。

## 6. Publish 资格与重放

Phase 2B 不做部分发布。允许发布必须满足：

- ImportBatch 为 PREVIEW_READY，或具有完整 Preview 记录且可重试的 PUBLISH_FAILED；
- accepted > 0、rejected = 0，不存在 ERROR/FATAL；
- WARNING 必须显式 confirm_warnings=true；
- expected fingerprint 与 Preview 记录一致；
- 当前为 RESEARCH，且无相同发布正在运行。

Publish 必须验证受控源路径仍在 upload staging 根内；检查文件存在和大小；重新计算 SHA-256；验证 Provider/Schema/标准化/质量版本；使用保存的映射调用 Phase 2A 同一解析、标准化和校验服务；重新生成统计、issue 和 Preview fingerprint；逐项完全比较。

Hash、映射、版本、统计或 fingerprint 任一变化都返回 PREVIEW_STALE，ImportBatch 进入 STALE。不得覆盖原 Preview 或写 Parquet；审计只保存稳定错误码和脱敏摘要，并要求重新 Preview。

## 7. 上传源文件生命周期

引用状态为 PREVIEW_READY、PUBLISHING 或可重试 PUBLISH_FAILED 的 staging 文件不得清理。STALE 和 PUBLISHED 在 Phase 2B 也默认保留，以支持重新 Preview 与审计。

本阶段不实现垃圾回收。未来清理必须先检查 SQLite 引用和保留策略，不能只按文件年龄、扩展名或目录扫描删除，只能处理数据库确认无引用的受控 storage key。

## 8. Dataset 创建与 Publish 分离

~~~text
POST /api/v1/datasets
POST /api/v1/data-batches/{batch_id}/publish
~~~

Dataset 必须先独立创建。Publish 只接受已存在的 dataset_id，不支持一站式创建。

Dataset 创建使用 canonical identity 生成稳定唯一 dataset_key：

~~~text
caller logical_key / dataset_type / market / frequency / adjustment_type / schema_version
~~~

名称和描述可修改，不是身份。重复相同 dataset_key 返回已有 Dataset。

Publish 请求只包含 dataset_id、expected_preview_fingerprint、frequency、adjustment_type、confirm_publish、confirm_warnings，以及可选 operator_label、request_note。

## 9. 领域模型

### Dataset

~~~text
dataset_id / dataset_key / logical_key / name / description
dataset_type / market / frequency / adjustment_type / schema_version
created_at / updated_at / is_active
~~~

dataset_key 唯一。已有版本后不得修改逻辑身份字段。

### DatasetVersion

~~~text
dataset_version_id / dataset_id / version / status
source_batch_id / source_preview_fingerprint / publication_fingerprint
schema_version / normalization_version / quality_rules_version
publication_format_version / partition_strategy_version
row_count / instrument_count / min_timestamp / max_timestamp
partition_count / file_count / total_size_bytes
quality_issue_count / warning_count / blocking_issue_count / quality_summary_json
relative_version_root / manifest_path / manifest_sha256
publication_claimed_at / published_at / created_at
failure_code / failure_reason
~~~

relative_version_root 和 manifest_path 相对于 published root；SQLite、Manifest、API 不保存盘符或机器绝对路径。唯一约束为 (dataset_id, version) 和 publication_fingerprint。

### DatasetFile

~~~text
dataset_file_id / dataset_version_id / relative_path / partition_values_json
row_count / size_bytes / sha256 / min_timestamp / max_timestamp / created_at
~~~

(dataset_version_id, relative_path) 唯一；路径相对于该版本 root。

## 10. Publication fingerprint 与版本分配

Publication fingerprint 覆盖 source Preview fingerprint、dataset_id、frequency、adjustment type、Schema、发布格式、分区版本、压缩和发布列定义。

DatasetVersion claim 使用一个短 BEGIN IMMEDIATE 事务：验证 Dataset；查询 publication fingerprint；已发布则返回；处理中则返回同一 version ID；不存在时在事务内计算 max(version)+1 并立即插入 DatasetVersion claim；同一事务把 ImportBatch 更新为 PUBLISHING；提交后才做文件操作。

(dataset_id, version) 和 publication fingerprint 唯一约束提供最终保护。版本绝不在事务外预分配。

第一次 claim 同时冻结 publication_claimed_at。Manifest 重建、幂等重试和恢复必须复用该时间，不得重新取当前时间。

## 11. 状态职责

ImportBatch：

~~~text
PREVIEW_READY → PUBLISHING → PUBLISHED
                         ↘ PUBLISH_FAILED
                         ↘ STALE
~~~

DatasetVersion：

~~~text
VALIDATING → STAGING → FILES_COMMITTING → FILES_COMMITTED → PUBLISHED
          ↘ FAILED
~~~

目录提升前后只更新 DatasetVersion 的 FILES_COMMITTING/FILES_COMMITTED。整个文件阶段 ImportBatch 保持 PUBLISHING；最终 SQLite 事务成功后两者才一起进入 PUBLISHED。查询只承认 DatasetVersion PUBLISHED。

## 12. 幂等与并发

- 相同 fingerprint 已 PUBLISHED：HTTP 200，同一 DatasetVersion，idempotent_replay=true；
- 相同 fingerprint 处理中：HTTP 202，同一 version ID 和状态；
- 唯一约束竞争失败：重新读取胜出记录；
- 可恢复失败：同一显式请求复用原 DatasetVersion，不分配新版本；
- 不一致：PUBLICATION_RECOVERY_REQUIRED，不覆盖目录。

重复请求不生成第二套目录、DatasetFile 或实质发布审计；可以记录轻量 IDEMPOTENT_HIT。

## 13. Parquet Schema、排序与分区

~~~text
instrument_id VARCHAR
symbol VARCHAR
exchange VARCHAR
frequency VARCHAR
timestamp TIMESTAMP_MICROS
trade_date DATE
open/high/low/close DECIMAL(20,8)
volume BIGINT
amount DECIMAL(20,8)
adjustment_type VARCHAR
quality_status VARCHAR
source_batch_id VARCHAR
~~~

timestamp 存储 UTC 时点；Manifest 声明 UTC、Asia/Shanghai 和日线 15:00 语义。发布行按 frequency/exchange/instrument_id/trade_date/timestamp 排序并验证业务唯一键。

首版按 frequency/exchange/year 分区，不按 symbol 分区，以避免 20 MiB 输入产生小文件。最多 64 个分区，每分区一个 ZSTD 文件：part-ordinal-hashprefix.parquet。

~~~text
published/market_bars/dataset=<id>/version=<六位版本>/
├── manifest.json
└── frequency=DAILY/exchange=XSHG/year=2026/part-00000-....parquet
~~~

分区值只来自内部枚举和年份，用户文本不参与路径。

## 14. Manifest

Manifest 是 UTF-8 canonical JSON，key 与数组稳定排序，结尾单个换行。覆盖 Manifest 版本、Dataset/Version、source batch/SHA/Preview fingerprint、publication fingerprint、Schema/列、frequency/adjustment、时区、分区策略、相对文件清单和 Hash、行数/标的/时间范围、质量摘要、publication_claimed_at 和 producer 版本。

publication_claimed_at 来自第一次 claim。实际最终事务时间只保存在 SQLite published_at，不进入 Manifest，以免重试改变内容。Manifest 不包含自己的 Hash；manifest_sha256 存 SQLite。不得包含绝对路径、账户、API key、用户名或无关环境信息。

## 15. 原子提升、持久性与恢复

新增 runtime-root 相对配置：

~~~text
data/publication-staging
data/published
~~~

发布前确认两者位于同一文件系统/Windows volume。流程：创建唯一 nonce staging；写 .parquet.tmp；关闭连接并重读校验 Schema、类型、行数、范围、唯一键和 Hash；改名为 part 文件；写和校验 manifest.json.tmp；改名为 manifest；确认最终目录不存在；DatasetVersion 进入 FILES_COMMITTING；同卷重命名整个目录；进入 FILES_COMMITTED；最终 SQLite 事务插入 DatasetFile/统计/审计并把 DatasetVersion 与 ImportBatch 一起标记 PUBLISHED。

同卷重命名只提供原子可见性，不是文件系统与 SQLite 的跨介质事务：原子重命名避免半套目录可见；宕机持久性依赖文件关闭、重读、Hash、Manifest 和幂等恢复；查询只承认 SQLite PUBLISHED。

失败策略：

- fingerprint 不一致：STALE，不创建 staging；
- 写入/Manifest/校验失败：只清理本次精确 nonce，版本 FAILED、batch PUBLISH_FAILED；
- 清理失败只记录警告，不覆盖原异常；
- Windows 锁有限重试后返回 PUBLICATION_FILE_LOCKED；
- 目录提升成功但 SQLite 失败：保留最终目录，版本保持 FILES_COMMITTING/FILES_COMMITTED，查询不可见；
- 相同请求重试：用冻结 claim、确定性路径、Manifest 和全部 Hash 复验后完成事务；
- 最终目录不匹配：PUBLICATION_RECOVERY_REQUIRED，不删除、不覆盖、不发布。

不实现后台恢复队列、启动扫描或自动垃圾回收。

## 16. SQLite 不可变触发器与外键

触发器只阻止 OLD.status=PUBLISHED 后的 DatasetVersion UPDATE、PUBLISHED 版本 DELETE，以及其 DatasetFile UPDATE/DELETE。它不阻止 FILES_COMMITTED→PUBLISHED。

DatasetVersion→Dataset/ImportBatch、DatasetFile→DatasetVersion、PublicationAudit→相关实体全部使用 ON DELETE RESTRICT，不使用级联删除，避免绕过不可变规则。Phase 2B 不提供删除 API。

## 17. DuckDB 只读分析层

SQLite 是发布事实来源，DuckDB 不复制完整数据到持久表。查询服务按 SQLite 中指定的 PUBLISHED DatasetVersion 和 DatasetFile 创建短生命周期连接及内部逻辑 CTE，通过参数化 read_parquet 查询。

不在持久 DuckDB catalog 保存含机器路径的视图。绝对路径只在进程内由 relative path 与 published root 组合，并验证 resolved path 仍在 root 内；不返回或持久化。

前端不能提交 SQL、路径、ATTACH、COPY、INSTALL 或 LOAD。查询不扫描 staging、FAILED、上传源或 Preview。默认 100、最大 500 行，最大十年、最多 256 文件、2 线程、512 MiB 和 5 秒超时；cursor 基于 instrument_id/timestamp。

## 18. API、操作者与审计

~~~text
POST /api/v1/datasets
GET  /api/v1/datasets
GET  /api/v1/datasets/{dataset_id}/versions
GET  /api/v1/datasets/{dataset_id}/versions/{version_id}
POST /api/v1/data-batches/{batch_id}/publish
GET  /api/v1/market-bars
~~~

行情查询强制指定 dataset_version_id，不提供隐式 latest。

当前没有认证。服务端固定 actor_type=LOCAL_UNAUTHENTICATED_USER。客户端 operator_label 和 request_note 只是未经认证的备注，不是可信身份，不参与权限或 fingerprint。

PublicationAudit 记录 request/audit ID、actor type、备注、batch/Dataset/Version、expected/actual Preview fingerprint、publication fingerprint、canonical 配置、warning 确认、时间、结果、稳定 failure code、Manifest Hash、文件/行数和 idempotent replay。错误不包含绝对路径、SQL、堆栈或原始数据库异常。

## 19. 前端

现有 /data/import 增量显示 Preview fingerprint、阻断状态、已有 Dataset 选择、warning 确认和不可变发布确认。新增 /datasets 和 /datasets/{dataset_id}，支持 Dataset 创建、版本列表/详情、Manifest 摘要、血缘和受限查询预览。

不提供任意 SQL、文件编辑、版本删除、交易、策略或回测控件。

## 20. Alembic 0004 与测试

新增线性 20260720_0004，不修改 0001–0003。它扩展 import_batches、升级 issue fingerprint v2、创建 datasets/dataset_versions/dataset_files/publication_audits，并建立唯一约束、RESTRICT 外键和精确不可变触发器。Downgrade 只撤销 0004 对象，不删除 Phase 2A DataSource、ImportBatch 或上传文件。

必须测试空库→head、0003→0004、重复 upgrade、0004→0003→0004，以及：

- issue/Preview/publication fingerprint 确定性、排除字段和版本漂移；
- Preview 事务完整性；Dataset 创建幂等；BEGIN IMMEDIATE 版本分配；
- 所有发布成功、阻断、源变化、重复和并发场景；
- Parquet Schema、Decimal、timestamp、排序、唯一键、Hash 和重读；
- Manifest canonical 内容与冻结时间；
- 文件/Manifest/校验/SQLite 故障注入和恢复；
- 不可变触发器允许正常发布但拒绝已发布修改/删除；
- DuckDB 过滤、cursor、限制和非 PUBLISHED 隔离；
- Windows 空格/中文路径、同卷、文件锁和不越界清理；
- API 脱敏、固定 actor type、前端功能和 Phase 2A 全量回归。

测试数据写入唯一隔离临时目录，不访问外部网络，不污染仓库运行目录。

## 21. 明确不做

不实现 Preview 私有 Parquet、删除/垃圾回收、后台恢复队列、S3、权限系统、任意 SQL、外部/实时行情、策略、回测、Broker、vn.py、QMT、XtQuant、PAPER、LIVE、版本原地修改、自动覆盖或自动 latest 数据源。

Phase 2B 完成后停止，不自动进入 Phase 2C 或 Phase V1。
