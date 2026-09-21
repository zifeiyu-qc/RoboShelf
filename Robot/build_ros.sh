#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$SCRIPT_DIR/ros_ws"

source /opt/ros/noetic/setup.bash
cd "$WORKSPACE"
if [[ ! -e src/CMakeLists.txt ]]; then
  catkin_init_workspace src
fi
catkin_make
