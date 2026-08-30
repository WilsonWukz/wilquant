# AI-2 Evidence, Grounding & Temporal Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不引入 Provider、SDK、chat、UI 或交易写操作的前提下，实现可审计 EvidencePack、六层确定性校验、ResearchGate 与 temporal-safe FTS5 案例检索。

**Architecture:** Core 通过显式 resolver registry 把 allowlisted 领域对象冻结为 canonical evidence，所有时间、市场和来源身份都进入 fingerprint。四张 append-only 历史表保存 pack、validation、case document 与 retrieval snapshot；FTS5 只作为可从 case document 重建的 derived index，业务排名不保存 SQLite 内部 score。

**Tech Stack:** Python 3.12、Pydantic v2、SQLAlchemy 2、Alembic、SQLite/FTS5、FastAPI、pytest、Ruff、mypy、PowerShell。

---

## 文件职责图

- `backend/src/quant_lab/ai/contracts.py`：AI-2 枚举、时间/证据/claim/finding/gate/retrieval DTO。
- `backend/src/quant_lab/ai/policies.py`：不可由调用方覆盖的版本、限额、单位、容差、排序权重与 reason precedence。
- `backend/src/quant_lab/ai/resolvers.py`：resolver protocol、registry、字段 allowlist 与 canonical item builder。
- `backend/src/quant_lab/ai/source_resolvers.py`：11 种已批准 source 的显式 resolver；不提供反射或任意查询。
- `backend/src/quant_lab/ai/packs.py`：EvidencePack 单次冻结、完整校验、security scan 与 fingerprint。
- `backend/src/quant_lab/ai/validation.py`：六层 pipeline、derived recompute、immutable assertion identity、untrusted observation。
- `backend/src/quant_lab/ai/gates.py`：固定优先级 ResearchGate。
- `backend/src/quant_lab/ai/retrieval.py`：canonical case document、hard filters、structured/lexical 业务分与 snapshot。
- `backend/src/quant_lab/ai/persistence.py`、`repository.py`：四张历史表、FTS transaction/rebuild 与只读恢复。
- `backend/alembic/versions/20260830_0015_ai_evidence_temporal_validation.py`：线性接在 `20260827_0014` 后的 schema、FTS、trigger。
- `backend/src/quant_lab/api/ai_research.py`：新增三个只读 provenance GET API。
- `backend/src/quant_lab/main.py`：启动时检查/rebuild derived FTS，不调用任何 Provider。
- `backend/tests/ai/test_ai2_*.py`：contracts、resolver、pack、validation、gate、retrieval、API、recovery、边界攻击测试。

### Task 1: 固定 AI-2 contract 与不可覆盖 policy

**Files:**
- Create: `backend/src/quant_lab/ai/contracts.py`
- Create: `backend/src/quant_lab/ai/policies.py`
- Test: `backend/tests/ai/test_ai2_contracts.py`

- [ ] **Step 1: 写 RED contract tests**

```python
def test_temporal_context_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        TemporalContext(
            market_data_cutoff=datetime(2024, 1, 1),
            knowledge_cutoff=datetime(2024, 1, 2),
            market="CN_A_SHARE",
            timezone="Asia/Shanghai",
            asset_type="EQUITY",
            analysis_mode="HISTORICAL_REPLAY",
        )

def test_market_rules_are_nullable_for_rule_independent_analysis() -> None:
    context = EvidenceContext(
        market="CN_A_SHARE", instrument_id="SSE:600000", asset_type="EQUITY",
        timezone="Asia/Shanghai", market_rules_version=None,
    )
    assert context.market_rules_version is None
```

- [ ] **Step 2: 运行 RED**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/ai/test_ai2_contracts.py -q`

Expected: FAIL，因为 `contracts` 与 `policies` 尚不存在。

- [ ] **Step 3: 实现最小稳定 contract**

```python
class TemporalContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    market_data_cutoff: datetime
    knowledge_cutoff: datetime
    market: Literal["CN_A_SHARE", "US_EQUITY"]
    timezone: str
    asset_type: Literal["EQUITY", "ETF"]
    analysis_mode: Literal["CURRENT_RESEARCH", "HISTORICAL_REPLAY"]

    @field_validator("market_data_cutoff", "knowledge_cutoff")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        return value.astimezone(UTC)
```

同时定义 frozen `EvidenceContext`、`AnalysisRequirements`、`CanonicalEvidenceItem`、`EvidencePack`、`StructuredClaim`、`ValidationFinding`、`ValidationResult`、`GateResult`、`RetrievalQuery`、`RetrievalCandidate` 与受控枚举。`policies.py` 固定 `ai-evidence-v1`、`ai-validation-v1`、`ai-retrieval-v1`、128 items、262144 bytes、20 cases、Decimal 容差和 integer ranking weights。

- [ ] **Step 4: 运行 GREEN 与静态检查**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/ai/test_ai2_contracts.py -q`

Expected: PASS；naive datetime、未知枚举、客户端权重覆盖均被拒绝。

### Task 2: 建立 append-only schema、repository 与 migration matrix

**Files:**
- Modify: `backend/src/quant_lab/ai/persistence.py`
- Modify: `backend/src/quant_lab/ai/repository.py`
- Create: `backend/alembic/versions/20260830_0015_ai_evidence_temporal_validation.py`
- Create: `backend/tests/ai/test_ai2_migration.py`
- Create: `backend/tests/ai/test_ai2_repository.py`
- Modify: `backend/tests/datasets/test_migration.py`
- Modify: `backend/tests/paper/test_migration.py`
- Modify: `backend/tests/test_sqlite_bootstrap.py`

- [ ] **Step 1: 写 RED migration/repository tests**

```python
EXPECTED = {
    "ai_evidence_packs", "ai_validation_results",
    "ai_research_case_documents", "ai_retrieval_snapshots",
    "ai_research_case_fts",
}

def test_ai2_migration_creates_history_and_derived_index(migrated_engine: Engine) -> None:
    names = set(inspect(migrated_engine).get_table_names())
    with migrated_engine.connect() as connection:
        fts = connection.scalar(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_research_case_fts'"
        ))
    assert EXPECTED - {"ai_research_case_fts"} <= names
    assert fts == "ai_research_case_fts"
```

另测四张普通表 UPDATE/DELETE 失败、FTS 可 DELETE/rebuild、`down_revision == "20260827_0014"`、upgrade/downgrade/upgrade matrix 和 pack/document+FTS 事务原子性。

- [ ] **Step 2: 运行 RED**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/ai/test_ai2_migration.py backend/tests/ai/test_ai2_repository.py -q`

Expected: FAIL，缺少 revision、models 与 repository methods。

- [ ] **Step 3: 实现 schema 与 repository**

```python
class AIEvidencePackModel(Base):
    __tablename__ = "ai_evidence_packs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("ai_research_cases.id", ondelete="RESTRICT"))
    temporal_context_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_context_json: Mapped[str] = mapped_column(Text, nullable=False)
    items_json: Mapped[str] = mapped_column(Text, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

其余三表保存规范设计中的 identity/fingerprint/policy/result JSON。migration 只给四张普通表创建 append-only trigger；FTS virtual table无历史 trigger。repository 暴露显式 add/get/list 和 `rebuild_research_case_fts()`，后者只从 `ai_research_case_documents` 重建。

- [ ] **Step 4: 运行 GREEN 与 matrix**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/ai/test_ai2_migration.py backend/tests/ai/test_ai2_repository.py backend/tests/datasets/test_migration.py backend/tests/paper/test_migration.py backend/tests/test_sqlite_bootstrap.py -q`

Expected: PASS；revision 唯一且线性，历史表不可改，derived FTS 可重建。

### Task 3: 实现显式 resolver registry 与 11 个 source resolver

**Files:**
- Create: `backend/src/quant_lab/ai/resolvers.py`
- Create: `backend/src/quant_lab/ai/source_resolvers.py`
- Create: `backend/tests/ai/test_ai2_resolvers.py`
- Create: `backend/tests/ai/test_ai2_source_resolvers.py`

- [ ] **Step 1: 写 registry、allowlist 与真实对象 RED tests**

```python
def test_registry_rejects_unregistered_or_arbitrary_fields() -> None:
    registry = EvidenceResolverRegistry()
    with pytest.raises(UnsupportedEvidenceSource):
        registry.resolve(EvidenceRequest(source_type="RESEARCH_JOURNAL", source_id="x"))
    with pytest.raises(DisallowedEvidenceField):
        registry.resolve(EvidenceRequest(
            source_type="DATASET_VERSION", source_id="v1", fields=("database_url",)
        ))

def test_experiment_hypothesis_is_user_note(experiment_resolver) -> None:
    item = experiment_resolver.resolve("exp-1")
    assert item.fields["hypothesis"].classification == "USER_NOTE"
```

逐一覆盖 11 个 SUPPORTED source，并断言 mutable MarketDataProfile、ResearchJournal、MarketRules、US realtime source 均拒绝。

- [ ] **Step 2: 运行 RED**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/ai/test_ai2_resolvers.py backend/tests/ai/test_ai2_source_resolvers.py -q`

Expected: FAIL，resolver modules 尚不存在。

- [ ] **Step 3: 实现无反射 registry 与 source adapters**

```python
class EvidenceResolverRegistry:
    def __init__(self, resolvers: Iterable[EvidenceResolver] = ()) -> None:
        self._resolvers = {resolver.source_type: resolver for resolver in resolvers}

    def resolve(self, request: EvidenceRequest) -> CanonicalEvidenceItem:
        resolver = self._resolvers.get(request.source_type)
        if resolver is None:
            raise UnsupportedEvidenceSource(request.source_type)
        if not set(request.fields) <= resolver.allowed_fields:
            raise DisallowedEvidenceField(request.source_type)
        return resolver.resolve(request)
```

每个 resolver 使用构造注入的正式 repository/service 和固定 projector；不接收 table、model class、column、SQL、path 或 callable。缺少 market/time/integrity metadata 时显式返回 finding-ready 状态，不猜测 symbol、currency 或时间。

- [ ] **Step 4: 运行 GREEN**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/ai/test_ai2_resolvers.py backend/tests/ai/test_ai2_source_resolvers.py -q`

Expected: PASS；SUPPORTED 全覆盖，DEFERRED 全 fail closed。

### Task 4: 冻结 EvidencePack 并实现时间/完整性门控

**Files:**
- Create: `backend/src/quant_lab/ai/packs.py`
- Create: `backend/src/quant_lab/ai/gates.py`
- Create: `backend/tests/ai/test_ai2_evidence_packs.py`
- Create: `backend/tests/ai/test_ai2_research_gate.py`

- [ ] **Step 1: 写 RED pack/gate tests**

```python
def test_pack_fingerprint_excludes_server_created_at(pack_factory) -> None:
    first = pack_factory(created_at=aware("2026-08-30T00:00:00Z"))
    second = pack_factory(created_at=aware("2026-08-30T01:00:00Z"))
    assert first.fingerprint == second.fingerprint

@pytest.mark.parametrize("signals, expected", [
    ({"deterministic_violation": True, "missing": True}, "REJECT"),
    ({"missing": True, "unanswerable": True}, "WAIT_FOR_EVIDENCE"),
    ({"unanswerable": True}, "ABSTAIN"),
    ({}, "PROCEED"),
])
def test_gate_precedence(signals, expected):
    assert ResearchGate().decide(**signals).decision == expected
```

另测 future effective/known time、stale evidence、market/asset mismatch、oversize、secret marker、missing rules conditional behavior 与 pack failure 无残留行。

- [ ] **Step 2: 运行 RED**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/ai/test_ai2_evidence_packs.py backend/tests/ai/test_ai2_research_gate.py -q`

Expected: FAIL，service 尚不存在。

- [ ] **Step 3: 实现 pack 与固定 gate**

```python
PRECEDENCE = ("REJECT", "WAIT_FOR_EVIDENCE", "ABSTAIN", "PROCEED")

def decide(findings: Sequence[ValidationFinding]) -> GateResult:
    codes = {finding.code for finding in findings}
    if codes & DETERMINISTIC_VIOLATIONS:
        return GateResult(decision="REJECT", reason_codes=ordered_codes(codes))
    if codes & MISSING_OR_STALE:
        return GateResult(decision="WAIT_FOR_EVIDENCE", reason_codes=ordered_codes(codes))
    if codes & UNANSWERABLE:
        return GateResult(decision="ABSTAIN", reason_codes=ordered_codes(codes))
    return GateResult(decision="PROCEED", reason_codes=("PROCEED",))
```

EvidencePackService 必须先解析、排序、限额、secret scan、完整性与 temporal precheck，再在一次 repository call 中写入。仅当 `requires_market_rules=true` 或 topics 非空时，空 rules version 产生 `MISSING_MARKET_RULES`。

- [ ] **Step 4: 运行 GREEN**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/ai/test_ai2_evidence_packs.py backend/tests/ai/test_ai2_research_gate.py -q`

Expected: PASS。

### Task 5: 实现六层 validation 与 adversarial immutable drift

**Files:**
- Create: `backend/src/quant_lab/ai/validation.py`
- Create: `backend/tests/ai/test_ai2_validation.py`
- Create: `backend/tests/ai/test_ai2_adversarial_validation.py`

- [ ] **Step 1: 写 RED pipeline 与攻击测试**

```python
def test_percent_change_is_recomputed_from_ordered_operands(validator, pack) -> None:
    claim = claim_of("PERCENT_CHANGE", value="0.20", refs=("new", "old"))
    result = validator.validate(candidate(claim), pack)
    assert result.accepted
    assert result.accepted_claims[0].value == Decimal("0.20")

def test_claim_id_alias_unit_and_ref_order_cannot_hide_drift(validator, prior) -> None:
    mutated = claim_of(
        "FACT", claim_id="new-id", subject="subject alias", unit="percent",
        refs=tuple(reversed(prior.evidence_refs)), value="99",
    )
    result = validator.validate(candidate(mutated), pack_for(prior), prior=(prior,))
    assert "IMMUTABLE_FACT_DRIFT" in result.error_codes
```

另测 syntax/schema/semantic/grounding/temporal/immutable 层序、fabricated ref、USER_NOTE 支持 FACT、DELTA/PERCENT_CHANGE operand swap/zero denominator、容差边界、forbidden authority、prompt injection、schema-invalid observation 仅 `trusted=false` 且永不 accepted。

- [ ] **Step 2: 运行 RED**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/ai/test_ai2_validation.py backend/tests/ai/test_ai2_adversarial_validation.py -q`

Expected: FAIL，validation service 尚不存在。

- [ ] **Step 3: 实现 pipeline 与 canonical assertion identity**

```python
def assertion_identity(claim: StructuredClaim, pack: EvidencePack) -> str:
    payload = {
        "claim_type": claim.claim_type,
        "subject": canonical_subject(claim.subject, pack),
        "predicate": claim.predicate,
        "evidence_refs": normalized_direct_refs(claim),
        "unit": canonical_unit(claim.unit),
        "derived_operation": claim.derived_operation,
        "operand_refs": ordered_operand_refs(claim),
    }
    return sha256_canonical(payload)
```

`claim_id` 永不进入 identity。schema 失败时只从安全可识别字段生成 `AssertionObservation(origin_attempt_id=..., trusted=False)`；它只进入当前 run 的 validation provenance，不进入 accepted claims、EvidencePack、ResearchCaseDocument 或 resolver registry。任一层 ERROR 后保持 rejected，Grounding 成功不能覆盖 Schema ERROR。

- [ ] **Step 4: 运行 GREEN**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/ai/test_ai2_validation.py backend/tests/ai/test_ai2_adversarial_validation.py -q`

Expected: PASS；所有绕过尝试得到稳定 error code。

### Task 6: 实现 durable case document、derived FTS 与稳定 retrieval

**Files:**
- Create: `backend/src/quant_lab/ai/retrieval.py`
- Create: `backend/tests/ai/test_ai2_retrieval.py`
- Create: `backend/tests/ai/test_ai2_fts_recovery.py`

- [ ] **Step 1: 写 RED temporal/ranking/rebuild tests**

```python
def test_case_created_later_cannot_enter_historical_context(service, case_2023_created_2026):
    result = service.retrieve(query(knowledge_cutoff=aware("2024-12-31T23:59:59Z")))
    assert case_2023_created_2026.id not in result.included_case_ids

def test_fts_rebuild_preserves_business_ranking_and_old_snapshot(service, repository):
    before = service.retrieve(query(text="mean reversion"))
    frozen = repository.get_retrieval_snapshot(before.id)
    repository.rebuild_research_case_fts()
    after = service.retrieve(query(text="mean reversion"))
    assert business_rows(before) == business_rows(after)
    assert repository.get_retrieval_snapshot(before.id).fingerprint == frozen.fingerprint
```

另测 CN/US 严格隔离、market/asset/cutoff/universe filters、rules conditional compatibility、strategy family 只加高权重分、query sanitization、stable tie-break、20-case bound、无 cross_market/embedding 字段。

- [ ] **Step 2: 运行 RED**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/ai/test_ai2_retrieval.py backend/tests/ai/test_ai2_fts_recovery.py -q`

Expected: FAIL，retrieval service 尚不存在。

- [ ] **Step 3: 实现稳定业务 ranking**

```python
def business_lexical_score(query_tokens: tuple[str, ...], document: str) -> int:
    normalized = normalize_search_text(document)
    return min(sum(normalized.count(token) for token in query_tokens), 20)

def rank_key(candidate: RetrievalCandidate) -> tuple[int, float, str]:
    return (-candidate.final_score, -candidate.case_end_at.timestamp(), candidate.case_id)
```

FTS 只产生与 query 匹配的 candidate identity；最终 lexical component 从 canonical document 做稳定 normalization/quantization，不保存 rowid/bm25。Snapshot 保存 query/policy、case_id、document_id、document_fingerprint、结构分、lexical 整数分、final score、rank 和排除原因。

- [ ] **Step 4: 运行 GREEN**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/ai/test_ai2_retrieval.py backend/tests/ai/test_ai2_fts_recovery.py -q`

Expected: PASS；重建前后排名相同，旧 snapshot 不变。

### Task 7: 接入只读 API、启动恢复与 compile-time boundary

**Files:**
- Modify: `backend/src/quant_lab/api/ai_research.py`
- Modify: `backend/src/quant_lab/api/schemas.py`
- Modify: `backend/src/quant_lab/main.py`
- Create: `backend/tests/ai/test_ai2_api.py`
- Create: `backend/tests/ai/test_ai2_execution_boundary.py`
- Modify: `backend/tests/ai/test_ai_execution_boundary.py`

- [ ] **Step 1: 写 RED API/restart/boundary tests**

```python
@pytest.mark.parametrize("path", [
    "/api/v1/ai/evidence-packs/{id}",
    "/api/v1/ai/validation-results/{id}",
    "/api/v1/ai/retrieval-snapshots/{id}",
])
def test_ai2_provenance_endpoints_are_get_only(client, path, seeded_ids):
    resolved = path.format(id=seeded_ids[path])
    assert client.get(resolved).status_code == 200
    assert client.post(resolved, json={}).status_code == 405

def test_ai2_import_graph_has_no_provider_sdk_or_trading_write() -> None:
    assert forbidden_ai2_imports() == set()
```

另测 404、response 不泄漏 secret/raw internal payload、启动时 FTS 缺失/漂移可幂等重建、普通表不被 recovery 修改、非 AI health 不依赖 AI-2。

- [ ] **Step 2: 运行 RED**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/ai/test_ai2_api.py backend/tests/ai/test_ai2_execution_boundary.py -q`

Expected: FAIL，API schemas/routes/recovery 尚未接入。

- [ ] **Step 3: 实现只读接线**

```python
@router.get("/ai/evidence-packs/{pack_id}", response_model=AIEvidencePackResponse)
def get_evidence_pack(pack_id: str, request: Request) -> AIEvidencePackResponse:
    model = request.app.state.ai_repository.get_evidence_pack(pack_id)
    if model is None:
        raise HTTPException(status_code=404, detail="evidence pack not found")
    return AIEvidencePackResponse.from_model(model)
```

另外两个 route 使用同一显式 model-to-response 映射。startup 仅检查 FTS 是否能由 canonical documents 完整重建；不得初始化 Provider、读取 AI key 或触碰 PAPER/LIVE repository 写方法。

- [ ] **Step 4: 运行 GREEN**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/ai -q`

Expected: AI shard 全绿。

### Task 8: 文档同步、完整验证与最多三提交闭环

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/superpowers/specs/2026-08-27-ai-research-copilot-architecture.md`
- Modify: `docs/superpowers/specs/2026-08-30-ai-2-evidence-temporal-validation-design.md`
- Modify: `scripts/test.ps1`（仅在 shard coverage 或显式 AI-2 gate 需要时）

- [ ] **Step 1: 更新阶段状态和 migration head**

把状态从 `approved for implementation` 改为 `implemented / stable`，记录 migration `20260830_0015`、FTS derived/rebuild contract、只读 API、支持/延后边界和 `AI-2 EVIDENCE & TEMPORAL VALIDATION STABLE`；不得宣称 AI-3 能力。

- [ ] **Step 2: 运行 targeted quality gates**

Run: `backend/.venv/Scripts/python.exe -m ruff check backend/src backend/tests backend/alembic`

Run: `backend/.venv/Scripts/python.exe -m mypy backend/src`

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/ai -q`

Expected: 全部 exit 0。

- [ ] **Step 3: 运行仓库唯一完整验收入口**

Run: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1`

Expected: `All backend and frontend checks passed.`，覆盖全部 backend shards、Ruff、mypy、frontend tests/build。

- [ ] **Step 4: 完成 hygiene 与边界扫描**

Run: `git diff --check`

Run: `rg -n "T[O]DO|T[B]D|place[h]older|OPENAI_API_KEY|ANTHROPIC_API_KEY|client\.chat|responses\.create|embedding|cross_market" backend/src/quant_lab/ai backend/tests/ai docs/superpowers/specs/2026-08-30-ai-2-evidence-temporal-validation-design.md`

Expected: 无占位、secret、Provider call、embedding/cross-market implementation；文档中的 deferred 文字允许存在。

- [ ] **Step 5: 创建剩余两个逻辑提交并停止**

```text
feat(ai): implement evidence and deterministic validation
feat(ai): add temporal-safe case retrieval
```

总提交数不超过 3；不 push、不建分支、不 worktree、不 merge/rebase/reset、不改历史。最终报告按需求 A-Q 输出，并明确没有进入 AI-3。
