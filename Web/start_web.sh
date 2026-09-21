#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ROBOT_SERVER_URL="${ROBOT_SERVER_URL:-http://127.0.0.1:8001}"
export ROBOT_REQUEST_TIMEOUT="${ROBOT_REQUEST_TIMEOUT:-3.0}"
export CAMERA_STREAM_ENABLED="${CAMERA_STREAM_ENABLED:-true}"
export CAMERA_IMAGE_TOPIC="${CAMERA_IMAGE_TOPIC:-/camera/color/image_raw}"

ROS_SETUP="$SCRIPT_DIR/../Robot/ros_ws/devel/setup.bash"
if [[ "${CAMERA_STREAM_ENABLED,,}" == "true" && -f "$ROS_SETUP" ]]; then
  source /opt/ros/noetic/setup.bash
  source "$ROS_SETUP"
fi
exec python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --app-dir "$SCRIPT_DIR/backend"
