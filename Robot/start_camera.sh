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

echo "Starting eye-in-hand depth camera"
CAMERA_MODEL="${CAMERA_MODEL:-d405}"

if [[ "${CAMERA_MODEL,,}" == "d405" ]]; then
  echo "Using D405 color defaults: color stream with depth aligned to color"
  exec roslaunch realsense2_camera rs_camera.launch \
    device_type:="${DEVICE_TYPE:-d405}" \
    enable_color:="${ENABLE_COLOR:-true}" \
    enable_depth:="${ENABLE_DEPTH:-true}" \
    enable_infra:="${ENABLE_INFRA:-false}" \
    enable_infra1:="${ENABLE_INFRA1:-false}" \
    enable_infra2:="${ENABLE_INFRA2:-false}" \
    infra_rgb:="${INFRA_RGB:-false}" \
    enable_confidence:="${ENABLE_CONFIDENCE:-true}" \
    align_depth:="${ALIGN_DEPTH:-true}" \
    color_width:="${COLOR_WIDTH:-848}" \
    color_height:="${COLOR_HEIGHT:-480}" \
    color_fps:="${COLOR_FPS:-30}" \
    depth_width:="${DEPTH_WIDTH:-848}" \
    depth_height:="${DEPTH_HEIGHT:-480}" \
    depth_fps:="${DEPTH_FPS:-30}" \
    initial_reset:="${INITIAL_RESET:-true}" \
    wait_for_device_timeout:="${WAIT_FOR_DEVICE_TIMEOUT:-10.0}"
fi

echo "Using generic RealSense color/depth defaults"
exec roslaunch realsense2_camera rs_camera.launch \
  enable_color:="${ENABLE_COLOR:-true}" \
  enable_depth:="${ENABLE_DEPTH:-true}" \
  align_depth:="${ALIGN_DEPTH:-true}" \
  color_width:="${COLOR_WIDTH:-640}" \
  color_height:="${COLOR_HEIGHT:-480}" \
  color_fps:="${COLOR_FPS:-30}"
