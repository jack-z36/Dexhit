"""Rokoko OmniHand system-test package: deterministic software O10 provider.

Houses the software provider (ARCHITECTURE A09) that emulates the O10 wire
contract without the vendor ``omnihand_node`` package (A04), so the control
system and its integration tests can run end-to-end on a laptop.
"""

from __future__ import annotations

__version__ = "0.1.0"