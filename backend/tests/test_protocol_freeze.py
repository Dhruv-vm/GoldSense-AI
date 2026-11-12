from app.services.prediction.protocol import (
    EXPERIMENT_PROTOCOL_V1_SHA256,
    PROTOCOL_DOC_PATH,
    compute_protocol_sha256,
)


def test_experiment_protocol_v1_is_frozen():
    assert PROTOCOL_DOC_PATH.exists(), f"Protocol document missing: {PROTOCOL_DOC_PATH}"
    actual = compute_protocol_sha256()
    assert actual == EXPERIMENT_PROTOCOL_V1_SHA256, (
        "docs/ml/EXPERIMENT_PROTOCOL_V1.md changed. A protocol change is an amendment: record it in "
        "the document's Amendment Log and update EXPERIMENT_PROTOCOL_V1_SHA256 in "
        f"app/services/prediction/protocol.py to {actual} in the same change."
    )
