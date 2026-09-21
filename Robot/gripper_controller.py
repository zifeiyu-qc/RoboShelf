"""Mock and feedback-verified Robotiq 3F ROS gripper adapters."""

import copy
import threading
import time


class MockGripper:
    def __init__(self, delay=0.5):
        self.delay = delay

    def check_connection(self):
        return True

    def open(self):
        time.sleep(self.delay)
        return True

    def close(self):
        time.sleep(self.delay)
        return True


class Robotiq3FTopicGripper:
    """Controls and verifies the bundled Robotiq 3F TCP ROS driver."""

    def __init__(self, config):
        import rospy
        from robotiq_3f_gripper_articulated_msgs.msg import (
            Robotiq3FGripperRobotInput,
            Robotiq3FGripperRobotOutput,
        )

        self._rospy = rospy
        self._message_type = Robotiq3FGripperRobotOutput
        self._config = config
        self._condition = threading.Condition()
        self._initialization_lock = threading.Lock()
        self._initialized = False
        self._activated = False
        self._status = None
        self._subscriber = rospy.Subscriber(
            config["status_topic"], Robotiq3FGripperRobotInput,
            self._status_callback, queue_size=1,
        )
        self._publisher = rospy.Publisher(
            config["command_topic"], Robotiq3FGripperRobotOutput,
            queue_size=1, latch=True,
        )

    def _status_callback(self, message):
        with self._condition:
            self._status = message
            self._condition.notify_all()

    def _status_snapshot(self):
        with self._condition:
            return copy.deepcopy(self._status)

    @staticmethod
    def _fault(status):
        # 0x05..0x07 are transient activation/mode-change states.
        if status is None or int(status.gFLT) < 0x09:
            return None
        return "Robotiq fault 0x{:02X}".format(int(status.gFLT))

    @staticmethod
    def _status_text(status):
        if status is None:
            return "no feedback"
        return (
            "gACT={} gMOD={} gIMC={} gSTA={} gFLT=0x{:02X} "
            "gPRA={} gPOA={} contacts=({},{},{})"
        ).format(
            status.gACT, status.gMOD, status.gIMC, status.gSTA,
            int(status.gFLT), status.gPRA, status.gPOA,
            status.gDTA, status.gDTB, status.gDTC,
        )

    def _message(self, position):
        message = self._message_type()
        message.rACT = 1
        message.rMOD = int(self._config.get("mode", 1))
        message.rGTO = 1
        message.rPRA = int(position)
        message.rSPA = int(self._config.get("speed", 100))
        message.rFRA = int(self._config.get("force", 100))
        return message

    def check_connection(self):
        with self._initialization_lock:
            if self._initialized:
                return True
            return self._initialize_once()

    def _initialize_once(self):
        timeout = float(self._config.get("feedback_timeout", 3.0))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._rospy.is_shutdown():
            if self._publisher.get_num_connections() > 0:
                break
            self._rospy.sleep(0.05)
        else:
            raise RuntimeError(
                "No subscriber on Robotiq command topic {}".format(
                    self._config["command_topic"]
                )
            )

        with self._condition:
            while self._status is None and not self._rospy.is_shutdown():
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    raise RuntimeError(
                        "No Robotiq feedback on {}".format(self._config["status_topic"])
                    )
                self._condition.wait(timeout=min(0.1, remaining))

        self._activate()
        self._move(closed=False, startup=True)
        self._initialized = True
        return True

    def _activate(self):
        if self._activated:
            return
        status = self._status_snapshot()
        fault = self._fault(status)
        if fault:
            raise RuntimeError(fault + " before activation")
        if status is not None and status.gACT == 1 and status.gIMC == 3:
            self._rospy.loginfo("Robotiq already active: %s", self._status_text(status))
            self._activated = True
            return

        reset = self._message_type()
        reset.rACT = 0
        self._publisher.publish(reset)
        self._rospy.sleep(0.3)

        activate = self._message(self._config.get("open_position", 0))
        deadline = time.monotonic() + float(
            self._config.get("activation_timeout", 10.0)
        )
        next_publish = 0.0
        while time.monotonic() < deadline and not self._rospy.is_shutdown():
            now = time.monotonic()
            if now >= next_publish:
                self._publisher.publish(activate)
                next_publish = now + float(self._config.get("resend_period", 0.25))
            status = self._status_snapshot()
            fault = self._fault(status)
            if fault:
                raise RuntimeError(fault + " during activation")
            if status is not None and status.gACT == 1 and status.gIMC == 3:
                self._rospy.loginfo("Robotiq activation completed: %s", self._status_text(status))
                self._activated = True
                return
            self._rospy.sleep(0.05)
        raise RuntimeError(
            "Robotiq activation timed out: {}".format(
                self._status_text(self._status_snapshot())
            )
        )

    def _move(self, closed, startup=False):
        target = int(self._config.get("close_position" if closed else "open_position", 255 if closed else 0))
        command = self._message(target)
        initial = self._status_snapshot()
        initial_position = int(initial.gPOA) if initial is not None else None
        timeout_key = "closing_timeout" if closed else "opening_timeout"
        timeout = float(self._config.get(timeout_key, self._config.get("command_timeout", 6.0)))
        deadline = time.monotonic() + timeout
        resend_period = float(self._config.get("resend_period", 0.25))
        tolerance = int(self._config.get("position_tolerance", 5))
        next_publish = 0.0

        while time.monotonic() < deadline and not self._rospy.is_shutdown():
            now = time.monotonic()
            if now >= next_publish:
                self._publisher.publish(command)
                next_publish = now + resend_period

            status = self._status_snapshot()
            fault = self._fault(status)
            if fault:
                raise RuntimeError(fault + " while commanding gripper")
            if status is None or status.gACT != 1 or status.gIMC != 3:
                self._rospy.sleep(0.05)
                continue
            if int(status.gPRA) != target:
                self._rospy.sleep(0.05)
                continue

            reached_target = abs(int(status.gPOA) - target) <= tolerance
            position_changed = (
                initial_position is None
                or abs(int(status.gPOA) - initial_position) > tolerance
            )
            contacts = (int(status.gDTA), int(status.gDTB), int(status.gDTC))
            closing_contact = any(value == 2 for value in contacts)
            stopped_before_target = int(status.gSTA) in (1, 2)

            if closed:
                if closing_contact or stopped_before_target:
                    self._rospy.loginfo("Robotiq grasp contact: %s", self._status_text(status))
                    return True
                # gPOA is mode-dependent and is not directly comparable with
                # rPRA in every Robotiq mode (notably Pinch mode). gSTA/gDT* are
                # the authoritative motion and contact results.
                if int(status.gSTA) == 3:
                    if bool(self._config.get("require_object_contact", True)):
                        raise RuntimeError(
                            "Robotiq completed closing without detecting the object: {}".format(
                                self._status_text(status)
                            )
                        )
                    self._rospy.loginfo("Robotiq close confirmed: %s", self._status_text(status))
                    return True
            else:
                open_threshold = int(self._config.get("open_position_threshold", 30))
                if reached_target or (
                    status.gSTA == 3 and int(status.gPOA) <= open_threshold
                ):
                    self._rospy.loginfo("Robotiq open confirmed: %s", self._status_text(status))
                    return True

            if not position_changed and not startup:
                self._rospy.sleep(0.05)
                continue
            self._rospy.sleep(0.05)

        raise RuntimeError(
            "Robotiq {} timed out: {}".format(
                "close" if closed else "open",
                self._status_text(self._status_snapshot()),
            )
        )

    def open(self):
        return self._move(closed=False)

    def close(self):
        return self._move(closed=True)


def create_gripper(config):
    """Return the configured gripper adapter.

    Add another adapter with ``check_connection()``, ``open()``, and ``close()``
    methods here when integrating a different end effector.
    """
    gripper_type = config.get("type", "robotiq_3f_topic")
    if gripper_type == "robotiq_3f_topic":
        return Robotiq3FTopicGripper(config)
    raise RuntimeError(
        "Unsupported gripper type: {}. Add an adapter in gripper_controller.py "
        "with check_connection(), open(), and close().".format(gripper_type)
    )
