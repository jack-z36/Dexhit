"""Small provenance-preserving RawHandFrame derivatives for T1.

These are maintained derivatives of real ROS ``RawHandFrame`` messages, not
synthetic data and not the original UDP bytes.  The source MCAP remains
outside the repository.

Source:
    /tmp/omnihand-thumb-user-20260820_101032/left_chain/left_chain_0.mcap
Source MCAP SHA-256:
    2c515f083e3d004f362b8670dc7ce5a91cbc089c2e8a7c8e0722130b8d6f8851
Stage/topic:
    real Rokoko capture -> /rokoko/left/raw_hand
Message type:
    rokoko_omnihand_msgs/msg/RawHandFrame
Markers:
    G_FLEX_HOLD marker at 1787191892481825742 ns; selected sample at
        1787191892494384634 ns (nearest RawHandFrame received timestamp)
    I_OPEN_HOLD marker at 1787191904446191981 ns; selected sample at
        1787191904433064588 ns (nearest RawHandFrame received timestamp)
Fields copied:
    RawHandFrame.header.stamp, actor_index, actor_name, source_timestamp,
    node_names[21], positions[21], orientations[21].  The maintained fixture
    stores header.stamp, node_names[21], and positions[21]; actor metadata and
    orientations are provenance-only and are not needed by RetargetingSession.
Extraction/reproduction:
    Read the MCAP read-only with the ROS 2 MCAP reader, select topic
    /rokoko/left/raw_hand, compare message.header.stamp to each marker ns,
    and copy the nearest message's header.stamp, node_names, and positions.
    The checksum can be reproduced with:
        sha256sum /tmp/omnihand-thumb-user-20260820_101032/left_chain/left_chain_0.mcap
    No MCAP or ROS graph is required to run this fixture.
The source_timestamp values are retained below as provenance metadata.
"""

from hand_retargeting.contracts import RawHandFrameValue


LEFT_NODE_NAMES = (
    "leftHand",
    "leftThumbProximal", "leftThumbMedial", "leftThumbDistal", "leftThumbTip",
    "leftIndexProximal", "leftIndexMedial", "leftIndexDistal", "leftIndexTip",
    "leftMiddleProximal", "leftMiddleMedial", "leftMiddleDistal", "leftMiddleTip",
    "leftRingProximal", "leftRingMedial", "leftRingDistal", "leftRingTip",
    "leftLittleProximal", "leftLittleMedial", "leftLittleDistal", "leftLittleTip",
)

G_FLEX_MARKER_NS = 1787191892481825742
G_FLEX_RECEIVED_AT_NS = 1787191892494384634
G_FLEX_SOURCE_TIMESTAMP = 3660.059
G_FLEX_POSITIONS = (
    (-0.463852465, 1.05246985, 0.08040583),
    (-0.439426839, 1.062883, 0.104220159),
    (-0.424107134, 1.09991062, 0.09750756),
    (-0.411541373, 1.111368, 0.0717808),
    (-0.408938557, 1.10976124, 0.03668343),
    (-0.381543845, 1.07773018, 0.09612451),
    (-0.3360122, 1.08460021, 0.08683862),
    (-0.310212135, 1.09492064, 0.07889959),
    (-0.287174672, 1.10872, 0.0699011),
    (-0.383746684, 1.07422924, 0.0701871961),
    (-0.340537041, 1.07382822, 0.04877951),
    (-0.316238374, 1.09065914, 0.037032675),
    (-0.299712658, 1.11541831, 0.0292711277),
    (-0.392781615, 1.07188845, 0.0458520949),
    (-0.3565149, 1.08038318, 0.020525476),
    (-0.335143477, 1.09353614, 0.00589229167),
    (-0.316563547, 1.110802, -0.0066210106),
    (-0.4077473, 1.06884134, 0.0270688236),
    (-0.3778141, 1.07571685, 0.00744362),
    (-0.3604959, 1.0866611, -0.00281089172),
    (-0.3448308, 1.10174942, -0.0112676891),
)

I_OPEN_MARKER_NS = 1787191904446191981
I_OPEN_RECEIVED_AT_NS = 1787191904433064588
I_OPEN_SOURCE_TIMESTAMP = 3671.998
I_OPEN_POSITIONS = (
    (-0.441106379, 1.03114045, 0.08450501),
    (-0.414881, 1.04012835, 0.106946304),
    (-0.394735426, 1.07429838, 0.115741834),
    (-0.374517053, 1.08769178, 0.134790972),
    (-0.357290566, 1.09661853, 0.16419749),
    (-0.3573947, 1.05422974, 0.09541834),
    (-0.313613623, 1.0655458, 0.08270135),
    (-0.289588362, 1.07872581, 0.07352226),
    (-0.268725842, 1.09530509, 0.0639304742),
    (-0.361455977, 1.05182636, 0.06958072),
    (-0.3199181, 1.05389988, 0.04517112),
    (-0.296790123, 1.07179189, 0.032654468),
    (-0.2810896, 1.09711611, 0.0250033531),
    (-0.372196555, 1.05064213, 0.0458626971),
    (-0.337677479, 1.063161, 0.0197747536),
    (-0.3187858, 1.0805074, 0.00613376964),
    (-0.303922743, 1.10228264, -0.004105377),
    (-0.388484031, 1.04863524, 0.02806501),
    (-0.3597754, 1.05930233, 0.008305386),
    (-0.344036, 1.07341, -0.0005318234),
    (-0.330843866, 1.09175479, -0.0063636424),
)


REAL_LEFT_FLEX_G = RawHandFrameValue(
    LEFT_NODE_NAMES, G_FLEX_POSITIONS, G_FLEX_RECEIVED_AT_NS
)
REAL_LEFT_OPEN_I = RawHandFrameValue(
    LEFT_NODE_NAMES, I_OPEN_POSITIONS, I_OPEN_RECEIVED_AT_NS
)
