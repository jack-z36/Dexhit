# RawHandFrame — per-side Rokoko raw hand frame published by the Rokoko receiver
# node on /rokoko/{left,right}/raw_hand. Read-only source data for retargeting.
#
# Hand side is expressed by the Topic name, NOT by a field here (Spec decision 5).
# The canonical 21 Rokoko node spellings are NOT owned by this package; they are
# fixed by the versioned official JSON v3 fixture in rokoko_hand_receiver. This
# message only carries the 21 names/positions/quaternions as data arrays, already
# reordered into the project canonical order (Spec decision 6):
#   Hand, then Thumb/Index/Middle/Ring/Little, each Proximal/Medial/Distal/Tip.

# stamp = local ROS time at which the UDP datagram was received on this host
# (Spec decisions 4, 50). frame_id is set by the publisher and is not used to
# encode the hand side.
std_msgs/Header header

# The single Rokoko Actor selected for this run (Spec decision 3). One run
# selects exactly one Actor (configurable index, default 0).
uint32 actor_index
string actor_name

# Scene-level source timestamp carried VERBATIM from the Rokoko source (Spec
# decisions 4, 50). Its epoch/unit is UNCONFIRMED: it MUST NOT be converted to
# ROS time, subtracted from ROS time or used for control timing.
float64 source_timestamp

# Canonical-ordered 21 node data arrays (Spec decisions 5, 6, 49).
# Positions are Rokoko world coordinates, unmodified: no re-relativization,
# mirroring, filtering or normalization (Spec decision 7).
# Orientations are x, y, z, w quaternions, unmodified (Spec decision 7).
string[21] node_names
geometry_msgs/Point[21] positions
geometry_msgs/Quaternion[21] orientations
