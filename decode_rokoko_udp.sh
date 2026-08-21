#!/usr/bin/env bash
# Print Rokoko Custom Streaming UDP datagrams as formatted JSON.
#
# The existing receiver may already own UDP port 14043.  This script observes
# packets with tcpdump instead of binding a second UDP socket, so it does not
# interfere with the receiver or publish any ROS messages.

set -euo pipefail

readonly DEFAULT_PORT=14043
port="$DEFAULT_PORT"
count=0

usage() {
    cat <<'EOF'
Usage: ./decode_rokoko_udp.sh [--port PORT] [--count N]

Passively capture Rokoko UDP traffic and print every datagram as formatted JSON.

Options:
  --port PORT  UDP destination port to observe (default: 14043).
  --count N    Stop after N complete JSON datagrams. The default, 0, prints continuously.
  -h, --help   Show this help text.

The script uses tcpdump on the Linux "any" interface and needs sudo permission
for packet capture. It does not save a pcap, bind the UDP port, start or stop
ROS nodes, publish commands, or interact with OmniHand hardware.
EOF
}

fail() {
    printf 'decode_rokoko_udp.sh: %s\n' "$*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
        --port)
            (($# >= 2)) || fail '--port needs a value'
            port="$2"
            shift 2
            ;;
        --count)
            (($# >= 2)) || fail '--count needs a value'
            count="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "unknown option: $1"
            ;;
    esac
done

[[ "$port" =~ ^[0-9]+$ ]] && ((port >= 1 && port <= 65535)) \
    || fail '--port must be an integer in [1, 65535]'
[[ "$count" =~ ^[0-9]+$ ]] || fail '--count must be a non-negative integer'

command -v tcpdump >/dev/null || fail 'tcpdump is not installed'
python_bin="$(command -v python3)"
[[ -n "$python_bin" ]] || fail 'python3 is not installed'
"$python_bin" -c 'import lz4.frame' \
    || fail "Python interpreter lacks lz4.frame: $python_bin"

# Validate once before starting the pipeline, so a password prompt remains on
# the terminal rather than becoming part of tcpdump's binary stdout stream.
sudo -v

tcpdump_args=(tcpdump -ni any -U -w - "ip proto 17")

printf 'Capturing Rokoko UDP packets to port %s; press Ctrl-C to stop.\n' "$port" >&2

set +e
sudo "${tcpdump_args[@]}" | "$python_bin" -c '
import json
import struct
import sys

import lz4.frame

LZ4_FRAME_MAGIC = bytes.fromhex("04224d18")
DLT_EN10MB = 1
DLT_LINUX_SLL2 = 276


def read_exact(stream, size):
    chunks = []
    remaining = size
    while remaining:
        part = stream.read(remaining)
        if not part:
            return None if not chunks else b"".join(chunks)
        chunks.append(part)
        remaining -= len(part)
    return b"".join(chunks)


def ipv4_offset(packet, linktype):
    if linktype == DLT_LINUX_SLL2:
        if len(packet) < 20 or packet[0:2] != bytes.fromhex("0800"):
            return None
        return 20
    if linktype != DLT_EN10MB or len(packet) < 14:
        return None
    offset = 14
    ethertype = int.from_bytes(packet[12:14], "big")
    while ethertype in (0x8100, 0x88A8, 0x9100):
        if len(packet) < offset + 4:
            return None
        ethertype = int.from_bytes(packet[offset + 2:offset + 4], "big")
        offset += 4
    return offset if ethertype == 0x0800 else None


def ipv4_fragment(packet, linktype):
    ip_offset = ipv4_offset(packet, linktype)
    if ip_offset is None or len(packet) < ip_offset + 20:
        return None
    ip = packet[ip_offset:]
    header_bytes = (ip[0] & 0x0F) * 4
    if (ip[0] >> 4) != 4 or header_bytes < 20 or len(ip) < header_bytes:
        return None
    if ip[9] != 17:
        return None
    total_length = int.from_bytes(ip[2:4], "big")
    if total_length < header_bytes or len(ip) < total_length:
        return None
    flags_and_offset = int.from_bytes(ip[6:8], "big")
    return {
        "key": (bytes(ip[12:16]), bytes(ip[16:20]), int.from_bytes(ip[4:6], "big")),
        "source_ip": bytes(ip[12:16]),
        "destination_ip": bytes(ip[16:20]),
        "offset": (flags_and_offset & 0x1FFF) * 8,
        "more_fragments": bool(flags_and_offset & 0x2000),
        "payload": bytes(ip[header_bytes:total_length]),
    }


def json_item(datagram, sequence, seconds, fraction, source_ip, destination_ip, fragments):
    if len(datagram) < 8:
        return {"_decode_error": "reassembled UDP datagram has no complete header"}
    udp_length = int.from_bytes(datagram[4:6], "big")
    if udp_length < 8 or udp_length > len(datagram):
        return {"_decode_error": f"invalid UDP length: {udp_length}"}
    payload = datagram[8:udp_length]
    encoding = "lz4-frame" if payload.startswith(LZ4_FRAME_MAGIC) else "plain-json"
    try:
        decoded = lz4.frame.decompress(payload) if encoding == "lz4-frame" else payload
        body = json.loads(decoded)
    except (RuntimeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        body = {"_decode_error": str(error)}

    return {
        "packet": sequence,
        "captured_at": {"sec": seconds, "fraction": fraction},
        "udp": {
            "source": ".".join(map(str, source_ip)) + ":" + str(int.from_bytes(datagram[0:2], "big")),
            "destination": ".".join(map(str, destination_ip)) + ":" + str(int.from_bytes(datagram[2:4], "big")),
            "payload_bytes": len(payload),
            "encoding": encoding,
            "ip_fragments": fragments,
        },
        "json": body,
    }


stream = sys.stdin.buffer
global_header = read_exact(stream, 24)
if global_header is None or len(global_header) != 24:
    raise SystemExit("tcpdump ended before writing a pcap header")

magic = global_header[0:4]
if magic in (bytes.fromhex("d4c3b2a1"), bytes.fromhex("4d3cb2a1")):
    endian = "<"
elif magic in (bytes.fromhex("a1b2c3d4"), bytes.fromhex("a1b23c4d")):
    endian = ">"
else:
    raise SystemExit("unsupported pcap byte order")
linktype = struct.unpack(endian + "I", global_header[20:24])[0]
if linktype not in (DLT_LINUX_SLL2, DLT_EN10MB):
    raise SystemExit(f"unsupported tcpdump link type: {linktype}")

target_port = int(sys.argv[1])
message_limit = int(sys.argv[2])
sequence = 0
fragments_by_datagram = {}
while True:
    record_header = read_exact(stream, 16)
    if record_header is None:
        break
    if len(record_header) != 16:
        raise SystemExit("truncated pcap record header")
    seconds, fraction, captured_length, _original_length = struct.unpack(endian + "IIII", record_header)
    packet = read_exact(stream, captured_length)
    if packet is None or len(packet) != captured_length:
        raise SystemExit("truncated pcap packet")
    fragment = ipv4_fragment(packet, linktype)
    if fragment is None:
        continue
    if fragment["offset"] == 0:
        if len(fragment["payload"]) < 8:
            continue
        if int.from_bytes(fragment["payload"][2:4], "big") != target_port:
            continue
        fragments_by_datagram[fragment["key"]] = {
            "parts": {},
            "end": None,
            "seconds": seconds,
            "fraction": fraction,
            "source_ip": fragment["source_ip"],
            "destination_ip": fragment["destination_ip"],
        }
    state = fragments_by_datagram.get(fragment["key"])
    if state is None:
        continue
    state["parts"][fragment["offset"]] = fragment["payload"]
    end = fragment["offset"] + len(fragment["payload"])
    if not fragment["more_fragments"]:
        state["end"] = end
    if state["end"] is None:
        continue
    cursor = 0
    assembled = []
    while cursor < state["end"]:
        part = state["parts"].get(cursor)
        if part is None:
            break
        assembled.append(part)
        cursor += len(part)
    if cursor != state["end"]:
        continue
    del fragments_by_datagram[fragment["key"]]
    sequence += 1
    item = json_item(
        b"".join(assembled), sequence, state["seconds"], state["fraction"],
        state["source_ip"], state["destination_ip"], len(state["parts"]),
    )
    print(json.dumps(item, ensure_ascii=False, indent=2), flush=True)
    if message_limit and sequence >= message_limit:
        break
' "$port" "$count"
pipeline_status=("${PIPESTATUS[@]}")
set -e
if ((pipeline_status[1] != 0)); then
    exit "${pipeline_status[1]}"
fi
# After Python has printed the requested number of JSON datagrams it closes the
# pipe. tcpdump then exits from SIGPIPE (141), which is the expected outcome.
if ((pipeline_status[0] != 0 && pipeline_status[0] != 141)); then
    exit "${pipeline_status[0]}"
fi
