from __future__ import annotations

from enum import StrEnum


class ResearchExperimentStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class RunRole(StrEnum):
    BASELINE = "BASELINE"
    CANDIDATE = "CANDIDATE"
    REFERENCE = "REFERENCE"


class JournalEntryType(StrEnum):
    HYPOTHESIS = "HYPOTHESIS"
    OBSERVATION = "OBSERVATION"
    DECISION = "DECISION"
    CONCLUSION = "CONCLUSION"
    TODO = "TODO"


class ComparabilityStatus(StrEnum):
    STRICTLY_COMPARABLE = "STRICTLY_COMPARABLE"
    PARTIALLY_COMPARABLE = "PARTIALLY_COMPARABLE"
    NOT_COMPARABLE = "NOT_COMPARABLE"
