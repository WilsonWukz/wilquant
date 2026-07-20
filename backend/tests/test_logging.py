import json
import logging

from quant_lab.core.logging import configure_logging


def test_log_record_is_structured_json(capsys) -> None:
    configure_logging(level="INFO")

    logging.getLogger("quant_lab.test").info(
        "database ready",
        extra={"event": "sqlite.ready", "correlation_id": "test-1"},
    )

    record = json.loads(capsys.readouterr().err)
    assert record["level"] == "INFO"
    assert record["event"] == "sqlite.ready"
    assert record["correlation_id"] == "test-1"
    assert record["message"] == "database ready"
    assert record["application_version"] == "0.1.0"
    assert "timestamp" in record
