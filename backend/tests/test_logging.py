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


def test_import_log_record_uses_a_safe_audit_allowlist(capsys) -> None:
    configure_logging(level="INFO")

    logging.getLogger("quant_lab.import").info(
        "preview ready",
        extra={
            "event": "data_import.preview_ready",
            "request_id": "request-1",
            "batch_id": "batch-1",
            "provider": "local_csv",
            "source_hash": "a" * 64,
            "row_count": 3,
            "accepted_count": 2,
            "rejected_count": 1,
            "warning_count": 0,
            "error_category": None,
            "duration_ms": 12,
            "raw_file_content": "must-not-appear",
        },
    )

    record = json.loads(capsys.readouterr().err)
    assert record["request_id"] == "request-1"
    assert record["batch_id"] == "batch-1"
    assert record["provider"] == "local_csv"
    assert record["row_count"] == 3
    assert "raw_file_content" not in record
