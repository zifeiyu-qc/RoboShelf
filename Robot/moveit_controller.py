"""MoveIt 1 adapter using visual pick targets generated at runtime."""

import copy
import inspect
import math
import sys
import time


class MoveItController:
    def __init__(self, config):
        import moveit_commander
        import rospy
        from moveit_msgs.srv import GetPositionFK

        moveit_commander.roscpp_initialize(sys.argv)
        if not rospy.core.is_initialized():
            rospy.init_node("supermarket_robot_service", anonymous=True, disable_signals=True)

        self._rospy = rospy
        self.robot = moveit_commander.RobotCommander()
        self.scene = moveit_commander.PlanningSceneInterface(synchronous=True)
        self.group = moveit_commander.MoveGroupCommander(config["move_group"])
        self.config = config
        if config.get("reference_frame"):
            self.group.set_pose_reference_frame(config["reference_frame"])
        if config.get("end_effector_link"):
            self.group.set_end_effector_link(config["end_effector_link"])
        self._end_effector_link = self.group.get_end_effector_link()
        self._joint_names = self.group.get_active_joints()
        self._fk_service_name = config.get("fk_service", "/compute_fk")
        self._fk = rospy.ServiceProxy(self._fk_service_name, GetPositionFK)
        self.group.set_max_velocity_scaling_factor(float(config["velocity_scale"]))
        self.group.set_max_acceleration_scaling_factor(float(config["acceleration_scale"]))
        self.group.set_planning_time(float(config.get("planning_time", 8.0)))
        self.group.set_num_planning_attempts(int(config.get("planning_attempts", 8)))
        self._pick_pose = None
        self._product_id = None
        self._place_pose = None
        self._approach_direction = None
        self._selected_product = None
        self._last_visual_detection = None

    def check_connection(self):
        configured = self.config["move_group"]
        if configured not in self.robot.get_group_names():
            raise RuntimeError("MoveIt planning group not found: {}".format(configured))
        if not self.group.get_current_joint_values():
            raise RuntimeError("No current joint state received from UR30")
        if not self._end_effector_link:
            raise RuntimeError("MoveIt group has no end-effector link; configure end_effector_link")
        self._rospy.wait_for_service(self._fk_service_name, timeout=5.0)
        self._place_pose = self._fk_pose(self.config["place_joint_values_deg"], "place")
        # A previous API process or failed task may have left these objects in
        # MoveIt's shared planning scene. Picking starts with the shelf open.
        self.remove_shelf_collision_scene()
        for floor, joints in self.config.get("floor_pre_pick_joint_values_deg", {}).items():
            self._validate_joint_count(joints, "floor {} pre-pick".format(floor))
        for product_id, product in self.config["products"].items():
            self._floor_pre_pick_joints(product, product_id)
            if not product.get("yolo_class"):
                raise RuntimeError("{} missing yolo_class".format(product_id))
        return True

    def enable_shelf_collision_scene(self):
        self._apply_shelf_collision_scene()
        return True

    def remove_shelf_collision_scene(self):
        """Remove configured shelf objects and wait until MoveIt forgets them."""
        collision = self.config.get("shelf_collision", {})
        object_ids = [
            str(box.get("id", "")).strip()
            for box in collision.get("boxes", [])
            if str(box.get("id", "")).strip()
        ]
        if not object_ids:
            return True

        for object_id in object_ids:
            self.scene.remove_world_object(object_id)

        timeout = float(collision.get("wait_timeout", 2.0))
        deadline = time.monotonic() + max(0.0, timeout)
        remaining = set(object_ids)
        while remaining and time.monotonic() <= deadline and not self._rospy.is_shutdown():
            known = set(self.scene.get_known_object_names())
            remaining.intersection_update(known)
            if remaining:
                self._rospy.sleep(0.05)
        if remaining:
            raise RuntimeError(
                "MoveIt planning scene did not remove collision objects: {}".format(
                    ", ".join(sorted(remaining))
                )
            )
        self._rospy.loginfo("Removed shelf collision objects: %s", ", ".join(object_ids))
        return True

    def _apply_shelf_collision_scene(self):
        """Add configured shelf collision boxes and wait until MoveIt sees them."""
        collision = self.config.get("shelf_collision", {})
        if not collision.get("enabled", False):
            return

        from geometry_msgs.msg import PoseStamped

        boxes = collision.get("boxes", [])
        if not boxes:
            raise RuntimeError("shelf_collision is enabled but no boxes are configured")

        frame = collision.get("frame") or self.config.get("reference_frame")
        if not frame:
            raise RuntimeError("shelf_collision requires a frame")

        object_ids = []
        for box in boxes:
            object_id = str(box.get("id", "")).strip()
            size = box.get("size", [])
            position = box.get("position", [])
            orientation = box.get("orientation", [0.0, 0.0, 0.0, 1.0])
            if not object_id:
                raise RuntimeError("shelf_collision box is missing an id")
            if len(size) != 3 or any(float(value) <= 0.0 for value in size):
                raise RuntimeError("{} must have three positive size values".format(object_id))
            if len(position) != 3:
                raise RuntimeError("{} must have three position values".format(object_id))
            if len(orientation) != 4:
                raise RuntimeError("{} must have four quaternion values".format(object_id))

            quaternion = [float(value) for value in orientation]
            norm = math.sqrt(sum(value * value for value in quaternion))
            if norm < 1e-9:
                raise RuntimeError("{} orientation quaternion must not be zero".format(object_id))
            quaternion = [value / norm for value in quaternion]

            pose = PoseStamped()
            pose.header.frame_id = frame
            pose.header.stamp = self._rospy.Time.now()
            pose.pose.position.x, pose.pose.position.y, pose.pose.position.z = (
                float(value) for value in position
            )
            (
                pose.pose.orientation.x,
                pose.pose.orientation.y,
                pose.pose.orientation.z,
                pose.pose.orientation.w,
            ) = quaternion
            self.scene.add_box(object_id, pose, size=tuple(float(value) for value in size))
            object_ids.append(object_id)

        timeout = float(collision.get("wait_timeout", 2.0))
        deadline = time.monotonic() + max(0.0, timeout)
        missing = set(object_ids)
        while missing and time.monotonic() <= deadline and not self._rospy.is_shutdown():
            missing.difference_update(self.scene.get_known_object_names())
            if missing:
                self._rospy.sleep(0.05)
        if missing:
            raise RuntimeError(
                "MoveIt planning scene did not load collision objects: {}".format(
                    ", ".join(sorted(missing))
                )
            )
        self._rospy.loginfo("Loaded shelf collision objects: %s", ", ".join(object_ids))

    def select_product(self, product_id):
        product = self.config.get("products", {}).get(product_id)
        if product is None:
            raise RuntimeError("Unknown configured product: {}".format(product_id))
        self._pick_pose = None
        self._approach_direction = None
        self._product_id = product_id
        self._selected_product = product
        self._rospy.loginfo("Selected visual pick target: %s", product_id)
        return True

    def set_visual_pick_target(self, detected_target):
        """Set the pick pose from a detector result in the reference frame.

        The detector provides the object center in base/reference frame. The
        actual grasp target is lifted by vision.pick_z_offset to reduce shelf
        board collisions on short objects. Orientation is inherited from the
        current end-effector pose at the floor pre-pick point.
        """
        if self._product_id is None:
            raise RuntimeError("Select a product before setting a visual pick target")
        point = detected_target["point_base"]
        current = self.group.get_current_pose(self._end_effector_link).pose
        target = copy.deepcopy(current)
        target.position.x = float(point["x"])
        target.position.y = float(point["y"])
        pick_z_offset = float(
            self._selected_product.get(
                "pick_z_offset",
                self.config.get("vision", {}).get("pick_z_offset", 0.02),
            )
        )
        target.position.z = float(point["z"]) + pick_z_offset

        # The depth point comes from the detected object, but MoveIt controls
        # the palm link. Keep the palm slightly outside the object so the
        # fingers close around it instead of pushing it deeper into the shelf.
        approach_direction = self._horizontal_tool_axis(target)
        grasp_depth_offset = float(
            self._selected_product.get(
                "grasp_depth_offset",
                self.config.get("motion", {}).get("grasp_depth_offset", 0.0),
            )
        )
        target.position.x -= approach_direction[0] * grasp_depth_offset
        target.position.y -= approach_direction[1] * grasp_depth_offset

        self._pick_pose = target
        self._approach_direction = approach_direction
        self._last_visual_detection = copy.deepcopy(detected_target)
        self._rospy.loginfo(
            "Visual pick target for %s: x=%.4f y=%.4f z=%.4f conf=%.3f palm_offset=%.3f",
            self._product_id,
            target.position.x,
            target.position.y,
            target.position.z,
            float(detected_target.get("confidence", 0.0)),
            grasp_depth_offset,
        )
        return True

    def _floor_pre_pick_joints(self, product, product_id):
        floor = product.get("floor")
        if floor not in (1, 2, 3):
            raise RuntimeError("{} has invalid floor: {}".format(product_id, floor))
        floor_targets = self.config.get("floor_pre_pick_joint_values_deg", {})
        joints = floor_targets.get(floor, floor_targets.get(str(floor)))
        if joints is None:
            raise RuntimeError("No pre-pick joints configured for floor {}".format(floor))
        self._validate_joint_count(joints, "floor {} pre-pick".format(floor))
        return joints

    @staticmethod
    def _radians(values):
        return [math.radians(float(value)) for value in values]

    def _validate_joint_count(self, values, label):
        if len(values) != len(self._joint_names):
            raise RuntimeError(
                "{} has {} joints but MoveIt group expects {}: {}".format(
                    label, len(values), len(self._joint_names), self._joint_names
                )
            )

    def _fk_pose(self, joint_values_deg, label):
        from moveit_msgs.msg import MoveItErrorCodes, RobotState
        from moveit_msgs.srv import GetPositionFKRequest
        from sensor_msgs.msg import JointState

        self._validate_joint_count(joint_values_deg, label)
        request = GetPositionFKRequest()
        request.header.frame_id = self.config["reference_frame"]
        request.fk_link_names = [self._end_effector_link]
        request.robot_state = RobotState(
            joint_state=JointState(
                name=list(self._joint_names),
                position=self._radians(joint_values_deg),
            )
        )
        response = self._fk(request)
        if response.error_code.val != MoveItErrorCodes.SUCCESS or not response.pose_stamped:
            raise RuntimeError("MoveIt FK failed for {} (code {})".format(label, response.error_code.val))
        stamped = response.pose_stamped[0]
        if stamped.header.frame_id.lstrip("/") != self.config["reference_frame"].lstrip("/"):
            raise RuntimeError(
                "FK frame {} does not match reference frame {}".format(
                    stamped.header.frame_id, self.config["reference_frame"]
                )
            )
        return copy.deepcopy(stamped.pose)

    def _horizontal_tool_axis(self, pose):
        axis = [float(value) for value in self.config["motion"]["approach_axis_local"]]
        norm = math.sqrt(sum(value * value for value in axis))
        if norm < 1e-9:
            raise RuntimeError("motion.approach_axis_local must not be zero")
        vx, vy, vz = [value / norm for value in axis]
        q = pose.orientation
        # Rotate a vector by quaternion q using v' = v + 2w(q_xyz x v)
        # + 2(q_xyz x (q_xyz x v)).
        tx = 2.0 * (q.y * vz - q.z * vy)
        ty = 2.0 * (q.z * vx - q.x * vz)
        tz = 2.0 * (q.x * vy - q.y * vx)
        wx = vx + q.w * tx + (q.y * tz - q.z * ty)
        wy = vy + q.w * ty + (q.z * tx - q.x * tz)
        horizontal_norm = math.hypot(wx, wy)
        if horizontal_norm < 1e-4:
            raise RuntimeError("Configured tool approach axis is vertical at the pick target")
        return [wx / horizontal_norm, wy / horizontal_norm, 0.0]

    def _execute_pose(self, pose, label):
        self.group.set_pose_target(pose, self._end_effector_link)
        try:
            success = bool(self.group.go(wait=True))
        finally:
            self.group.stop()
            self.group.clear_pose_targets()
        if not success:
            raise RuntimeError("MoveIt failed: {}; target x={:.4f} y={:.4f} z={:.4f}".format(
                label, pose.position.x, pose.position.y, pose.position.z
            ))

    def move_home(self):
        self._move_joints(self.config["home_joint_values_deg"], "home")

    def move_floor_pre_pick(self):
        if self._product_id is None:
            raise RuntimeError("Select a product before moving to a floor pre-pick point")
        product = self.config["products"][self._product_id]
        floor = product["floor"]
        self._move_joints(
            self._floor_pre_pick_joints(product, self._product_id),
            "floor {} pre-pick".format(floor),
        )

    def _move_joints(self, joints, label):
        self._validate_joint_count(joints, label)
        if not self.group.go(self._radians(joints), wait=True):
            raise RuntimeError("MoveIt failed: {}".format(label))
        self.group.stop()

    def move_before_pick(self):
        if self._pick_pose is None or self._approach_direction is None:
            raise RuntimeError("Visual pick target has not been detected")
        distance = float(self.config["motion"]["pick_approach_distance"])
        target = copy.deepcopy(self._pick_pose)
        target.position.x -= self._approach_direction[0] * distance
        target.position.y -= self._approach_direction[1] * distance
        label = (
            "{:.0f} cm before visual pick; pick x={:.4f} y={:.4f} z={:.4f}; "
            "approach dx={:.3f} dy={:.3f}"
        ).format(
            distance * 100.0,
            self._pick_pose.position.x, self._pick_pose.position.y, self._pick_pose.position.z,
            self._approach_direction[0], self._approach_direction[1],
        )
        current = self.group.get_current_pose(self._end_effector_link).pose

        dz = target.position.z - current.position.z
        if abs(dz) > 1e-4:
            self._cartesian_delta([0.0, 0.0, dz], label + " vertical align")

        current = self.group.get_current_pose(self._end_effector_link).pose
        dx = target.position.x - current.position.x
        dy = target.position.y - current.position.y
        if math.hypot(dx, dy) > 1e-4:
            self._cartesian_delta([dx, dy, 0.0], label + " shelf-front horizontal align")

    def move_to_pick(self):
        if self._approach_direction is None:
            raise RuntimeError("Visual pick target has not been detected")
        distance = float(self.config["motion"]["pick_approach_distance"])
        self._cartesian_delta(
            [self._approach_direction[0] * distance,
             self._approach_direction[1] * distance, 0.0],
            "horizontal approach to pick",
        )

    def lift_after_grasp(self):
        self._cartesian_delta(
            [0.0, 0.0, float(self.config["motion"]["post_grasp_lift"])],
            "3 cm lift after grasp",
        )

    def retreat_from_shelf(self):
        distance = float(self.config["motion"]["shelf_retreat_distance"])
        self._cartesian_delta(
            [-self._approach_direction[0] * distance,
             -self._approach_direction[1] * distance, 0.0],
            "horizontal retreat from shelf",
        )

    def lift_after_retreat(self, distance):
        distance = float(distance)
        if distance <= 0.0:
            raise RuntimeError("Post-retreat lift distance must be positive")
        self._cartesian_delta(
            [0.0, 0.0, distance],
            "{:.0f} cm vertical lift after shelf retreat".format(distance * 100.0),
        )

    def move_above_place(self):
        target = copy.deepcopy(self._place_pose)
        target.position.z += float(self.config["motion"]["place_clearance"])
        self._execute_pose(
            target,
            "{:.0f} cm above place".format(float(self.config["motion"]["place_clearance"]) * 100.0),
        )

    def move_to_place(self):
        self._cartesian_delta(
            [0.0, 0.0, -float(self.config["motion"]["place_clearance"])],
            "slow descent to place",
            self.config.get("place_descent_velocity_scale", 0.025),
        )

    def lift_from_place(self):
        self._cartesian_delta(
            [0.0, 0.0, float(self.config["motion"]["place_clearance"])],
            "{:.0f} cm lift from place".format(float(self.config["motion"]["place_clearance"]) * 100.0),
        )

    def _cartesian_delta(self, delta, label, velocity_scale=None):
        target = copy.deepcopy(self.group.get_current_pose(self._end_effector_link).pose)
        target.position.x += float(delta[0])
        target.position.y += float(delta[1])
        target.position.z += float(delta[2])
        self.group.set_start_state_to_current_state()
        plan, fraction = self._compute_cartesian_path([target])
        if fraction < float(self.config.get("min_cartesian_fraction", 0.98)):
            raise RuntimeError("{} path fraction {:.3f}".format(label, fraction))
        if not plan.joint_trajectory.points:
            raise RuntimeError("MoveIt returned an empty Cartesian trajectory: {}".format(label))
        scale = float(velocity_scale or self.config.get("cartesian_velocity_scale", 0.05))
        plan = self.group.retime_trajectory(
            self.robot.get_current_state(), plan,
            velocity_scaling_factor=scale,
            acceleration_scaling_factor=float(self.config.get("acceleration_scale", 0.05)),
        )
        if not self.group.execute(plan, wait=True):
            raise RuntimeError("MoveIt failed: {}".format(label))
        self.group.stop()

    def _compute_cartesian_path(self, waypoints):
        """Call either MoveIt Python API without confusing bool and float args."""
        method = self.group.compute_cartesian_path
        parameters = inspect.signature(method).parameters
        step = float(self.config.get("cartesian_step", 0.005))
        if "jump_threshold" in parameters:
            return method(waypoints, step, 0.0, True)
        return method(waypoints, step, True)
