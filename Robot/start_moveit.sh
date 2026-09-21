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
  echo "ROS Master is not reachable at ${ROS_MASTER_URI:-http://localhost:11311}. Start start_roscore.sh first." >&2
  exit 1
fi
if ! rosparam get /robot_description >/dev/null 2>&1; then
  echo "UR30 robot_description is missing. Start start_ur30_driver.sh and wait for it to finish initialization." >&2
  exit 1
fi
if ! rosservice list 2>/dev/null | grep -Fxq /controller_manager/list_controllers; then
  echo "UR30 controller manager is unavailable. Check the driver terminal before starting MoveIt." >&2
  exit 1
fi

echo "Starting MoveIt and Robotiq joint-state publisher"
exec roslaunch supermarket_robot_bringup moveit.launch use_rviz:="${USE_RVIZ:-true}"
