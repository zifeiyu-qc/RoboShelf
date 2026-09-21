"""YOLO + D405 depth detector for dynamic supermarket pick targets."""

import math
import struct
import zlib
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np


class VisionDetector:
    def __init__(self, config):
        import rospy
        import tf2_ros
        from sensor_msgs.msg import CameraInfo, Image
        from ultralytics import YOLO

        self.config = config
        self._rospy = rospy
        self._lock = threading.Lock()
        self._image_msg = None
        self._depth_msg = None
        self._camera_info = None
        self._base_frame = config.get("base_frame", "base_link")
        self._camera_frame = config.get("camera_frame", "camera_infra1_optical_frame")
        self._model = YOLO(config["model_path"])
        self._names = self._normalize_names(getattr(self._model, "names", {}))
        self._tf_buffer = tf2_ros.Buffer(rospy.Duration(30.0))
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer)
        self._image_sub = rospy.Subscriber(
            config["image_topic"], Image, self._image_callback, queue_size=1
        )
        self._depth_sub = rospy.Subscriber(
            config["depth_topic"], Image, self._depth_callback, queue_size=1
        )
        self._camera_info_sub = rospy.Subscriber(
            config["camera_info_topic"], CameraInfo, self._camera_info_callback, queue_size=1
        )

    @staticmethod
    def _normalize_names(names):
        if isinstance(names, dict):
            return {int(k): str(v) for k, v in names.items()}
        return {index: str(name) for index, name in enumerate(names)}

    def check_connection(self):
        deadline = time.time() + float(self.config.get("image_timeout", 5.0))
        while time.time() < deadline and not self._rospy.is_shutdown():
            with self._lock:
                ready = self._image_msg is not None and self._depth_msg is not None and self._camera_info is not None
            if ready:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError(
                "Vision topics not ready: image={}, depth={}, camera_info={}".format(
                    self.config["image_topic"],
                    self.config["depth_topic"],
                    self.config["camera_info_topic"],
                )
            )
        try:
            self._tf_buffer.lookup_transform(
                self._base_frame,
                self._camera_frame,
                self._rospy.Time(0),
                self._rospy.Duration(float(self.config.get("tf_timeout", 2.0))),
            )
        except Exception as exc:
            raise RuntimeError(
                "Vision TF is disconnected: {} -> {}. Start and keep "
                "Robot/start_handeye_publish.sh running; also verify the UR30 "
                "robot_state_publisher publishes the configured end-effector frame. "
                "Original error: {}".format(
                    self._base_frame, self._camera_frame, exc
                )
            )
        return True

    def locate(self, product_id, product):
        yolo_class = str(product.get("yolo_class", product_id))
        image_msg, depth_msg, camera_info = self._wait_for_frames()
        image = self._image_to_yolo_array(image_msg)
        result = self._model.predict(
            source=image,
            conf=float(self.config.get("confidence_threshold", 0.45)),
            iou=float(self.config.get("iou_threshold", 0.50)),
            verbose=False,
        )[0]
        detection = self._select_detection(result, yolo_class)
        depth = self._depth_to_meters(depth_msg)
        u, v, depth_m = self._target_depth(depth, detection["bbox"])
        point_camera = self._deproject(u, v, depth_m, camera_info)
        point_base = self._transform_point(point_camera)
        pick_pixel = self._project_base_pick_to_pixel(point_base, camera_info)
        detection.update({
            "pixel": {"u": float(u), "v": float(v)},
            "pick_pixel": {"u": float(pick_pixel[0]), "v": float(pick_pixel[1])},
            "depth_m": float(depth_m),
            "point_camera": {
                "x": float(point_camera[0]),
                "y": float(point_camera[1]),
                "z": float(point_camera[2]),
            },
            "point_base": {
                "x": float(point_base[0]),
                "y": float(point_base[1]),
                "z": float(point_base[2]),
            },
        })
        self._save_debug_image(product_id, image, detection)
        return detection

    def _project_base_pick_to_pixel(self, point_base, camera_info):
        pick_z_offset = float(self.config.get("pick_z_offset", 0.03))
        point_base_pick = np.array([
            float(point_base[0]),
            float(point_base[1]),
            float(point_base[2]) + pick_z_offset,
        ], dtype=np.float64)
        transform = self._tf_buffer.lookup_transform(
            self._camera_frame,
            self._base_frame,
            self._rospy.Time(0),
            self._rospy.Duration(float(self.config.get("tf_timeout", 2.0))),
        )
        t = transform.transform.translation
        q = transform.transform.rotation
        point_camera = self._rotate_vector(point_base_pick, [q.x, q.y, q.z, q.w]) + np.array([t.x, t.y, t.z], dtype=np.float64)
        if point_camera[2] <= 1e-6:
            return [float("nan"), float("nan")]
        fx = float(camera_info.K[0])
        fy = float(camera_info.K[4])
        cx = float(camera_info.K[2])
        cy = float(camera_info.K[5])
        return [fx * point_camera[0] / point_camera[2] + cx, fy * point_camera[1] / point_camera[2] + cy]

    def _save_debug_image(self, product_id, image, detection):
        if not self.config.get("debug_save_images", False):
            return
        debug_dir = Path(self.config.get("debug_dir", "/tmp/supermarket_vision_debug"))
        debug_dir.mkdir(parents=True, exist_ok=True)
        canvas = self._debug_canvas(image)
        bbox = detection["bbox"]
        x1, y1, x2, y2 = [int(round(bbox[key])) for key in ("x1", "y1", "x2", "y2")]
        center = detection["pixel"]
        pick = detection.get("pick_pixel", center)
        self._draw_rect(canvas, x1, y1, x2, y2, color=(0, 255, 0))
        self._draw_cross(canvas, int(round(center["u"])), int(round(center["v"])), color=(255, 0, 0), size=10)
        if math.isfinite(float(pick["u"])) and math.isfinite(float(pick["v"])):
            self._draw_cross(canvas, int(round(pick["u"])), int(round(pick["v"])), color=(0, 0, 255), size=12)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        point = detection["point_base"]
        image_format = str(self.config.get("debug_image_format", "png")).lower().lstrip(".")
        if image_format not in ("png", "jpg", "jpeg"):
            self._rospy.logwarn(
                "Unsupported debug_image_format=%s; falling back to png",
                image_format,
            )
            image_format = "png"
        extension = "jpg" if image_format == "jpeg" else image_format
        meta = (
            "{}_{}_conf{:.2f}_depth{:.3f}_center{:.0f}-{:.0f}_pick{:.0f}-{:.0f}_base{:.3f}-{:.3f}-{:.3f}.{}"
        ).format(
            stamp, product_id, float(detection.get("confidence", 0.0)), float(detection.get("depth_m", 0.0)),
            float(center["u"]), float(center["v"]), float(pick["u"]), float(pick["v"]),
            point["x"], point["y"], point["z"], extension,
        )
        path = debug_dir / self._safe_filename(meta)
        self._write_debug_image(path, canvas, extension)
        self._rospy.loginfo("Saved vision debug image: %s", str(path))

    @staticmethod
    def _safe_filename(value):
        return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)

    @staticmethod
    def _debug_canvas(image):
        if image.ndim == 2:
            canvas = np.repeat(image[:, :, None], 3, axis=2)
        else:
            canvas = image[:, :, :3].copy()
        if canvas.dtype != np.uint8:
            min_value = float(np.nanmin(canvas)) if canvas.size else 0.0
            max_value = float(np.nanmax(canvas)) if canvas.size else 1.0
            scale = 255.0 / max(max_value - min_value, 1e-6)
            canvas = np.clip((canvas - min_value) * scale, 0, 255).astype(np.uint8)
        return np.ascontiguousarray(canvas)

    @staticmethod
    def _draw_rect(canvas, x1, y1, x2, y2, color):
        h, w = canvas.shape[:2]
        x1, x2 = max(0, min(w - 1, x1)), max(0, min(w - 1, x2))
        y1, y2 = max(0, min(h - 1, y1)), max(0, min(h - 1, y2))
        canvas[y1:y1 + 2, x1:x2 + 1] = color
        canvas[max(0, y2 - 1):y2 + 1, x1:x2 + 1] = color
        canvas[y1:y2 + 1, x1:x1 + 2] = color
        canvas[y1:y2 + 1, max(0, x2 - 1):x2 + 1] = color

    @staticmethod
    def _draw_cross(canvas, u, v, color, size=8):
        h, w = canvas.shape[:2]
        if u < 0 or u >= w or v < 0 or v >= h:
            return
        canvas[max(0, v - 1):min(h, v + 2), max(0, u - size):min(w, u + size + 1)] = color
        canvas[max(0, v - size):min(h, v + size + 1), max(0, u - 1):min(w, u + 2)] = color

    @staticmethod
    def _write_debug_image(path, image, image_format):
        rgb = np.ascontiguousarray(image[:, :, :3].astype(np.uint8))

        try:
            import cv2

            if image_format in ("jpg", "jpeg"):
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                if cv2.imwrite(str(path), bgr, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                    return
            else:
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                if cv2.imwrite(str(path), bgr):
                    return
        except Exception:
            pass

        try:
            from PIL import Image

            pil_format = "JPEG" if image_format in ("jpg", "jpeg") else "PNG"
            Image.fromarray(rgb).save(str(path), pil_format)
            return
        except Exception:
            pass

        if image_format in ("jpg", "jpeg"):
            raise RuntimeError("Saving JPG debug images requires cv2 or Pillow.")
        VisionDetector._write_png_fallback(path, rgb)

    @staticmethod
    def _write_png_fallback(path, image):
        rgb = np.ascontiguousarray(image[:, :, :3].astype(np.uint8))
        height, width = rgb.shape[:2]
        raw = b"".join(b"\x00" + rgb[row].tobytes() for row in range(height))

        def chunk(kind, data):
            return (
                struct.pack(">I", len(data))
                + kind
                + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
            )

        png = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, level=6))
            + chunk(b"IEND", b"")
        )
        with open(path, "wb") as stream:
            stream.write(png)

    def _wait_for_frames(self):
        start = self._rospy.Time.now()
        deadline = time.time() + float(self.config.get("image_timeout", 5.0))
        while time.time() < deadline and not self._rospy.is_shutdown():
            with self._lock:
                image_msg = self._image_msg
                depth_msg = self._depth_msg
                camera_info = self._camera_info
            if image_msg is not None and depth_msg is not None and camera_info is not None:
                if self._stamp_ok(image_msg, start) and self._stamp_ok(depth_msg, start):
                    return image_msg, depth_msg, camera_info
            time.sleep(0.03)
        raise RuntimeError("Timed out waiting for fresh D405 image/depth frames")

    @staticmethod
    def _stamp_ok(msg, start):
        try:
            return msg.header.stamp.is_zero() or msg.header.stamp >= start
        except Exception:
            return True

    def _select_detection(self, result, yolo_class):
        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            raise RuntimeError("YOLO did not detect any object")
        candidates = []
        for box in boxes:
            class_id = int(box.cls[0])
            class_name = self._names.get(class_id, str(class_id))
            if class_name != yolo_class:
                continue
            confidence = float(box.conf[0])
            xyxy = [float(value) for value in box.xyxy[0].tolist()]
            candidates.append((confidence, class_id, class_name, xyxy))
        if not candidates:
            detected = sorted({self._names.get(int(box.cls[0]), str(int(box.cls[0]))) for box in boxes})
            raise RuntimeError(
                "YOLO did not find target class '{}'; detected {}".format(yolo_class, detected)
            )
        confidence, class_id, class_name, xyxy = max(candidates, key=lambda item: item[0])
        return {
            "class_id": class_id,
            "class_name": class_name,
            "confidence": confidence,
            "bbox": {"x1": xyxy[0], "y1": xyxy[1], "x2": xyxy[2], "y2": xyxy[3]},
        }

    def _target_depth(self, depth_m, bbox):
        height, width = depth_m.shape[:2]
        x1 = max(0, min(width - 1, int(round(bbox["x1"]))))
        x2 = max(0, min(width - 1, int(round(bbox["x2"]))))
        y1 = max(0, min(height - 1, int(round(bbox["y1"]))))
        y2 = max(0, min(height - 1, int(round(bbox["y2"]))))
        if x2 <= x1 or y2 <= y1:
            raise RuntimeError("Invalid YOLO bbox: {}".format(bbox))
        cx = 0.5 * (x1 + x2)
        cy = 0.5 * (y1 + y2)
        scale = float(self.config.get("center_roi_scale", 0.25))
        half_w = max(2, int((x2 - x1) * scale * 0.5))
        half_h = max(2, int((y2 - y1) * scale * 0.5))
        rx1 = max(0, int(cx) - half_w)
        rx2 = min(width, int(cx) + half_w + 1)
        ry1 = max(0, int(cy) - half_h)
        ry2 = min(height, int(cy) + half_h + 1)
        roi = depth_m[ry1:ry2, rx1:rx2]
        min_depth = float(self.config.get("min_depth_m", 0.05))
        max_depth = float(self.config.get("max_depth_m", 1.20))
        valid = roi[np.isfinite(roi) & (roi >= min_depth) & (roi <= max_depth)]
        if valid.size == 0:
            raise RuntimeError("No valid depth around target bbox center")
        return cx, cy, float(np.median(valid))

    def _deproject(self, u, v, depth_m, camera_info):
        fx = float(camera_info.K[0])
        fy = float(camera_info.K[4])
        cx = float(camera_info.K[2])
        cy = float(camera_info.K[5])
        if fx == 0.0 or fy == 0.0:
            raise RuntimeError("Invalid camera intrinsics: fx/fy is zero")
        x = (float(u) - cx) * depth_m / fx
        y = (float(v) - cy) * depth_m / fy
        z = depth_m
        return np.array([x, y, z], dtype=np.float64)

    def _transform_point(self, point_camera):
        transform = self._tf_buffer.lookup_transform(
            self._base_frame,
            self._camera_frame,
            self._rospy.Time(0),
            self._rospy.Duration(float(self.config.get("tf_timeout", 2.0))),
        )
        t = transform.transform.translation
        q = transform.transform.rotation
        rotated = self._rotate_vector(point_camera, [q.x, q.y, q.z, q.w])
        return rotated + np.array([t.x, t.y, t.z], dtype=np.float64)

    @staticmethod
    def _rotate_vector(vector, quaternion):
        x, y, z, w = quaternion
        qvec = np.array([x, y, z], dtype=np.float64)
        uv = np.cross(qvec, vector)
        uuv = np.cross(qvec, uv)
        return vector + 2.0 * (w * uv + uuv)

    def _image_callback(self, msg):
        with self._lock:
            self._image_msg = msg

    def _depth_callback(self, msg):
        with self._lock:
            self._depth_msg = msg

    def _camera_info_callback(self, msg):
        with self._lock:
            self._camera_info = msg

    @staticmethod
    def _image_to_yolo_array(msg):
        array = VisionDetector._ros_image_to_array(msg)
        if array.ndim == 2:
            array = np.repeat(array[:, :, None], 3, axis=2)
        if msg.encoding.lower() == "rgb8":
            return array
        if msg.encoding.lower() == "bgr8":
            return array[:, :, ::-1]
        return array

    @staticmethod
    def _depth_to_meters(msg):
        array = VisionDetector._ros_image_to_array(msg)
        encoding = msg.encoding.lower()
        if encoding in {"16uc1", "mono16"}:
            return array.astype(np.float32) * 0.001
        if encoding in {"32fc1"}:
            return array.astype(np.float32)
        raise RuntimeError("Unsupported depth encoding: {}".format(msg.encoding))

    @staticmethod
    def _ros_image_to_array(msg):
        encoding = msg.encoding.lower()
        if encoding in {"mono8", "8uc1"}:
            dtype, channels = np.uint8, 1
        elif encoding in {"rgb8", "bgr8", "8uc3"}:
            dtype, channels = np.uint8, 3
        elif encoding in {"16uc1", "mono16"}:
            dtype, channels = np.uint16, 1
        elif encoding == "32fc1":
            dtype, channels = np.float32, 1
        else:
            raise RuntimeError("Unsupported image encoding: {}".format(msg.encoding))
        itemsize = np.dtype(dtype).itemsize
        row_values = int(msg.step // itemsize)
        data = np.frombuffer(msg.data, dtype=dtype)
        if channels == 1:
            array = data.reshape((msg.height, row_values))[:, :msg.width]
        else:
            array = data.reshape((msg.height, row_values // channels, channels))[:, :msg.width, :]
        return np.ascontiguousarray(array)
