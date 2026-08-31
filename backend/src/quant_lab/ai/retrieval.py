from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from quant_lab.ai.cases import stored_utc
from quant_lab.ai.configuration import contains_forbidden_secret_material
from quant_lab.ai.contracts import (
    RetrievalCandidate,
    RetrievalQuery,
    RetrievalSnapshot,
)
from quant_lab.ai.fingerprints import fingerprint_payload
from quant_lab.ai.persistence import (
    AIResearchCaseDocumentModel,
    AIResearchCaseModel,
    AIRetrievalSnapshotModel,
)
from quant_lab.ai.policies import AI2_POLICY, AI2Policy
from quant_lab.ai.repository import AIRepository
from quant_lab.market_data.fingerprints import canonical_json_bytes

_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z_\u3400-\u4dbf\u4e00-\u9fff]+")


class ResearchCaseDocumentError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _json_text(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFC", value).casefold()
    return tuple(sorted(set(_TOKEN_PATTERN.findall(normalized))))


def _fts_query(tokens: Sequence[str]) -> str:
    return " OR ".join(f'"{token}"' for token in tokens)


def _document_text(model: AIResearchCaseDocumentModel) -> str:
    values = [
        model.title,
        model.summary,
        model.diagnosis,
        *json.loads(model.success_factors_json),
        *json.loads(model.failure_factors_json),
        *json.loads(model.regime_labels_json),
        *json.loads(model.safe_tags_json),
    ]
    return unicodedata.normalize("NFC", " ".join(str(value) for value in values)).casefold()


def _snapshot_from_model(model: AIRetrievalSnapshotModel) -> RetrievalSnapshot:
    return RetrievalSnapshot(
        id=model.id,
        query=json.loads(model.query_json),
        policy_version=model.policy_version,
        candidates=tuple(json.loads(model.candidates_json)),
        exclusions=tuple(json.loads(model.exclusions_json)),
        fingerprint=model.fingerprint,
        created_at=_utc(model.created_at),
    )


class ResearchCaseDocumentService:
    def __init__(
        self,
        repository: AIRepository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.clock = clock

    def create(
        self,
        *,
        case_id: str,
        title: str,
        summary: str,
        diagnosis: str,
        success_factors: Sequence[str],
        failure_factors: Sequence[str],
        regime_labels: Sequence[str],
        safe_tags: Sequence[str],
        universe: Sequence[str],
        strategy_family: str | None,
        market_rules_version: str | None,
    ) -> AIResearchCaseDocumentModel:
        case = self.repository.get_research_case(case_id)
        if case is None:
            raise ResearchCaseDocumentError("AI_CASE_NOT_FOUND", "research case not found")
        existing = self.repository.get_research_case_document_by_case_id(case_id)
        canonical = {
            "case_id": case_id,
            "case_fingerprint": case.fingerprint,
            "title": title.strip(),
            "summary": summary.strip(),
            "diagnosis": diagnosis.strip(),
            "success_factors": sorted(set(success_factors)),
            "failure_factors": sorted(set(failure_factors)),
            "regime_labels": sorted(set(regime_labels)),
            "safe_tags": sorted(set(safe_tags)),
            "universe": sorted(set(universe)),
            "strategy_family": strategy_family,
            "market_rules_version": market_rules_version,
        }
        if not canonical["title"] or len(str(canonical["title"])) > 200:
            raise ResearchCaseDocumentError("DOCUMENT_TITLE_INVALID", "invalid document title")
        if len(str(canonical["summary"])) > 8_000 or len(str(canonical["diagnosis"])) > 8_000:
            raise ResearchCaseDocumentError("DOCUMENT_TOO_LARGE", "case document is too large")
        if any(
            len(values) > 64
            for values in (
                success_factors,
                failure_factors,
                regime_labels,
                safe_tags,
                universe,
            )
        ):
            raise ResearchCaseDocumentError("DOCUMENT_TOO_LARGE", "case document is too large")
        if contains_forbidden_secret_material(canonical):
            raise ResearchCaseDocumentError(
                "SECRET_MATERIAL_FORBIDDEN", "case document contains forbidden material"
            )
        fingerprint = fingerprint_payload(canonical)
        if existing is not None:
            if existing.document_fingerprint == fingerprint:
                return existing
            raise ResearchCaseDocumentError(
                "CASE_DOCUMENT_ALREADY_EXISTS", "research case already has a document"
            )
        return self.repository.add_research_case_document(
            AIResearchCaseDocumentModel(
                id=str(uuid4()),
                case_id=case_id,
                title=str(canonical["title"]),
                summary=str(canonical["summary"]),
                diagnosis=str(canonical["diagnosis"]),
                success_factors_json=_json_text(canonical["success_factors"]),
                failure_factors_json=_json_text(canonical["failure_factors"]),
                regime_labels_json=_json_text(canonical["regime_labels"]),
                safe_tags_json=_json_text(canonical["safe_tags"]),
                universe_json=_json_text(canonical["universe"]),
                strategy_family=strategy_family,
                market_rules_version=market_rules_version,
                document_fingerprint=fingerprint,
                created_at=self.clock().astimezone(UTC),
            )
        )


class ResearchCaseRetrievalService:
    def __init__(
        self,
        repository: AIRepository,
        *,
        policy: AI2Policy = AI2_POLICY,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.policy = policy
        self.clock = clock

    def _structured_score(
        self,
        query: RetrievalQuery,
        document: AIResearchCaseDocumentModel,
    ) -> int:
        score = 0
        regimes = set(json.loads(document.regime_labels_json))
        tags = set(json.loads(document.safe_tags_json))
        universe = set(json.loads(document.universe_json))
        if query.strategy_family and document.strategy_family == query.strategy_family:
            score += self.policy.strategy_family_weight
        score += len(regimes & set(query.regime_labels)) * self.policy.regime_label_weight
        score += len(universe & set(query.universe)) * self.policy.universe_weight
        score += len(tags & set(query.safe_tags)) * self.policy.safe_tag_weight
        return score

    def retrieve(self, query: RetrievalQuery) -> RetrievalSnapshot:
        rows = self.repository.list_research_case_documents_with_cases()
        eligible: list[tuple[AIResearchCaseDocumentModel, AIResearchCaseModel]] = []
        exclusions: list[dict[str, str]] = []
        for document, case in rows:
            reason: str | None = None
            case_end_at = stored_utc(case.as_of_utc)
            known_at = stored_utc(case.created_at)
            if case.market != query.market:
                reason = "MARKET_MISMATCH"
            elif case.asset_type != query.asset_type:
                reason = "ASSET_TYPE_MISMATCH"
            elif case_end_at > query.market_data_cutoff:
                reason = "MARKET_DATA_CUTOFF"
            elif known_at > query.knowledge_cutoff:
                reason = "KNOWLEDGE_CUTOFF"
            elif query.universe and not (
                set(query.universe) & set(json.loads(document.universe_json))
            ):
                reason = "UNIVERSE_MISMATCH"
            elif query.requires_market_rules and (
                query.market_rules_version is None
                or document.market_rules_version != query.market_rules_version
            ):
                reason = "MARKET_RULES_MISMATCH"
            if reason is not None:
                exclusions.append({"case_id": case.id, "reason": reason})
            else:
                eligible.append((document, case))

        query_tokens = _tokens(query.query_text)
        fts_matches = (
            set(self.repository.search_research_case_fts(_fts_query(query_tokens)))
            if query_tokens
            else {document.id for document, _case in eligible}
        )
        scored: list[
            tuple[AIResearchCaseDocumentModel, AIResearchCaseModel, int, int, int]
        ] = []
        for document, case in eligible:
            structured = self._structured_score(query, document)
            lexical = 0
            if document.id in fts_matches:
                text = _document_text(document)
                lexical = min(
                    sum(text.count(token) for token in query_tokens),
                    self.policy.max_lexical_bucket,
                )
            final = structured + lexical * self.policy.lexical_weight
            scored.append((document, case, structured, lexical, final))
        scored.sort(
            key=lambda row: (
                -row[4],
                -stored_utc(row[1].as_of_utc).timestamp(),
                row[1].id,
            )
        )
        candidates = tuple(
            RetrievalCandidate(
                case_id=case.id,
                document_id=document.id,
                document_fingerprint=document.document_fingerprint,
                case_end_at=stored_utc(case.as_of_utc),
                known_at=stored_utc(case.created_at),
                structured_score=structured,
                lexical_score=lexical,
                final_score=final,
                rank=index,
            )
            for index, (document, case, structured, lexical, final) in enumerate(
                scored[: min(query.limit, self.policy.max_retrieval_cases)], start=1
            )
        )
        exclusions_tuple = tuple(sorted(exclusions, key=lambda item: item["case_id"]))
        payload = {
            "query": query.model_dump(mode="python"),
            "policy_version": self.policy.retrieval_policy_version,
            "candidates": [item.model_dump(mode="python") for item in candidates],
            "exclusions": list(exclusions_tuple),
        }
        fingerprint = fingerprint_payload(payload)
        existing = self.repository.find_retrieval_snapshot_by_fingerprint(fingerprint)
        if existing is not None:
            return _snapshot_from_model(existing)
        model = self.repository.add_retrieval_snapshot(
            AIRetrievalSnapshotModel(
                id=str(uuid4()),
                query_json=_json_text(payload["query"]),
                policy_version=self.policy.retrieval_policy_version,
                candidates_json=_json_text(payload["candidates"]),
                exclusions_json=_json_text(payload["exclusions"]),
                fingerprint=fingerprint,
                created_at=self.clock().astimezone(UTC),
            )
        )
        return _snapshot_from_model(model)


__all__ = [
    "ResearchCaseDocumentError",
    "ResearchCaseDocumentService",
    "ResearchCaseRetrievalService",
    "_snapshot_from_model",
]
