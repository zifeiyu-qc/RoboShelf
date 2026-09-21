#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export MOCK_MODE="${MOCK_MODE:-true}"
export MOCK_STEP_DELAY="${MOCK_STEP_DELAY:-1.0}"

if [[ "${MOCK_MODE,,}" == "false" ]]; then
  ROS_SETUP="$SCRIPT_DIR/ros_ws/devel/setup.bash"
  if [[ ! -f "$ROS_SETUP" ]]; then
    echo "Local ROS workspace is not built. Run: $SCRIPT_DIR/build_ros.sh" >&2
    exit 1
  fi
  source /opt/ros/noetic/setup.bash
  source "$ROS_SETUP"
fi

exec python3 -m uvicorn robot_server:app --host 0.0.0.0 --port 8001 --app-dir "$SCRIPT_DIR"
