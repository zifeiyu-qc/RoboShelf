# Adapting RoboShelf to Another Robot

RoboShelf separates the order/Web layer, visual target calculation, MoveIt motion logic, and the UR30-specific ROS integration. The Web API, `task_executor.py`, `moveit_controller.py`, and `vision_detector.py` can be reused with a different arm that has a ROS 1 MoveIt 1 integration. The included UR30 driver, URDF, MoveIt package, calibration, poses, and Robotiq 3F driver scripts cannot be reused unchanged on another robot.

## Compatibility contract

Before using `MOCK_MODE=false`, the target system must provide:

- ROS 1 and MoveIt 1 with a planning group capable of Cartesian trajectories;
- current joint states and the `/compute_fk` service;
- a TF tree connecting the selected base/reference frame, end-effector link, and RGB-D camera frame;
- an RGB image, aligned depth image, and camera-info topic compatible with `sensor_msgs/Image` and `sensor_msgs/CameraInfo`;
- a gripper adapter implementing `check_connection()`, `open()`, and `close()`.

The core motion code accepts any number of joints. It validates every configured joint target against the active MoveIt group before commanding motion.

## Porting procedure

1. Start in mock mode and confirm the Robot and Web APIs work without ROS:

   ```bash
   MOCK_MODE=true ./Robot/start_robot.sh
   ROBOT_SERVER_URL=http://127.0.0.1:8001 ./Web/start_web.sh
   ```

2. Install the target robot vendor's ROS 1 driver and create a MoveIt configuration for the actual arm, tool, and collision model with the MoveIt Setup Assistant. Start the vendor driver and your MoveIt launch files independently. Do not use `start_ur30_driver.sh`, `start_moveit.sh`, or the UR30 packages for another arm.

3. Edit `Robot/config/poses.yaml` for the new MoveIt configuration:

   - Set `move_group`, `end_effector_link`, `reference_frame`, and `fk_service` to names exposed by the target stack.
   - Replace `home_joint_values_deg`, `place_joint_values_deg`, and each floor pre-pick vector. Every vector must use the exact joint order and joint count returned by `MoveGroup.get_active_joints()`.
   - Re-measure or disable `shelf_collision` during initial RViz-only testing. Never retain the UR30 shelf dimensions or pose.
   - Update the `motion` approach axis, clearances, speed/acceleration scaling, and Cartesian path thresholds. Begin with slower values than the reference configuration.

4. Add the target RGB-D camera topics and frame names under `vision` in `Robot/config/poses.yaml`. Train a matching YOLO model, put it at `Robot/vision/model/best.pt`, and perform a new hand-eye calibration. Do not reuse the checked-in calibration.

5. Integrate the gripper. The supplied `robotiq_3f_topic` adapter only supports a Robotiq 3F topic driver. For another gripper, add an adapter to `Robot/gripper_controller.py` that exposes `check_connection()`, `open()`, and `close()`, register it in `create_gripper()`, and set its `type` plus its parameters under `gripper` in `poses.yaml`.

6. Validate in RViz without hardware motion, then at low speed with an empty shelf: Home, each floor pre-pick pose, camera/TF connectivity, a single Cartesian approach, gripper commands, and the retreat/place paths. Only then start `MOCK_MODE=false ./Robot/start_robot.sh` after sourcing your own robot workspace.

## Required configuration relationships

Keep these identifiers synchronized:

```text
Web/backend/catalog.py product_id
        = Robot/config/poses.yaml products.<product_id>
        = YOLO class name in products.<product_id>.yolo_class

poses.yaml move_group / end_effector_link / reference_frame
        = names published by the target MoveIt and TF stack

poses.yaml vision.*_topic and *_frame
        = names published by the selected RGB-D camera and calibration setup
```

## Safety boundary

Porting this code is a robotics integration task, not a configuration-only change. The maintainer of the new cell is responsible for the robot model, tool center point, collision scene, velocity limits, workspace guarding, controller behavior, and emergency stop. Validate every change in simulation/RViz and at reduced speed before operating around people or equipment.
