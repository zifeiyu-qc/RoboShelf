#!/usr/bin/env bash
set -euo pipefail

source /opt/ros/noetic/setup.bash
unset ROS_IP ROS_HOSTNAME
export ROS_MASTER_URI="${SUPERMARKET_ROS_MASTER_URI:-http://127.0.0.1:11311}"

echo "Starting ROS Master at $ROS_MASTER_URI"
exec roscore
