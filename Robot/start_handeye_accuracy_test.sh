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

exec python3 "$SCRIPT_DIR/vision/test_handeye_accuracy.py" \
  --base-frame "${BASE_FRAME:-base_link}" \
  --marker-frame "${MARKER_FRAME:-aruco_marker_frame}" \
  --samples "${SAMPLES:-10}" \
  --auto-interval "${AUTO_INTERVAL:-0}"
