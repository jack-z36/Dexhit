# Rokoko JSON v3 fixture provenance

## `official_fields_constructed_v3.json`

A deterministic, shuffled test fixture constructed from Rokoko's official Custom
Streaming JSON v3 documentation and its published hand-node spellings. It is
intentionally shuffled to verify name-based reordering.

Official source:
<https://support.rokoko.com/hc/en-us/articles/4410416376977-Custom-Streaming>

Its `version` is now pinned to the real wire spelling `"3,0"` (a string), matching
the captured datagram below.

## `captured_left_glove_v3.lz4`

A **real UDP datagram** captured from the project's target Rokoko Studio
installation. It is LZ4-frame-compressed (leading magic `04 22 4d 18`), as Rokoko
Studio emits when compression is enabled. Capture facts:

- Sender: Windows host `192.168.103.220` (Rokoko Studio)
- Receiver: Ubuntu `192.168.103.29`, UDP port `14043`
- Payload: 2978 bytes on the wire → 6735 bytes after LZ4 decompression
- Confirms: `version` is the string `"3,0"`, `fps` is `30.0`,
  `scene.timestamp` is a finite float, and the actor `body` mixes hand nodes with
  full-body skeleton nodes (hip/spine/chest/.../leftFoot/rightToe).

## `captured_left_glove_v3.json`

The LZ4-decompressed JSON of the capture above, kept as a human-readable sibling so
field structure can be reviewed without decompressing. This actor has
`hasLeftGlove=true` and `hasRightGlove=false`, so it exercises the left-only path:
the decoder must publish the left hand and reject the right hand with a
`missing node` reason.
