#!/usr/bin/env python3
"""
Rokoko 手套数据接收测试程序
监听 UDP 端口，接收 LZ4 压缩的 JSON 数据并解析。

Rokoko Studio 的 JSON 流默认经过 LZ4 帧压缩：
  - 数据前 4 字节是 LZ4 魔数 0x184D2204（16 进制 04 22 4d 18）
  - 需要用 lz4.frame.decompress 解压后才能得到纯 JSON
"""

import socket
import json
import sys

import lz4.frame

# ===== 配置参数 =====
UDP_IP = "0.0.0.0"          # 监听所有网络接口
UDP_PORT = 14043            # 端口号，和 Rokoko Studio 里设置的要一致
BUFFER_SIZE = 65535         # 缓冲区大小


def print_actor_summary(actor):
    """打印单个 actor（动捕对象）的关键信息摘要。"""
    name = actor.get("name", "?")
    meta = actor.get("meta", {})
    gloves = "左/右" if meta.get("hasLeftGlove") and meta.get("hasRightGlove") else (
        "仅左手" if meta.get("hasLeftGlove") else
        "仅右手" if meta.get("hasRightGlove") else "无")
    print(f"  🧍 actor: {name}  手套: {gloves}  "
          f"body={meta.get('hasBody', False)}  face={meta.get('hasFace', False)}")

    # 身体骨骼（全身动捕时才有）
    body = actor.get("body", {})
    if body and body.get("hip"):
        hip = body["hip"]
        pos = hip.get("position", {})
        print(f"     📍 hip 位置: x={pos.get('x'):.3f}, y={pos.get('y'):.3f}, z={pos.get('z'):.3f}")
    return len(body)


def main():
    # 1. 创建 UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))

    print(f"✅ UDP 服务器已启动，监听端口 {UDP_PORT}")
    print(f"📡 等待接收来自 Rokoko 的数据（LZ4 压缩 JSON）...")
    print(f"💡 按 Ctrl+C 停止程序\n")
    print("-" * 60)

    packet_count = 0
    show_full = "--full" in sys.argv

    try:
        while True:
            # 2. 接收数据
            data, addr = sock.recvfrom(BUFFER_SIZE)
            packet_count += 1

            # 3. LZ4 解压
            try:
                json_bytes = lz4.frame.decompress(data)
            except Exception as e:
                print(f"\n⚠️  第 {packet_count} 个数据包 LZ4 解压失败: {e}")
                print(f"   来源: {addr[0]}:{addr[1]}，原始 {len(data)} 字节")
                print("-" * 60)
                continue

            # 4. 解析 JSON
            try:
                json_data = json.loads(json_bytes.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                print(f"\n⚠️  第 {packet_count} 个数据包 JSON 解析失败: {e}")
                print(f"   解压后前 200 字符: {json_bytes[:200]}")
                print("-" * 60)
                continue

            # 5. 打印结果
            print(f"\n📦 第 {packet_count} 个数据包")
            print(f"   来源: {addr[0]}:{addr[1]}  |  压缩 {len(data)}B → 解压 {len(json_bytes)}B")

            scene = json_data.get("scene", {})
            print(f"   🕐 场景时间戳: {scene.get('timestamp', 'N/A')}")
            print(f"   📐 版本: {json_data.get('version', 'N/A')}  fps: {json_data.get('fps', 'N/A')}")

            actors = scene.get("actors", [])
            for a in actors:
                print_actor_summary(a)

            if show_full:
                print("   📄 完整 JSON:")
                print(json.dumps(json_data, indent=2, ensure_ascii=False))

            print("-" * 60)

    except KeyboardInterrupt:
        print(f"\n\n🛑 程序已停止，共接收 {packet_count} 个数据包")
        sock.close()
        sys.exit(0)


if __name__ == "__main__":
    main()
