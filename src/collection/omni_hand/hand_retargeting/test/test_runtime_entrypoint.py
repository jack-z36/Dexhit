"""Runtime entrypoint contract for the external numeric environment."""

from pathlib import Path
import subprocess


SCRIPT = Path(__file__).parents[1] / "scripts" / "hand_retargeting_node"


def test_runtime_entrypoint_requires_explicit_external_runtime(monkeypatch):
    """Missing runtime inputs fail explicitly before ROS node startup."""
    monkeypatch.delenv("DEXHIT_COLLECTION_PREFIX", raising=False)
    monkeypatch.delenv("OMNIHAND_O10_MODEL_FIXTURE", raising=False)
    result = subprocess.run(
        [str(SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "BLOCKED_ENV" in result.stderr
    assert "DEXHIT_COLLECTION_PREFIX" in result.stderr
