"""Secret Leak & Publish Gate Enforcement Tests."""

from pathlib import Path

try:
    import pytest
except ImportError:
    class _PytestStub:
        @staticmethod
        def raises(exc, match=None):
            class _Context:
                def __enter__(self): return self
                def __exit__(self, exc_type, exc_val, exc_tb):
                    if exc_type is None:
                        raise AssertionError(f"Expected {exc.__name__} but none was raised")
                    return issubclass(exc_type, exc)
            return _Context()
    pytest = _PytestStub()

from src.validation.publish_gate import (
    PublishBlocked,
    assert_publishable_dataset,
    assert_safe_object_name,
)
from tools.graphify_analysis import scan_repository

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def test_zero_secrets_in_codebase():
    """Runs graphify AST & regex scanner to verify zero hardcoded API keys or private keys."""
    report = scan_repository()
    assert report["secret_leaks_detected"] == 0, f"Secret leaks detected: {report['secret_hits']}"
    assert report["mock_violations_detected"] == 0, f"Mock violations: {report['mock_hits']}"


def test_publish_gate_blocks_credential_filenames():
    """Verifies publish_gate blocks .env, service-account JSON, and private keys."""
    for bad_name in [
        ".env",
        "config/.env.production",
        "keys/service_account_key.json",
        "certs/server.pem",
        "id_rsa",
    ]:
        with pytest.raises(PublishBlocked):
            assert_safe_object_name(bad_name)


def test_publish_gate_blocks_unverified_licence():
    """Verifies publish_gate blocks cloud upload if redistribution_permitted is not True."""
    unverified_entry = {
        "dataset_key": "unlicensed_layer",
        "licence": {
            "name": "Unknown",
            "redistribution_permitted": False,
            "attribution": "Some agency",
        },
    }
    with pytest.raises(PublishBlocked):
        assert_publishable_dataset(unverified_entry)

