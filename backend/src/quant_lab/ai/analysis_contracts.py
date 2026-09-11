"""Frozen AI-4 research-only request and two-stage output contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from quant_lab.ai.contracts import AssetType, FreshnessRequirement, Market, StructuredClaim

STAGE1_CONTRACT_VERSION = "RESEARCH_DIAGNOSIS_V1"
STAGE2_CONTRACT_VERSION = "RESEARCH_RECOMMENDATION_V1"
ANALYSIS_VALIDATION_POLICY_VERSION = "ai-research-validation-v1"
StageContract = Literal["RESEARCH_DIAGNOSIS_V1", "RESEARCH_RECOMMENDATION_V1"]
Identifier = Annotated[str, Field(min_length=1, max_length=160)]
ResearchText = Annotated[str, Field(min_length=1, max_length=2000)]
TextList = Annotated[tuple[ResearchText, ...], Field(max_length=64)]
IdentifierList = Annotated[tuple[Identifier, ...], Field(max_length=128)]


class AnalysisType(StrEnum):
    MARKET_DIAGNOSIS = "MARKET_DIAGNOSIS"
    STRATEGY_REVIEW = "STRATEGY_REVIEW"
    EXPERIMENT_REVIEW = "EXPERIMENT_REVIEW"
    PAPER_REVIEW = "PAPER_REVIEW"


class AnalysisMode(StrEnum):
    CURRENT_RESEARCH = "CURRENT_RESEARCH"
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResearchAnalysisRequest(StrictContract):
    analysis_type: AnalysisType
    market: Market
    asset_type: AssetType
    instrument_id: Identifier | None = None
    universe: IdentifierList | None = None
    market_data_cutoff: datetime
    knowledge_cutoff: datetime | None = None
    knowledge_cutoff_mode: Literal["EXPLICIT", "SERVER_FROZEN_CURRENT"] = "EXPLICIT"
    freshness_requirement: FreshnessRequirement
    analysis_mode: AnalysisMode
    research_question: str = Field(min_length=1, max_length=8000)
    requested_case_count: int = Field(default=5, ge=0, le=20)
    model_config_version_id: Identifier
    stage1_prompt_template_version_id: Identifier
    stage2_prompt_template_version_id: Identifier
    dataset_version_ids: IdentifierList = ()
    market_data_snapshot_id: Identifier | None = None
    experiment_id: Identifier | None = None
    backtest_run_ids: IdentifierList = ()
    paper_session_id: Identifier | None = None
    paper_account_snapshot_ids: IdentifierList = ()
    risk_decision_ids: IdentifierList = ()
    strategy_version_ids: IdentifierList = ()

    @field_validator("market_data_cutoff", "knowledge_cutoff")
    @classmethod
    def aware_cutoff(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cutoff must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def consistent_cutoff_mode(self) -> ResearchAnalysisRequest:
        if self.knowledge_cutoff_mode == "EXPLICIT":
            if self.knowledge_cutoff is None:
                raise ValueError("explicit knowledge cutoff is required")
        elif (
            self.analysis_mode != AnalysisMode.CURRENT_RESEARCH or self.knowledge_cutoff is not None
        ):
            raise ValueError(
                "server freeze requires current research without client knowledge cutoff"
            )
        return self


class ResearchClaim(StructuredClaim):
    evidence_refs: IdentifierList = ()
    operand_refs: IdentifierList = ()


class AnalysisSpecific(StrictContract):
    """Typed extension; fields are observations, never execution parameters."""

    analysis_type: AnalysisType
    regime_observations: TextList = ()
    strategy_limitations: TextList = ()
    experiment_limitations: TextList = ()
    paper_limitations: TextList = ()


class ResearchDiagnosis(StrictContract):
    schema_version: Literal["RESEARCH_DIAGNOSIS_V1"]
    analysis_type: AnalysisType
    claims: tuple[ResearchClaim, ...] = Field(max_length=128)
    observations: TextList
    risks: TextList
    uncertainties: TextList
    abstention: ResearchText | None
    analysis_specific: AnalysisSpecific | None = None

    @model_validator(mode="after")
    def consistent_extension(self) -> ResearchDiagnosis:
        if self.analysis_specific and self.analysis_specific.analysis_type != self.analysis_type:
            raise ValueError("analysis-specific type must match envelope")
        return self


class ResearchAction(StrEnum):
    CREATE_EXPERIMENT_DRAFT = "CREATE_EXPERIMENT_DRAFT"
    ADD_RESEARCH_JOURNAL_DRAFT = "ADD_RESEARCH_JOURNAL_DRAFT"
    CREATE_THESIS_REVISION_DRAFT = "CREATE_THESIS_REVISION_DRAFT"
    WAIT_FOR_MORE_DATA = "WAIT_FOR_MORE_DATA"
    REVIEW_STRATEGY = "REVIEW_STRATEGY"
    REVIEW_PAPER_RESULTS = "REVIEW_PAPER_RESULTS"


class ResearchRecommendation(StrictContract):
    schema_version: Literal["RESEARCH_RECOMMENDATION_V1"]
    analysis_type: AnalysisType
    summary: ResearchText
    claims: tuple[ResearchClaim, ...] = Field(max_length=128)
    hypotheses: TextList
    uncertainties: TextList
    invalidation_conditions: TextList
    suggested_next_actions: tuple[ResearchAction, ...] = Field(max_length=16)
    evidence_refs: IdentifierList
    diagnosis_ref: Identifier
