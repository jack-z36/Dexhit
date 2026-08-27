"""Run the ROS docstring linter for production sources."""

from ament_pep257.main import main
import pytest


@pytest.mark.linter
@pytest.mark.pep257
def test_pep257():
    """Check production docstrings."""
    assert main(argv=["hand_retargeting"]) == 0
