"""Pinocchio-dependent kinematic model build is BLOCKED_ENV.

The structural nq=nv=16 check is already enforced in test_urdf_validator by
counting movable joints. Building the actual pinocchio kinematic model and
asserting ``model.nq == 16`` genuinely requires pinocchio, which is not
installed. These tests document that block precisely: they must NOT fake a pass.
"""

import pytest

from omnihand_o10_model.pinocchio_model import (
    BLOCKED_ENV_DEPENDENCY,
    PinocchioUnavailableError,
    build_pinocchio_model,
    is_pinocchio_available,
)


def test_pinocchio_availability_reported_honestly():
    # This environment is documented as not having pinocchio. If it ever gets
    # installed, this test flips and the BLOCKED_ENV status must be revisited.
    available = is_pinocchio_available()
    if available:
        pytest.skip("pinocchio is now installed; BLOCKED_ENV no longer applies")
    assert available is False


@pytest.mark.skipif(
    is_pinocchio_available(),
    reason="pinocchio installed: the blocked path is not exercised here",
)
def test_build_pinocchio_model_raises_blocked_env(tmp_path):
    urdf = tmp_path / "right.urdf"
    urdf.write_text("<robot/>", encoding="utf-8")
    with pytest.raises(PinocchioUnavailableError) as exc:
        build_pinocchio_model(urdf, "right")
    msg = str(exc.value)
    assert "BLOCKED_ENV" in msg
    assert BLOCKED_ENV_DEPENDENCY in msg
    assert "16" in msg


def test_blocked_env_dependency_documents_exact_missing_package():
    assert "pinocchio" in BLOCKED_ENV_DEPENDENCY.lower()
