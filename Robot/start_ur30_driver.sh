#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_FILE="$SCRIPT_DIR/ros_ws/devel/setup.bash"
ROBOT_ADDRESS="${ROBOT_IP:-192.168.1.10}"
REVERSE_ADDRESS="${REVERSE_IP:-192.168.1.100}"

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
if ! ip -4 -o address show | awk '{print $4}' | cut -d/ -f1 | grep -Fxq "$REVERSE_ADDRESS"; then
  echo "REVERSE_IP $REVERSE_ADDRESS is not assigned to this computer." >&2
  echo "Available IPv4 addresses:" >&2
  ip -4 -o address show | awk '{print "  " $2 ": " $4}' >&2
  exit 1
fi
if ! ping -c 1 -W 1 "$ROBOT_ADDRESS" >/dev/null 2>&1; then
  echo "Warning: UR30 $ROBOT_ADDRESS did not answer ping; the driver may still connect if ICMP is disabled." >&2
fi

echo "Connecting UR30 $ROBOT_ADDRESS; reverse connection target $REVERSE_ADDRESS"
exec roslaunch supermarket_robot_bringup ur30_driver.launch \
  robot_ip:="$ROBOT_ADDRESS" \
  reverse_ip:="$REVERSE_ADDRESS" \
  headless_mode:="${HEADLESS_MODE:-true}"
