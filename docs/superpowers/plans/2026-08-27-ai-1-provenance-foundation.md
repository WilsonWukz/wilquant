# AI-1 Provenance Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立不调用真实模型的 AI provenance 基础，使 ResearchCase、Prompt/Model 版本、AnalysisRun、Attempt、Trace 和 Usage 可被不可变地记录、校验和查询。

**Architecture:** 在现有 FastAPI 模块化单体中新增纯领域 `quant_lab.ai` 模块，由 SQLite 保存控制面和 append-only 审计。AI-1 不安装 provider SDK、不创建 Provider Host、不生成诊断/建议，也不接触 PAPER/LIVE；所有哈希使用现有 canonical JSON 习惯，所有外部响应通过 FastAPI DTO。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、SQLite、pytest、Ruff、mypy、React/TypeScript（仅保持 API 不影响现有前端）

---

## 开始前检查

- 当前计划假设 Alembic head 仍为 `20260722_0013`。执行时先运行 `alembic heads`；若 head 已变化，停止并重新编号 migration，不创建分叉 head。
- 使用单独实现任务开始时创建的工作区隔离；本设计轮次不执行本计划。
- 不从 PA_Agent 复制代码、schema、Prompt、错误分类或 tests。
- 每个任务提交前运行该任务的定向测试；最后运行 `scripts/test.ps1`。

### Task 1: 建立 AI 纯领域类型与 canonical fingerprints

**Files:**
- Create: `backend/src/quant_lab/ai/__init__.py`
- Create: `backend/src/quant_lab/ai/domain.py`
- Create: `backend/src/quant_lab/ai/fingerprints.py`
- Test: `backend/tests/ai/test_fingerprints.py`
- Test: `backend/tests/ai/test_domain.py`

- [ ] **Step 1: 写 fingerprint 失败测试**

测试必须证明字典 key 顺序不影响 SHA-256，而 list 顺序和字段值变化会影响：

```python
from quant_lab.ai.fingerprints import fingerprint_payload


def test_fingerprint_is_canonical_for_mapping_order() -> None:
    assert fingerprint_payload({"b": 2, "a": 1}) == fingerprint_payload({"a": 1, "b": 2})


def test_fingerprint_preserves_list_order() -> None:
    assert fingerprint_payload({"items": [1, 2]}) != fingerprint_payload({"items": [2, 1]})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_fingerprints.py -q`

Expected: FAIL，原因是 `quant_lab.ai` 尚不存在。

- [ ] **Step 3: 实现领域 enum/value contracts**

`domain.py` 定义且只定义：

```python
from enum import StrEnum


class AIAnalysisStage(StrEnum):
    DIAGNOSIS = "DIAGNOSIS"
    RECOMMENDATION = "RECOMMENDATION"
    CONVERSATION = "CONVERSATION"


class AIAnalysisRunStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class AIModelAttemptStatus(StrEnum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


class AITraceEventType(StrEnum):
    CASE_FROZEN = "CASE_FROZEN"
    PROMPT_RESOLVED = "PROMPT_RESOLVED"
    PROVIDER_ATTEMPT_STARTED = "PROVIDER_ATTEMPT_STARTED"
    PROVIDER_ATTEMPT_FAILED = "PROVIDER_ATTEMPT_FAILED"
    PROVIDER_ATTEMPT_COMPLETED = "PROVIDER_ATTEMPT_COMPLETED"
    RUN_FAILED = "RUN_FAILED"
    RUN_CANCELLED = "RUN_CANCELLED"
    RUN_COMPLETED = "RUN_COMPLETED"
```

`fingerprints.py` 复用 `quant_lab.market_data.fingerprints.canonical_json_bytes`，暴露：

```python
def fingerprint_payload(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
```

- [ ] **Step 4: 写并运行 enum 稳定性测试**

`test_domain.py` 断言所有 persisted enum 的 `.value` 等于上面字符串，并断言没有 `ORDER`、`FILL`、`LIVE`、`CAPITAL` 成员。

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_domain.py backend/tests/ai/test_fingerprints.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add backend/src/quant_lab/ai backend/tests/ai/test_domain.py backend/tests/ai/test_fingerprints.py
git commit -m "feat(ai): add provenance domain fingerprints"
```

### Task 2: 定义 Prompt、Model、ResearchCase 与 Run persistence

**Files:**
- Create: `backend/src/quant_lab/ai/persistence.py`
- Test: `backend/tests/ai/test_persistence_models.py`

- [ ] **Step 1: 写 ORM schema 失败测试**

测试使用临时 SQLite `Base.metadata.create_all()`，确认以下 table 存在：

```python
EXPECTED = {
    "ai_prompt_template_versions",
    "ai_model_config_versions",
    "ai_research_cases",
    "ai_evidence_refs",
    "ai_analysis_runs",
    "ai_model_attempts",
    "ai_analysis_trace_events",
    "ai_usage_ledger",
}
```

并检查所有 fingerprint 列 `nullable=False`、长度 64，secret/API key 列完全不存在。

- [ ] **Step 2: 运行确认失败**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_persistence_models.py -q`

Expected: FAIL，原因是 persistence model 尚不存在。

- [ ] **Step 3: 实现 ORM models**

`persistence.py` 创建以下 SQLAlchemy models：

```text
AIPromptTemplateVersionModel
  id, template_name, stage, schema_version, content, content_sha256,
  variable_contract_json, variable_contract_sha256,
  validator_policy_version, status, created_by, created_at

AIModelConfigVersionModel
  id, provider_kind, model_identifier, endpoint_profile_id,
  parameters_json, fingerprint, created_by, created_at

AIResearchCaseModel
  id, purpose, market, instrument_id, asset_type, currency, timeframe,
  as_of_utc, market_local_trade_date, bindings_json,
  previous_case_id, previous_analysis_run_id, thesis_revision_id,
  fingerprint, created_by, created_at

AIEvidenceRefModel
  id, case_id, evidence_type, source_entity_type, source_entity_id,
  source_version_id, content_sha256, locator_json,
  effective_at, known_at, captured_at,
  market, instrument_id, currency, temporal_status,
  integrity_status, fingerprint, created_at

AIAnalysisRunModel
  id, case_id, stage, status, parent_run_id,
  prompt_template_version_id, model_config_version_id,
  case_fingerprint, prompt_template_fingerprint,
  resolved_prompt_fingerprint, model_config_fingerprint,
  validator_policy_version, validator_policy_fingerprint,
  input_envelope_fingerprint, raw_response_artifact_sha256,
  normalized_output_fingerprint, started_at, completed_at,
  failure_code, safe_failure_message, created_at

AIModelAttemptModel
  id, run_id, attempt_number, status, provider_request_id,
  input_fingerprint, output_fingerprint, latency_ms, finish_reason,
  failure_code, started_at, completed_at

AIAnalysisTraceEventModel
  id, run_id, sequence, event_type, payload_json,
  payload_fingerprint, occurred_at

AIUsageLedgerModel
  id, run_id, attempt_id, prompt_tokens, cached_prompt_tokens,
  completion_tokens, total_tokens, reported_cost, estimated_cost,
  currency, is_estimate, occurred_at
```

约束：`(run_id, attempt_number)`、`(run_id, sequence)` 唯一；所有外键使用明确 RESTRICT/CASCADE，不能 cascade 删除 provenance；`parameters_json` 明确禁止 `api_key`/`secret` 由 service 层验证。

- [ ] **Step 4: 运行 model tests**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_persistence_models.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add backend/src/quant_lab/ai/persistence.py backend/tests/ai/test_persistence_models.py
git commit -m "feat(ai): model provenance persistence"
```

### Task 3: 新增 migration 与 append-only triggers

**Files:**
- Create: `backend/alembic/versions/20260827_0014_ai_provenance_foundation.py`
- Test: `backend/tests/ai/test_provenance_migration.py`

- [ ] **Step 1: 写 migration 失败测试**

测试从空 SQLite 执行 `upgrade head`，检查 Task 2 的八张表，并对以下表分别执行 UPDATE/DELETE，预期 `sqlite3.IntegrityError`：

```text
ai_prompt_template_versions
ai_model_config_versions
ai_research_cases
ai_evidence_refs
ai_model_attempts
ai_analysis_trace_events
ai_usage_ledger
```

`ai_analysis_runs` 只允许 service 定义的状态列转换；完成后 fingerprint/output/failure 字段不可再修改。

- [ ] **Step 2: 运行确认失败**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_provenance_migration.py -q`

Expected: FAIL，表或 revision 尚不存在。

- [ ] **Step 3: 实现 migration**

revision metadata 固定为：

```python
revision = "20260827_0014"
down_revision = "20260722_0013"
branch_labels = None
depends_on = None
```

`upgrade()` 创建与 ORM 一致的表、unique/check constraints 和命名 triggers；`downgrade()` 先删 triggers 再按依赖逆序删表。run status check 只接受 Task 1 的 `AIAnalysisRunStatus` 值。

- [ ] **Step 4: 验证 upgrade/downgrade/upgrade**

Run: `\.venv\Scripts\alembic.exe -c backend/alembic.ini upgrade head`

Run: `\.venv\Scripts\alembic.exe -c backend/alembic.ini downgrade 20260722_0013`

Run: `\.venv\Scripts\alembic.exe -c backend/alembic.ini upgrade head`

Expected: 三条命令 exit 0，head 为 `20260827_0014`。

- [ ] **Step 5: 运行 migration tests 并提交**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_provenance_migration.py -q`

Expected: PASS。

```powershell
git add backend/alembic/versions/20260827_0014_ai_provenance_foundation.py backend/tests/ai/test_provenance_migration.py
git commit -m "feat(ai): persist append-only provenance"
```

### Task 4: PromptTemplateVersion 与 ModelConfigVersion services

**Files:**
- Create: `backend/src/quant_lab/ai/repository.py`
- Create: `backend/src/quant_lab/ai/configuration.py`
- Test: `backend/tests/ai/test_configuration_service.py`

- [ ] **Step 1: 写发布与 secret 拒绝测试**

```python
def test_model_config_rejects_secret_fields(service) -> None:
    with pytest.raises(AIProvenanceError, match="AI_MODEL_CONFIG_SECRET_FORBIDDEN"):
        service.publish_model_config(
            provider_kind="FAKE",
            model_identifier="fake-v1",
            endpoint_profile_id="local-fake",
            parameters={"api_key": "should-never-persist"},
            actor="USER",
        )
```

另测相同 canonical content 幂等返回同一版本，不同 content 创建新不可变版本。

- [ ] **Step 2: 运行确认失败**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_configuration_service.py -q`

Expected: FAIL，service 尚不存在。

- [ ] **Step 3: 实现 repository 和 service**

`configuration.py` 定义 `AIProvenanceError`、`PromptTemplateVersionService`、`AIModelConfigVersionService`。禁止字段集合至少为：

```python
FORBIDDEN_SECRET_KEYS = frozenset(
    {"api_key", "apikey", "secret", "token", "authorization", "password", "credential"}
)
```

递归检查 nested dict/list。fingerprint payload 不含数据库 ID/created_at，包含全部行为参数。

- [ ] **Step 4: 运行测试和静态检查**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_configuration_service.py -q`

Run: `\.venv\Scripts\python.exe -m ruff check backend/src/quant_lab/ai backend/tests/ai`

Expected: PASS / All checks passed。

- [ ] **Step 5: 提交**

```powershell
git add backend/src/quant_lab/ai/repository.py backend/src/quant_lab/ai/configuration.py backend/tests/ai/test_configuration_service.py
git commit -m "feat(ai): publish prompt and model versions"
```

### Task 5: ResearchCase identity 与最小 EvidenceRef registry

**Files:**
- Create: `backend/src/quant_lab/ai/cases.py`
- Create: `backend/src/quant_lab/ai/evidence.py`
- Test: `backend/tests/ai/test_research_cases.py`
- Test: `backend/tests/ai/test_evidence_refs.py`

- [ ] **Step 1: 写 identity 与时间测试**

测试覆盖：

- `as_of_utc` 必须 timezone-aware 且归一化 UTC；
- `market_local_trade_date` 必须是 ISO date；
- bindings 至少含 market data/calendar/rules fingerprints；
- instrument_id/market/exchange/symbol/currency/asset_type 都进入 fingerprint；
- previous case/run 只作 lineage，不允许形成 cycle；
- 相同输入幂等，不同 cutoff 或 rule fingerprint 产生新 case。

`test_evidence_refs.py` 另测 EvidenceRef 必须属于一个 case，source/version/hash/locator/time/instrument 均进入 fingerprint，且 `known_at > case.as_of_utc` 时拒绝注册。

- [ ] **Step 2: 运行确认失败**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_research_cases.py backend/tests/ai/test_evidence_refs.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现输入 DTO 与 service**

核心 DTO：

```python
@dataclass(frozen=True, slots=True)
class ResearchCaseInput:
    purpose: str
    market: str
    exchange: str
    symbol: str
    instrument_id: str
    asset_type: str
    currency: str
    timeframe: str
    as_of_utc: datetime
    market_local_trade_date: date
    bindings: Mapping[str, object]
    previous_case_id: str | None = None
    previous_analysis_run_id: str | None = None
    thesis_revision_id: str | None = None
```

case service 只冻结 identity/provenance，不查询行情、不实现 EvidencePack。

`evidence.py` 只实现最小 provenance registry：接受 Core 已验证的 source metadata，创建不可变 EvidenceRef；不读取 Dataset/Backtest/PAPER，不截取正文，不做 EvidencePack assembly 或案例检索。核心输入：

```python
@dataclass(frozen=True, slots=True)
class EvidenceRefInput:
    evidence_type: str
    source_entity_type: str
    source_entity_id: str
    source_version_id: str
    content_sha256: str
    locator: Mapping[str, object]
    effective_at: datetime
    known_at: datetime
    captured_at: datetime
    market: str
    instrument_id: str
    currency: str
    temporal_status: str
    integrity_status: str
```

- [ ] **Step 4: 运行 tests 并提交**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_research_cases.py backend/tests/ai/test_evidence_refs.py -q`

Expected: PASS。

```powershell
git add backend/src/quant_lab/ai/cases.py backend/src/quant_lab/ai/evidence.py backend/tests/ai/test_research_cases.py backend/tests/ai/test_evidence_refs.py
git commit -m "feat(ai): freeze research case evidence identity"
```

### Task 6: AnalysisRun、Attempt、Trace 与 Usage service

**Files:**
- Create: `backend/src/quant_lab/ai/provenance.py`
- Test: `backend/tests/ai/test_provenance_service.py`

- [ ] **Step 1: 写状态与 append-only 失败测试**

测试合法状态：

```text
CREATED -> RUNNING -> COMPLETED
CREATED -> CANCELLED
RUNNING -> FAILED/CANCELLED/REJECTED
```

终态不能再变化。Attempt number、Trace sequence 必须从 1 单调递增；同一 run 重复 number/sequence 冲突。Usage 必须引用已存在 attempt，token 非负且 `total_tokens` 与 components 一致或明确 provider-reported override。

- [ ] **Step 2: 运行确认失败**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_provenance_service.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现 provenance service**

公开方法固定为：

```python
create_run(...)
start_run(run_id, input_envelope_fingerprint)
start_attempt(run_id, input_fingerprint)
complete_attempt(attempt_id, provider_request_id, output_fingerprint, latency_ms, finish_reason)
fail_attempt(attempt_id, failure_code)
append_trace(run_id, event_type, payload)
append_usage(attempt_id, usage)
complete_run(run_id, raw_response_artifact_sha256, normalized_output_fingerprint)
fail_run(run_id, failure_code, safe_failure_message)
cancel_run(run_id)
recover_incomplete_runs(now_utc)
```

`recover_incomplete_runs` 将重启前 `STARTED` attempt 标记 `ABANDONED`、run 标记 `FAILED`，追加 trace；不重试、不调用 provider。

- [ ] **Step 4: 运行测试和提交**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_provenance_service.py -q`

Expected: PASS。

```powershell
git add backend/src/quant_lab/ai/provenance.py backend/tests/ai/test_provenance_service.py
git commit -m "feat(ai): record analysis provenance lifecycle"
```

### Task 7: FastAPI DTO 与 provenance APIs

**Files:**
- Create: `backend/src/quant_lab/api/ai_research.py`
- Create: `backend/src/quant_lab/api/ai_research_schemas.py`
- Modify: `backend/src/quant_lab/main.py`
- Test: `backend/tests/ai/test_ai_research_api.py`

- [ ] **Step 1: 写 API 失败测试**

覆盖：

```text
POST /api/v1/research-cases
GET  /api/v1/research-cases/{case_id}
POST /api/v1/ai-analysis-runs
GET  /api/v1/ai-analysis-runs/{run_id}
GET  /api/v1/ai-analysis-runs/{run_id}/trace
GET  /api/v1/ai-analysis-runs/{run_id}/usage
```

API 不提供 create attempt/complete run 等低层 provider 操作给前端，不返回 Prompt content、raw response、secret_ref 或内部 exception。

- [ ] **Step 2: 运行确认失败**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_ai_research_api.py -q`

Expected: FAIL/404。

- [ ] **Step 3: 实现严格 Pydantic DTO 与 routes**

Request 使用 `ConfigDict(extra="forbid")`。Response 至少返回 ID、status、fingerprints、safe failure、timestamps 和 lineage。error contract 延续现有：

```json
{"error_code": "AI_CASE_NOT_FOUND", "message": "研究案例不存在"}
```

`main.py` 只装配 repository/service/router，不装载 SDK/secret/provider，也不让 AI service 成为 health readiness 的 required component。

- [ ] **Step 4: 运行 API tests、mypy 并提交**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_ai_research_api.py -q`

Run: `\.venv\Scripts\python.exe -m mypy backend/src`

Expected: PASS / Success: no issues found。

```powershell
git add backend/src/quant_lab/api/ai_research.py backend/src/quant_lab/api/ai_research_schemas.py backend/src/quant_lab/main.py backend/tests/ai/test_ai_research_api.py
git commit -m "feat(ai): expose provenance foundation api"
```

### Task 8: Non-interference 与 dependency boundary tests

**Files:**
- Create: `backend/tests/ai/test_ai_execution_boundary.py`
- Modify: `backend/tests/test_health.py`

- [ ] **Step 1: 写 forbidden import test**

AST 扫描 `backend/src/quant_lab/ai`，拒绝这些 import 前缀：

```python
FORBIDDEN = (
    "quant_lab.paper.service",
    "quant_lab.paper.repository",
    "quant_lab.live",
    "quant_lab.execution_gateway",
    "quant_lab.brokers",
)
```

允许导入纯 `quant_lab.execution`/market domain DTO 只应在未来设计明确后加入；AI-1 不需要。

- [ ] **Step 2: 写 readiness non-interference test**

构造 AI repository 初始化失败/不可用情形，断言现有 health、dataset、backtest、paper route 的装配和 readiness 仍按既有 required components 工作；AI 状态只能作为 optional detail。

- [ ] **Step 3: 运行确认边界**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_ai_execution_boundary.py backend/tests/test_health.py -q`

Expected: PASS。

- [ ] **Step 4: 提交**

```powershell
git add backend/tests/ai/test_ai_execution_boundary.py backend/tests/test_health.py
git commit -m "test(ai): enforce execution isolation"
```

### Task 9: 文档、OpenAPI 与全量验收

**Files:**
- Modify: `ARCHITECTURE.md`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-27-ai-research-copilot-architecture.md`
- Test: `scripts/test.ps1`

- [ ] **Step 1: 更新实现状态但不超报**

README 只增加“AI provenance foundation（尚无模型分析）”；ARCHITECTURE 增加 AI module、八张表、optional health 和 forbidden execution dependencies。Spec 的 AI-1 标记为 implemented only after tests pass；AI-2～AI-8 保持 planned。

- [ ] **Step 2: 检查 OpenAPI**

Run: `\.venv\Scripts\python.exe -c "from quant_lab.main import create_app; app=create_app(); paths=app.openapi()['paths']; assert '/api/v1/research-cases' in paths; assert not any('order' in p.lower() and 'ai' in p.lower() for p in paths)"`

Expected: exit 0。

- [ ] **Step 3: 运行完整质量门禁**

Run: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1`

Expected:

- backend pytest 0 failures；
- Ruff exit 0；
- mypy exit 0；
- frontend Vitest 0 failures；
- TypeScript/Vite build exit 0。

- [ ] **Step 4: 检查 migration head 与 diff**

Run: `\.venv\Scripts\alembic.exe -c backend/alembic.ini heads`

Expected: 仅一个 head，为本任务执行时确认的 AI-1 revision。

Run: `git diff --check`

Expected: 无输出，exit 0。

- [ ] **Step 5: 最终提交**

```powershell
git add README.md ARCHITECTURE.md docs/superpowers/specs/2026-08-27-ai-research-copilot-architecture.md
git commit -m "docs: record ai provenance foundation"
```

## AI-1 完成判定

仅当以下全部成立才可进入 AI-2：

- 只有一个 Alembic head；
- provenance tables 与 ORM 一致；
- EvidenceRef 只是最小 provenance registry，尚未实现 EvidencePack/retrieval；
- append-only triggers 经 UPDATE/DELETE 反向测试；
- canonical fingerprints、状态机、restart recovery 和 safe errors 有测试；
- 数据库、API、trace、日志均不含 secret；
- AI package 无 PAPER/LIVE/Gateway/Broker 写依赖；
- AI unavailable 不影响既有 readiness；
- 没有 provider SDK、Provider Host 或真实模型调用；
- `scripts/test.ps1` 全量通过。
