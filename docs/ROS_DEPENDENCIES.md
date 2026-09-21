# ROS 1 Dependencies

The checked-in ROS packages contain only RoboShelf's UR30 bringup and MoveIt configuration. They depend on upstream ROS 1 packages that must be installed separately. This avoids redistributing third-party source and keeps each upstream license and update path clear.

## Supported reference platform

The provided hardware integration targets Ubuntu 20.04 and ROS Noetic. It requires MoveIt 1, the Universal Robots ROS Driver 2.1.4-compatible packages, Robotiq 3F ROS packages, RealSense ROS, ArUco ROS, and easy_handeye.

Install the ROS packages available for your distribution first:

```bash
sudo apt update
sudo apt install ros-noetic-moveit ros-noetic-realsense2-camera \
  ros-noetic-aruco-ros ros-noetic-trac-ik-kinematics-plugin
```

Then clone compatible ROS 1 versions of the following upstream projects into `Robot/ros_ws/src/` when they are not supplied by your package manager:

- [Universal Robots ROS Driver](https://github.com/UniversalRobots/Universal_Robots_ROS_Driver), including `ur_robot_driver`, `ur_calibration`, and `ur_dashboard_msgs`.
- [Universal Robots ROS-Industrial description](https://github.com/ros-industrial/universal_robot), including `ur_description` and `ur_kinematics` with UR30 assets.
- [RealSense ROS](https://github.com/IntelRealSense/realsense-ros), using its ROS 1 / Noetic-compatible branch.
- [aruco_ros](https://github.com/pal-robotics/aruco_ros), using its ROS 1 / Noetic-compatible branch.
- [easy_handeye](https://github.com/IFL-CAMP/easy_handeye), including `easy_handeye_msgs` and `rqt_easy_handeye`.
- A ROS 1 driver for the Robotiq 3F gripper that provides `robotiq_3f_gripper_articulated_msgs`, `robotiq_3f_gripper_control`, `robotiq_3f_gripper_joint_state_publisher`, and `robotiq_3f_gripper_visualization`.

Use package versions compatible with each other and ROS Noetic. Do not mix ROS 2 packages into this catkin workspace.

## Build

```bash
cd /path/to/RoboShelf
source /opt/ros/noetic/setup.bash
cd Robot/ros_ws/src
catkin_init_workspace
cd ../../..
rosdep install --from-paths Robot/ros_ws/src --ignore-src -r -y
./Robot/build_ros.sh
```

`rosdep` installs system dependencies; it does not replace a missing source package that is not released for your ROS distribution. Resolve all missing package errors before continuing.

## Verification

Before starting the Robot API in real mode, confirm the driver and MoveIt stack provide all of the following:

- a `robot_description` parameter;
- joint states for the configured planning group;
- the configured MoveIt group and `/compute_fk` service;
- a connected TF path from `reference_frame` to `end_effector_link` and to the configured camera frame;
- Robotiq command and status topics when using the supplied gripper adapter.

For another robot or gripper, follow [ADAPTATION.md](ADAPTATION.md) instead of using the UR30 startup scripts.
