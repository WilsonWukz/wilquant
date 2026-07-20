# Personal A-Share Quant Lab：Phase 2A 数据基础设计

- 状态：已批准
- 日期：2026-07-20
- 范围：本地 CSV/Parquet 导入、标准化、质量检查和预览
- 非范围：正式 Parquet 发布、复杂 DuckDB 查询、外部行情、策略、回测、Broker、vn.py

## 1. 目标与边界

Phase 2A 建立一条可审计、确定性、无外部网络的数据导入纵向切片：

```text
Browser File
  → Controlled Upload Staging
  → Provider Inspection
  → Explicit Field Mapping
  → Parse and Normalize
  → Deterministic Validation
  → Preview + SQLite Metadata
```

流程止于 `PREVIEW_READY`。原始上传文件保存于受控运行目录，Bar 只在一次预览请求的有界内存中存在，不写 SQLite，也不发布正式 Parquet。

## 2. 运行目录

新增 `QUANT_LAB_RUNTIME_ROOT`。未设置时，现有相对路径继续基于项目根目录；设置后，SQLite、DuckDB、日志、PID 和上传暂存区的相对路径统一基于该目录。显式绝对路径保持原义。fixtures 永远位于仓库内，不迁移现有文件，不自动删除旧数据。

新增安全默认值：

```dotenv
QUANT_LAB_RUNTIME_ROOT=
QUANT_LAB_IMPORT_DIRECTORY=imports/staging
QUANT_LAB_IMPORT_MAX_BYTES=20971520
QUANT_LAB_IMPORT_PREVIEW_ROWS=100
```

PowerShell 与 Python 使用相同环境变量规则；相对 runtime root 以项目根目录为基准，与终端当前目录无关。可选的非同步运行目录示例为 `F:\WIL_QUANT_RUNTIME` 或 `D:\WIL_QUANT_RUNTIME`。

## 3. 领域模型

- `Exchange`: `XSHG`、`XSHE`。
- `BarFrequency`: `DAILY`，并预留分钟枚举而不实现分钟聚合。
- `AdjustmentType`: `NONE`、`FORWARD`、`BACKWARD`、`UNKNOWN`。
- `QualityStatus`: `ACCEPTED`、`WARNING`、`REJECTED`。
- `ImportBatchStatus`: `PENDING`、`PARSING`、`VALIDATING`、`PREVIEW_READY`、`FAILED`、`CANCELLED`；没有 `PUBLISHED`。
- `IssueSeverity`: `INFO`、`WARNING`、`ERROR`、`FATAL`。

内部标的 ID 为 `<六位代码>.<XSHG|XSHE>`。输入交易所别名只允许显式白名单；交易所缺失时仅按六位代码首位做有限推断：`5/6/9 → XSHG`，`0/1/2/3 → XSHE`，其余拒绝。该规则不推断股票/ETF 类型。

价格和成交额使用 `Decimal`；成交量使用非负整数。日线 `trade_date` 表示上海时区交易日，`timestamp` 固定表示 `Asia/Shanghai` 当日 15:00 收盘时点。审计时间使用 UTC 带时区时间。

## 4. Provider 边界

`MarketDataProvider` 是项目内部 Protocol，包含 `name`、`inspect`、`load_bars` 和 `health_check`。Provider 只读取受控文件并返回原始/半结构化行，不写数据库、不修改 Instrument、不发布 Parquet、不调用网络或 Broker。

- CSV：标准库 `csv`，`utf-8-sig` 同时支持 UTF-8/BOM；编码错误明确分类；不模糊猜测关键字段。
- Parquet：使用现有 DuckDB 连接读取 schema 和行，不新增 pandas/PyArrow。
- Synthetic：在内存构造正常和异常数据，供确定性测试使用。

字段映射由客户端显式提交。inspect 只给出有限别名建议并将建议返回用户，不自动采用未知映射。

## 5. 上传安全

`POST /api/v1/data/imports/inspect?filename=<display-name>` 接收 `application/octet-stream`。后端：

1. 只接受 `.csv`、`.parquet`；
2. 流式计算大小和 SHA-256；
3. 超限立即失败并删除仅由本请求创建的临时文件；
4. 使用 UUID 生成服务器文件名并限制在 staging 根目录；
5. 不使用客户端文件名拼接服务器路径；
6. 原子替换临时文件为 staging 文件；
7. API 和日志不返回绝对路径或文件内容。

inspect 成功后创建 `DataSource` 和 `ImportBatch(PENDING)`，返回 `batch_id`、列、建议映射、大小和哈希。重复 SHA-256 返回稳定的冲突错误，不创建第二个活动批次。

## 6. 标准化与质量规则

逐行结果保留原始行号和问题，不使用 `dropna` 或静默跳过。存在 ERROR/FATAL 的行拒绝；只有 WARNING 的行接受但标记 WARNING。

阻断规则：缺失必填字段、日期/代码/交易所/数值无法解析、价格非正、成交量/额为负、`high < low`、open/close 超出区间、相同标的/频率/交易日重复、时间逆序、空文件、不支持格式、重复文件哈希。

有限 WARNING：零成交量、零成交额、相邻收盘价绝对涨幅超过 30%。完整交易日历、停牌、复权、历史涨跌停和板块规则明确未实现；“非交易日”和日期间断在没有权威日历前不伪装为完整支持。

## 7. SQLite 元数据

`20260720_0002` 迁移只新增：

- `instruments`
- `data_sources`
- `import_batches`
- `data_quality_issues`

不创建 Bar 表。`import_batches.source_file` 只保存显示名和内部 staging key，不保存敏感绝对路径。`20260720_0003` 为质量问题增加稳定 fingerprint，并以 `(batch_id, issue_fingerprint)` 建立唯一索引；重复 preview 在一个事务内替换该批次统计和 issue 集合。质量问题逐条保存，便于分页读取；预览 Bar 样本不持久化。

## 8. API 与错误

- `POST /api/v1/data/imports/inspect`
- `POST /api/v1/data/imports/preview`
- `GET /api/v1/data/imports/{batch_id}`
- `GET /api/v1/data/imports/{batch_id}/issues`

preview 请求包含 `batch_id` 与标准字段到源列的显式映射。错误返回稳定 code、中文 message、request_id 和可选 batch_id；不返回堆栈、数据库连接或绝对路径。

日志白名单增加 `request_id`、`batch_id`、`provider`、`source_hash`、计数、`error_category`、`duration_ms`，不记录完整文件内容。

## 9. 前端

保留 `/` 状态页，新增 `/data/import` 和安全 404。无需引入路由库，`App` 按 `window.location.pathname` 做三个明确分支。

导入页允许选择本地 CSV/Parquet，先 inspect，再展示列与建议映射，最后请求 preview；显示总数、接受、警告、拒绝、有限样本和质量问题。没有发布、策略、回测、交易或 vn.py 控件。

## 10. vn.py 边界

Phase 2A 不导入、不安装、不检测、不启动 vn.py。未来 VnpyMarketDataProvider 只能实现同一 Provider/标准化入口，不能成为历史数据或质量管道的唯一来源。ADR-0001 的独立进程决策不改变本阶段实现。
