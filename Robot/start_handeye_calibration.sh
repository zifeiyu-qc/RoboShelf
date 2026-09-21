#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_FILE="$SCRIPT_DIR/ros_ws/devel/setup.bash"

if [[ ! -f "$SETUP_FILE" ]]; then
  echo "ROS workspace is not built. Run: $SCRIPT_DIR/build_ros.sh" >&2
  exit 1
fi
source /opt/ros/noetic/setup.bash
source "$SETUP_FILE"
unset ROS_IP ROS_HOSTNAME
export ROS_MASTER_URI="${SUPERMARKET_ROS_MASTER_URI:-http://127.0.0.1:11311}"

if ! rosnode list >/dev/null 2>&1; then
  echo "ROS Master is not reachable at ${ROS_MASTER_URI}. Start start_roscore.sh first." >&2
  exit 1
fi

echo "Starting easy_handeye eye-in-hand calibration"
exec roslaunch supermarket_robot_bringup handeye_eye_on_hand.launch \
  robot_base_frame:="${ROBOT_BASE_FRAME:-base_link}" \
  robot_effector_frame:="${ROBOT_EFFECTOR_FRAME:-palm}" \
  tracking_base_frame:="${TRACKING_BASE_FRAME:-camera_color_optical_frame}" \
  tracking_marker_frame:="${TRACKING_MARKER_FRAME:-aruco_marker_frame}" \
  move_group:="${MOVE_GROUP:-manipulator}" \
  freehand_robot_movement:="${FREEHAND_ROBOT_MOVEMENT:-false}" \
  start_rviz:="${START_RVIZ:-true}" \
  start_sampling_gui:="${START_SAMPLING_GUI:-true}"
