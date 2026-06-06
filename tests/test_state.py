from local_llm_env.state import compute_spec_hash, diff_state
from local_llm_env.types import ReconcilePlan


def test_spec_hash_changes_when_spec_changes():
    manifest = {"models": [{"id": "a"}]}
    hash_a = compute_spec_hash({"x": 1}, manifest)
    hash_b = compute_spec_hash({"x": 2}, manifest)
    assert hash_a != hash_b


def test_diff_state_detects_changes():
    previous = {
        "applied_spec_hash": "old",
        "managed_resources": [{"type": "file", "path": "/a"}],
    }
    plan = ReconcilePlan(
        spec_hash="new",
        actions=[],
        observed={},
        managed_resources=[{"type": "file", "path": "/b"}],
    )
    diff = diff_state(previous, plan)
    assert diff["spec_changed"] is True
    assert diff["resources_added"] == [{"type": "file", "path": "/b"}]
    assert diff["resources_removed"] == [{"type": "file", "path": "/a"}]

