"""Frozen experiment-protocol identity (F-22 / A3-FINAL-6).

`EXPERIMENT_PROTOCOL_V1_SHA256` is the SHA-256 of docs/ml/EXPERIMENT_PROTOCOL_V1.md.
Both tests/test_protocol_freeze.py and runtime prospective forecast generation
verify this canonical SHA-256 before logging PROSPECTIVE forecasts.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

EXPERIMENT_PROTOCOL_VERSION = "EXPERIMENT_PROTOCOL_V1"
EXPERIMENT_PROTOCOL_V1_SHA256 = "ccb19df542209e530ebdc2cfdf5a5018d66010c63babdcf37202344d69c20f23"

PROTOCOL_HASHES: dict[str, str] = {
    EXPERIMENT_PROTOCOL_VERSION: EXPERIMENT_PROTOCOL_V1_SHA256,
}

PROTOCOL_DOC_PATH = Path(__file__).resolve().parents[4] / "docs" / "ml" / "EXPERIMENT_PROTOCOL_V1.md"


class ProtocolIntegrityError(RuntimeError):
    """Raised when the active experiment protocol document is missing, modified, or unverified."""


def compute_protocol_sha256(path: Path = PROTOCOL_DOC_PATH) -> str:
    """Compute canonical SHA-256 over normalized LF line endings."""
    if not path.exists():
        raise ProtocolIntegrityError(f"Protocol document missing: {path}")
    # Normalise line endings so a Windows checkout does not change the hash.
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def verify_runtime_protocol(
    *,
    protocol_version: str = EXPERIMENT_PROTOCOL_VERSION,
    protocol_path: Path | None = None,
    expected_sha256: str | None = None,
) -> str:
    """
    Verify at runtime that the experiment protocol document exists and matches the
    frozen SHA-256 for `protocol_version`. Raises ProtocolIntegrityError otherwise.
    """
    expected = expected_sha256 or PROTOCOL_HASHES.get(protocol_version)
    if not expected:
        raise ProtocolIntegrityError(
            f"Unsupported or unregistered protocol_version={protocol_version!r}; "
            "explicit versioned protocol registration is required."
        )
    target_path = protocol_path or PROTOCOL_DOC_PATH
    actual = compute_protocol_sha256(target_path)
    if actual != expected:
        raise ProtocolIntegrityError(
            f"Protocol integrity check failed for {protocol_version}: "
            f"expected {expected}, got {actual} ({target_path})."
        )
    return actual
