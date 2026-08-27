# RetargetingState — per-side retargeting diagnostics.
# Wire contract: DOCS/01_知识/05_手部重定向状态ROS接口契约.md.
# This is a read-only diagnostic interface; it does not participate in O10
# control decisions.
std_msgs/Header header
string side

builtin_interfaces/Time input_stamp
bool solve_executed
builtin_interfaces/Time solve_finished_stamp
float64 solve_duration_sec

uint8 PHASE_INITIALIZING=0
uint8 PHASE_COLLECTING_LENGTHS=1
uint8 PHASE_WAITING_FIRST_VALID_IK=2
uint8 PHASE_TRACKING=3
uint8 PHASE_STALE=4
uint8 PHASE_RECOVERY_CONFIRMING=5
uint8 PHASE_RECOVERY_RESUMING=6
uint8 PHASE_MODEL_ERROR=7
uint8 phase
bool ready
bool stale
bool command_published

uint8 LENGTH_COLLECTING=0
uint8 LENGTH_FROZEN=1
uint8 LENGTH_CURRENT_INVALID=2
uint8[5] length_state

uint8 IK_UNINITIALIZED=0
uint8 IK_VALID=1
uint8 IK_INPUT_INVALID=2
uint8 IK_SIDE_INVALID=3
uint8 IK_RESIDUAL_EXCEEDED=4
uint8 IK_SOLVER_ERROR=5
uint8 IK_NOT_RUN_LENGTH_COLLECTING=6
uint8 IK_NOT_RUN_STALE=7
uint8[5] ik_state

bool[5] has_valid_ik
bool[5] used_previous_valid_target
bool[5] residual_available
float64[5] normalized_residual
bool[5] target_projection_applied
bool[5] target_projection_distance_available
float64[5] normalized_target_projection_distance
int32[5] solver_result_code
uint32[5] solver_evaluations

# Named wire value for a finger whose solver was not executed.
uint8 SOLVER_NOT_RUN=0

uint32 recovery_valid_count
float64 recovery_valid_duration_sec
