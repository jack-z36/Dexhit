"""Run the package's configured ROS flake8 linter."""

from pathlib import Path

from ament_flake8.main import main_with_errors
import pytest


@pytest.mark.flake8
@pytest.mark.linter
def test_flake8():
    """Check production and test Python sources."""
    config = Path(__file__).with_name("ament_flake8.ini")
    return_code, errors = main_with_errors(
        argv=["--config", str(config), "hand_retargeting", "test"]
    )
    assert return_code == 0, "\n".join(errors)
