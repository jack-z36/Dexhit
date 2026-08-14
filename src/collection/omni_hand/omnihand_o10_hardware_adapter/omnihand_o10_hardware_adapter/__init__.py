"""Production O10 hardware boundary with an explicit external capability gate."""

from .application.provider import O10HardwareProviderApplication
from .contracts import BLOCKED_EXTERNAL, BackendCode, HardwareResponse
from .ports import O10HardwarePort

__all__ = [
    "BLOCKED_EXTERNAL",
    "BackendCode",
    "HardwareResponse",
    "O10HardwarePort",
    "O10HardwareProviderApplication",
]

__version__ = "0.1.0"
