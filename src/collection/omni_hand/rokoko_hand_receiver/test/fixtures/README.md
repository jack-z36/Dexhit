# Rokoko JSON v3 fixture provenance

`official_fields_constructed_v3.json` is a deterministic test fixture constructed
from Rokoko's official Custom Streaming JSON v3 documentation and its published
hand-node spellings. It is intentionally shuffled to verify name-based reordering.

Official source:
<https://support.rokoko.com/hc/en-us/articles/4410416376977-Custom-Streaming>

This is **not** a captured UDP datagram from the project's target Rokoko Studio
installation. A real capture must be added as a separate regression fixture before
claiming target-installation compatibility; it may refine required/optional fields
but must not silently change the `RawHandFrame` contract.
