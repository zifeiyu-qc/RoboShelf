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

echo "Starting ArUco marker detector"
exec roslaunch supermarket_robot_bringup aruco_single_realsense.launch \
  marker_id:="${MARKER_ID:-582}" \
  marker_size:="${MARKER_SIZE:-0.034}" \
  image_topic:="${IMAGE_TOPIC:-/camera/color/image_raw}" \
  camera_info_topic:="${CAMERA_INFO_TOPIC:-/camera/color/camera_info}" \
  camera_frame:="${CAMERA_FRAME:-camera_color_optical_frame}" \
  reference_frame:="${REFERENCE_FRAME:-camera_color_optical_frame}" \
  marker_frame:="${MARKER_FRAME:-aruco_marker_frame}"
