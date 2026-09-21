#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_FILE="$SCRIPT_DIR/ros_ws/devel/setup.bash"
GRIPPER_ADDRESS="${GRIPPER_IP:-192.168.1.11}"

if [[ ! -f "$SETUP_FILE" ]]; then
  echo "ROS workspace is not built. Run: $SCRIPT_DIR/build_ros.sh" >&2
  exit 1
fi
source /opt/ros/noetic/setup.bash
source "$SETUP_FILE"
unset ROS_IP ROS_HOSTNAME
export ROS_MASTER_URI="${SUPERMARKET_ROS_MASTER_URI:-http://127.0.0.1:11311}"

if ! rosnode list >/dev/null 2>&1; then
  echo "ROS Master is not reachable at ${ROS_MASTER_URI:-http://localhost:11311}. Start start_roscore.sh first." >&2
  exit 1
fi
if ! ping -c 1 -W 1 "$GRIPPER_ADDRESS" >/dev/null 2>&1; then
  echo "Warning: Robotiq 3F $GRIPPER_ADDRESS did not answer ping; attempting TCP connection anyway." >&2
fi

echo "Connecting Robotiq 3F gripper at $GRIPPER_ADDRESS"
exec rosrun robotiq_3f_gripper_control Robotiq3FGripperTcpNode.py "$GRIPPER_ADDRESS"
