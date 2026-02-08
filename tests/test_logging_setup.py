"""Tests for core/logging_setup.py — attach_audit_file_handler().

Covers: directory creation, handler configuration, duplicate prevention.
Target: raise coverage from 29% to 100%.
"""

import logging
from logging.handlers import RotatingFileHandler

import pytest

from megabot.core.logging_setup import attach_audit_file_handler


@pytest.fixture(autouse=True)
def _cleanup_audit_logger():
    """Remove any RotatingFileHandler we added to the megabot.audit logger."""
    yield
    audit_logger = logging.getLogger("megabot.audit")
    for h in list(audit_logger.handlers):
        if isinstance(h, RotatingFileHandler):
            audit_logger.removeHandler(h)
            h.close()
    # Reset level so we don't leak state
    audit_logger.setLevel(logging.WARNING)


class TestAttachAuditFileHandler:
    def test_creates_directory(self, tmp_path):
        log_path = tmp_path / "subdir" / "audit.log"
        attach_audit_file_handler(path=str(log_path))
        assert log_path.parent.exists()

    def test_returns_rotating_file_handler(self, tmp_path):
        log_path = tmp_path / "audit.log"
        handler = attach_audit_file_handler(path=str(log_path))
        assert isinstance(handler, RotatingFileHandler)

    def test_formatter_is_message_only(self, tmp_path):
        log_path = tmp_path / "audit.log"
        handler = attach_audit_file_handler(path=str(log_path))
        assert handler.formatter._fmt == "%(message)s"

    def test_handler_level_is_info(self, tmp_path):
        log_path = tmp_path / "audit.log"
        handler = attach_audit_file_handler(path=str(log_path))
        assert handler.level == logging.INFO

    def test_handler_added_to_audit_logger(self, tmp_path):
        log_path = tmp_path / "audit.log"
        attach_audit_file_handler(path=str(log_path))
        audit_logger = logging.getLogger("megabot.audit")
        handler_types = [type(h) for h in audit_logger.handlers]
        assert RotatingFileHandler in handler_types

    def test_logger_level_set_to_info(self, tmp_path):
        log_path = tmp_path / "audit.log"
        attach_audit_file_handler(path=str(log_path))
        audit_logger = logging.getLogger("megabot.audit")
        assert audit_logger.level == logging.INFO

    def test_no_duplicate_handler_on_second_call(self, tmp_path):
        log_path = tmp_path / "audit.log"
        attach_audit_file_handler(path=str(log_path))
        attach_audit_file_handler(path=str(log_path))

        audit_logger = logging.getLogger("megabot.audit")
        rfh_count = sum(
            1 for h in audit_logger.handlers if isinstance(h, RotatingFileHandler)
        )
        assert rfh_count == 1

    def test_custom_max_bytes_and_backup_count(self, tmp_path):
        log_path = tmp_path / "audit.log"
        handler = attach_audit_file_handler(
            path=str(log_path), maxBytes=1024, backupCount=2
        )
        assert handler.maxBytes == 1024
        assert handler.backupCount == 2
