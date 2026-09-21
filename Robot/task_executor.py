"""Thread-safe visual pick/place state machine."""

import copy
import logging
import threading
import time
import uuid
from datetime import datetime, timezone

RUNNING_STATES = {
    "QUEUED", "MOVING_TO_PICK", "GRASPING", "LIFTING",
    "MOVING_TO_PLACE", "RELEASING", "RETURNING_HOME",
}
LOGGER = logging.getLogger(__name__)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class TaskExecutor:
    def __init__(self, mock_mode, config, mock_step_delay=1.0):
        self.mock_mode = mock_mode
        self.config = config
        self.mock_step_delay = mock_step_delay
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._controller = None
        self._gripper = None
        self._vision = None
        self._startup_error = None
        self._moveit_ready = mock_mode
        self._gripper_ready = mock_mode
        self._vision_ready = mock_mode
        self._hardware_ready = mock_mode
        self._initializing = not mock_mode
        self._status = self._empty_status()
        if not mock_mode:
            thread = threading.Thread(
                target=self._initialize_real_hardware,
                name="robot-startup-initialization", daemon=True,
            )
            thread.start()

    def _empty_status(self):
        return {
            "task_id": None, "status": "IDLE", "step": "idle",
            "message": "机器人空闲", "error": None,
            "product_id": None, "product_name": None,
            "started_at": None, "finished_at": None,
        }

    def _initialize_real_hardware(self):
        try:
            from gripper_controller import create_gripper
            from moveit_controller import MoveItController
            from vision_detector import VisionDetector
        except Exception as exc:
            self._fail_startup(exc)
            return

        startup = self.config.get("startup", {})
        moveit_attempts = int(startup.get("moveit_attempts", 5))
        retry_interval = float(startup.get("retry_interval", 2.0))

        for attempt in range(1, moveit_attempts + 1):
            try:
                self._set(
                    "RETURNING_HOME", "startup_returning_home",
                    "正在连接 MoveIt 并返回 Home（{}/{}）".format(attempt, moveit_attempts),
                )
                LOGGER.info("Startup MoveIt/Home attempt %d/%d", attempt, moveit_attempts)
                controller = MoveItController(self.config)
                controller.check_connection()
                controller.move_home()
                with self._state_lock:
                    self._controller = controller
                    self._moveit_ready = True
                    self._startup_error = None
                break
            except Exception as exc:
                self._record_startup_retry("MoveIt/Home", attempt, moveit_attempts, exc)
                if attempt == moveit_attempts:
                    self._fail_startup(exc)
                    return
                time.sleep(retry_interval)

        try:
            self._set(
                "IDLE", "startup_initializing_vision",
                "机械臂已在 Home，正在连接 D405 和 YOLO 视觉模块",
            )
            LOGGER.info("Startup vision initialization")
            vision = VisionDetector(self.config["vision"])
            vision.check_connection()
            with self._state_lock:
                self._vision = vision
                self._vision_ready = True
                self._startup_error = None
        except Exception as exc:
            self._fail_startup(exc)
            return

        try:
            gripper = create_gripper(self.config["gripper"])
        except Exception as exc:
            self._fail_startup(exc)
            return
        try:
            self._set(
                "IDLE", "startup_initializing_gripper",
                "机械臂已在 Home，正在初始化夹爪",
            )
            LOGGER.info("Startup gripper initialization (single attempt)")
            if not gripper.check_connection():
                raise RuntimeError("Robotiq initialization returned false")
            gripper.open()
            with self._state_lock:
                self._gripper = gripper
                self._gripper_ready = True
                self._hardware_ready = True
                self._initializing = False
                self._startup_error = None
            self._set("IDLE", "idle", "机械臂位于 Home，夹爪初始化完成")
            LOGGER.info("Robot API startup initialization completed")
        except Exception as exc:
            self._fail_startup(exc)

    def _record_startup_retry(self, stage, attempt, attempts, exc):
        with self._state_lock:
            self._startup_error = "{}: {}".format(stage, exc)
        LOGGER.warning(
            "Startup %s attempt %d/%d failed: %s",
            stage, attempt, attempts, exc,
        )

    def _fail_startup(self, exc):
        with self._state_lock:
            self._initializing = False
            self._hardware_ready = False
            self._startup_error = str(exc)
            self._status.update(
                status="FAILED", step="startup_failed",
                message="Robot API 启动初始化失败", error=str(exc),
                finished_at=utc_now(),
            )
        LOGGER.error("Robot API startup initialization failed: %s", exc)

    def health(self):
        with self._state_lock:
            return {
                "service": "online", "mock_mode": self.mock_mode,
                "initializing": self._initializing,
                "moveit_connected": self._moveit_ready,
                "robot_connected": self._moveit_ready,
                "gripper_connected": self._gripper_ready,
                "vision_connected": self._vision_ready,
                "ready": self._hardware_ready,
                "error": self._startup_error,
            }

    def status(self):
        with self._state_lock:
            return copy.deepcopy(self._status)

    def start(self, product_id):
        product = self.config.get("products", {}).get(product_id)
        if product is None:
            raise ValueError("不支持的商品: {}".format(product_id))
        with self._state_lock:
            ready = self._hardware_ready
            initializing = self._initializing
            startup_error = self._startup_error
        if not ready:
            if initializing:
                raise RuntimeError("Robot startup initialization is still running")
            raise RuntimeError("Real hardware is not ready: {}".format(startup_error))
        if not self._lock.acquire(blocking=False):
            return None
        task_id = str(uuid.uuid4())
        product_name = product.get("name", product_id)
        self._set(
            "QUEUED", "queued", "{}任务已进入机器人队列".format(product_name),
            task_id=task_id, product_id=product_id, product_name=product_name,
            started_at=utc_now(), finished_at=None,
        )
        thread = threading.Thread(
            target=self._run, args=(product_id, product_name),
            name="pick-place-{}".format(task_id), daemon=True,
        )
        thread.start()
        return self.status()

    def _set(self, status, step, message, **extra):
        with self._state_lock:
            self._status.update(status=status, step=step, message=message, error=None, **extra)

    def _perform(self, status, step, message, action=None):
        self._set(status, step, message)
        if self.mock_mode:
            time.sleep(self.mock_step_delay)
        elif action is not None and action() is False:
            raise RuntimeError("Step returned failure: {}".format(step))

    def _return_home_with_open_gripper(self):
        if self.mock_mode:
            return True
        if self._gripper is not None:
            self._gripper.open()
        self._controller.move_home()
        if self._gripper is not None:
            self._gripper.open()
        return True

    def _run(self, product_id, product_name):
        try:
            product = self.config["products"][product_id]
            if not self.mock_mode:
                self._controller.remove_shelf_collision_scene()
                self._return_home_with_open_gripper()
                self._controller.select_product(product_id)
            self._perform("MOVING_TO_PICK", "moving_to_floor_pre_pick", "正在前往第 {} 层预抓取点".format(self.config["products"][product_id]["floor"]), None if self.mock_mode else self._controller.move_floor_pre_pick)
            self._perform("MOVING_TO_PICK", "detecting_product", "正在识别{}并计算抓取点".format(product_name), None if self.mock_mode else lambda: self._detect_and_set_pick_target(product_id))
            self._perform("MOVING_TO_PICK", "moving_before_pick", "正在从层预抓取点前往{}前方".format(product_name), None if self.mock_mode else self._controller.move_before_pick)
            self._perform("MOVING_TO_PICK", "approaching_pick", "正在水平移动至抓取点", None if self.mock_mode else self._controller.move_to_pick)
            self._perform("GRASPING", "closing_gripper", "正在抓取商品", None if self.mock_mode else self._gripper.close)
            self._perform("LIFTING", "lifting_product", "商品已抓取，正在竖直抬升 3 cm", None if self.mock_mode else self._controller.lift_after_grasp)
            self._perform("LIFTING", "retreating_from_shelf", "正在水平退出货架", None if self.mock_mode else self._controller.retreat_from_shelf)
            post_retreat_lift = float(product.get("post_retreat_lift", 0.0))
            if post_retreat_lift > 0.0:
                self._perform(
                    "LIFTING", "lifting_after_retreat",
                    "已退出货架，正在竖直上移 {:.0f} cm".format(post_retreat_lift * 100.0),
                    None if self.mock_mode else lambda: self._controller.lift_after_retreat(post_retreat_lift),
                )
            self._perform("MOVING_TO_PLACE", "enabling_shelf_collision", "已退出货架，正在启用货架防碰撞区域", None if self.mock_mode else self._controller.enable_shelf_collision_scene)
            self._perform("MOVING_TO_PLACE", "moving_above_place", "正在前往放置点上方 20 cm", None if self.mock_mode else self._controller.move_above_place)
            self._perform("MOVING_TO_PLACE", "descending_to_place", "正在缓慢下降至放置点", None if self.mock_mode else self._controller.move_to_place)
            self._perform("RELEASING", "opening_gripper", "正在将商品放入购物篮", None if self.mock_mode else self._gripper.open)
            self._perform("RETURNING_HOME", "lifting_from_place", "放置完成，正在上移 20 cm", None if self.mock_mode else self._controller.lift_from_place)
            self._perform("RETURNING_HOME", "returning_home", "机械臂正在返回 Home 并打开夹爪", None if self.mock_mode else self._return_home_with_open_gripper)
            if not self.mock_mode:
                self._controller.remove_shelf_collision_scene()
            self._set("SUCCESS", "completed", "{}已成功放入购物篮。".format(product_name), finished_at=utc_now())
        except Exception as exc:
            with self._state_lock:
                self._status.update(status="FAILED", step="failed", message="取货任务失败", error=str(exc), finished_at=utc_now())
        finally:
            self._lock.release()

    def _detect_and_set_pick_target(self, product_id):
        product = self.config["products"][product_id]
        detection = self._vision.locate(product_id, product)
        self._controller.set_visual_pick_target(detection)
        point = detection["point_base"]
        LOGGER.info(
            "Detected %s at base x=%.4f y=%.4f z=%.4f, depth=%.4f, conf=%.3f",
            product_id,
            point["x"], point["y"], point["z"],
            detection["depth_m"],
            detection["confidence"],
        )
        return True
