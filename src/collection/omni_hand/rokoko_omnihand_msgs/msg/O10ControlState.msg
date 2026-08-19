# O10ControlState — per-side control diagnostics.
# Wire contract: DOCS/01_知识/06_O10控制状态ROS接口契约.md.
# This is a read-only diagnostic interface; it does not participate in control
# decisions.
std_msgs/Header header
string side

uint8 EVENT_STARTUP=0
uint8 EVENT_TARGET_PROCESSED=1
uint8 EVENT_TARGET_TIMEOUT=2
uint8 EVENT_FEEDBACK_RECEIVED=3
uint8 EVENT_ERROR_STATUS_RECEIVED=4
uint8 EVENT_OPERATOR_REQUEST=5
uint8 EVENT_FAULT_CHANGED=6
uint8 EVENT_COMPONENT_STATE_CHANGED=7
uint8 event

uint8 PHASE_INITIALIZING=0
uint8 PHASE_IDLE_NOT_READY=1
uint8 PHASE_IDLE_READY=2
uint8 PHASE_ACTIVE=3
uint8 PHASE_PAUSED_TARGET_STALE=4
uint8 PHASE_FAULT_LATCHED=5
uint8 phase

bool feedback_ready
bool error_monitor_ready
bool target_ready
bool target_fresh
bool fault_latched
bool motion_enabled

uint8 TARGET_NOT_EVALUATED=0
uint8 TARGET_SENT=1
uint8 TARGET_VALID_MOTION_DISABLED=2
uint8 TARGET_REJECTED_SCHEMA=3
uint8 TARGET_REJECTED_NAME_ORDER=4
uint8 TARGET_REJECTED_NONFINITE=5
uint8 TARGET_REJECTED_LIMIT=6
uint8 TARGET_REJECTED_AUX_FIELDS=7
uint8 TARGET_REJECTED_TIMESTAMP=8
uint8 TARGET_REJECTED_CONTROL_STATE=9
uint8 target_result
bool command_published
bool[10] slew_limited

uint32 FAULT_HARDWARE_ERROR=1
uint32 FAULT_COMMAND_READBACK_TIMEOUT=2
uint32 FAULT_INVALID_FEEDBACK=4
uint32 FAULT_SAFETY_INVARIANT=8
uint32 FAULT_COMPONENT_RESTART_OR_DISCONNECT=16
uint32 FAULT_ERROR_MONITOR_TIMEOUT=32
uint32 fault_reason_mask
uint16[10] hardware_error_bits

bool target_time_available
builtin_interfaces/Time last_target_input_stamp
builtin_interfaces/Time last_target_received_stamp
bool command_time_available
builtin_interfaces/Time last_command_sent_stamp
bool feedback_time_available
builtin_interfaces/Time last_feedback_received_stamp
bool error_status_time_available
builtin_interfaces/Time last_error_status_received_stamp
