from sqlalchemy import create_engine

from quant_lab.ai.analysis_contracts import AnalysisType
from quant_lab.ai.analysis_prompts import (
    ValidationFeedbackBuilder,
    publish_analysis_prompts,
    render_analysis_prompt,
)
from quant_lab.ai.configuration import PromptTemplateVersionService
from quant_lab.ai.repository import AIRepository
from quant_lab.ai.validation import ValidationService
from quant_lab.db.sqlite import Base

from .test_ai2_validation import _pack


def test_published_prompts_are_versioned_and_render_deterministically():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    service = PromptTemplateVersionService(AIRepository(engine))
    first = publish_analysis_prompts(service)
    second = publish_analysis_prompts(service)
    assert [x.id for x in first] == [x.id for x in second]
    kwargs = dict(
        template=first[0],
        pack=_pack(),
        research_question="研究风险",
        analysis_type=AnalysisType.MARKET_DIAGNOSIS,
    )
    base = render_analysis_prompt(**kwargs)
    from quant_lab.ai.fingerprints import fingerprint_payload

    assert base.rendered_prompt_fingerprint == fingerprint_payload(
        [m.model_dump(mode="json") for m in base.messages]
    )
    invalid = ValidationService().validate("{bad", _pack(), origin_attempt_id="secret-attempt")
    feedback = ValidationFeedbackBuilder().build(invalid)
    retry = render_analysis_prompt(**kwargs, validation_feedback=feedback)
    assert retry.base_input_fingerprint == base.base_input_fingerprint
    assert retry.rendered_prompt_fingerprint != base.rendered_prompt_fingerprint
    assert "secret-attempt" not in retry.user_prompt
    for section in ["FACT", "USER_NOTE", "CASE_MEMORY", "QUESTION", "OUTPUT CONTRACT", "UNTRUSTED"]:
        assert section in base.user_prompt


def test_feedback_does_not_echo_unknown_nested_field_names():
    from quant_lab.ai.contracts import ValidationFinding

    result = ValidationService().validate("{bad", _pack(), origin_attempt_id="a")
    finding = ValidationFinding(
        layer="SCHEMA",
        code="SCHEMA_INVALID_TYPE",
        severity="ERROR",
        message_safe="candidate secrets",
        retryable=True,
        field_path="claims.private_customer_secret",
    )
    result = result.model_copy(update={"findings": (finding,)})
    feedback = ValidationFeedbackBuilder().build(result)
    assert feedback[0].field_path == "$"
    assert "secret" not in str(feedback)
