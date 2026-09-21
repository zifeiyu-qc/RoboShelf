import os
import threading
import time


BOUNDARY = "camera-frame"


class CameraStream:
    def __init__(self):
        self.enabled = os.getenv("CAMERA_STREAM_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.topic = os.getenv("CAMERA_IMAGE_TOPIC", "/camera/color/image_raw")
        self.timeout = float(os.getenv("CAMERA_FRAME_TIMEOUT", "3.0"))
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._frame = None
        self._content_type = "image/jpeg"
        self._updated_at = 0.0
        self._started = False
        self._error = None
        self._rospy = None
        self._subscriber = None
        self._encoder = self._make_encoder()

    def _make_encoder(self):
        try:
            import cv2
            import numpy as np

            def encode_with_cv2(msg):
                rgb = self._message_to_rgb(msg)
                image = np.frombuffer(rgb, dtype=np.uint8).reshape((msg.height, msg.width, 3))
                bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
                ok, buffer = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
                if not ok:
                    raise RuntimeError("OpenCV failed to encode camera frame")
                return bytes(buffer), "image/jpeg"

            return encode_with_cv2
        except Exception:
            pass

        try:
            from PIL import Image
            from io import BytesIO

            def encode_with_pillow(msg):
                rgb = self._message_to_rgb(msg)
                output = BytesIO()
                Image.frombytes("RGB", (msg.width, msg.height), rgb).save(
                    output, format="JPEG", quality=82
                )
                return output.getvalue(), "image/jpeg"

            return encode_with_pillow
        except Exception:
            pass

        def encode_with_bmp(msg):
            rgb = self._message_to_rgb(msg)
            return self._rgb_to_bmp(rgb, msg.width, msg.height), "image/bmp"

        return encode_with_bmp

    def start(self):
        if not self.enabled:
            return
        with self._lock:
            if self._started:
                return
            self._started = True
        try:
            import rospy
            from sensor_msgs.msg import Image

            if not rospy.core.is_initialized():
                rospy.init_node("supermarket_web_camera_stream", anonymous=True, disable_signals=True)
            self._rospy = rospy
            self._subscriber = rospy.Subscriber(self.topic, Image, self._callback, queue_size=1)
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
                self._started = False
                self._condition.notify_all()

    def status(self):
        self.start()
        with self._lock:
            fresh = self._frame is not None and time.monotonic() - self._updated_at <= self.timeout
            return {
                "enabled": self.enabled,
                "topic": self.topic,
                "connected": fresh,
                "content_type": self._content_type if self._frame is not None else None,
                "error": None if fresh else self._error,
                "updated_at": self._updated_at,
            }

    def frames(self):
        self.start()
        while True:
            with self._condition:
                previous = self._updated_at
                self._condition.wait_for(lambda: self._updated_at != previous or self._error, timeout=self.timeout)
                frame = self._frame
                content_type = self._content_type
                error = self._error
            if frame is None:
                if error:
                    time.sleep(1.0)
                continue
            yield (
                b"--" + BOUNDARY.encode("ascii") + b"\r\n"
                + b"Content-Type: " + content_type.encode("ascii") + b"\r\n"
                + b"Cache-Control: no-store\r\n"
                + b"Content-Length: " + str(len(frame)).encode("ascii") + b"\r\n\r\n"
                + frame + b"\r\n"
            )

    def _callback(self, msg):
        try:
            frame, content_type = self._encoder(msg)
        except Exception as exc:
            with self._condition:
                self._error = str(exc)
                self._condition.notify_all()
            return
        with self._condition:
            self._frame = frame
            self._content_type = content_type
            self._updated_at = time.monotonic()
            self._error = None
            self._condition.notify_all()

    @staticmethod
    def _message_to_rgb(msg):
        encoding = msg.encoding.lower()
        width = int(msg.width)
        height = int(msg.height)
        step = int(msg.step)
        data = bytes(msg.data)
        if width <= 0 or height <= 0:
            raise RuntimeError("Invalid camera frame size")

        rows = []
        if encoding in {"rgb8", "bgr8"}:
            row_bytes = width * 3
            for row in range(height):
                source = data[row * step:row * step + row_bytes]
                if encoding == "bgr8":
                    source = bytes(channel for i in range(0, len(source), 3) for channel in (source[i + 2], source[i + 1], source[i]))
                rows.append(source)
            return b"".join(rows)
        if encoding in {"rgba8", "bgra8"}:
            for row in range(height):
                source = data[row * step:row * step + width * 4]
                if encoding == "rgba8":
                    rows.append(bytes(channel for i in range(0, len(source), 4) for channel in source[i:i + 3]))
                else:
                    rows.append(bytes(channel for i in range(0, len(source), 4) for channel in (source[i + 2], source[i + 1], source[i])))
            return b"".join(rows)
        if encoding in {"mono8", "8uc1"}:
            for row in range(height):
                source = data[row * step:row * step + width]
                rows.append(bytes(channel for value in source for channel in (value, value, value)))
            return b"".join(rows)
        raise RuntimeError("Unsupported camera image encoding: {}".format(msg.encoding))

    @staticmethod
    def _rgb_to_bmp(rgb, width, height):
        row_stride = (width * 3 + 3) & ~3
        pixel_size = row_stride * height
        file_size = 54 + pixel_size
        header = bytearray()
        header.extend(b"BM")
        header.extend(file_size.to_bytes(4, "little"))
        header.extend((0).to_bytes(4, "little"))
        header.extend((54).to_bytes(4, "little"))
        header.extend((40).to_bytes(4, "little"))
        header.extend(width.to_bytes(4, "little"))
        header.extend(height.to_bytes(4, "little"))
        header.extend((1).to_bytes(2, "little"))
        header.extend((24).to_bytes(2, "little"))
        header.extend((0).to_bytes(4, "little"))
        header.extend(pixel_size.to_bytes(4, "little"))
        header.extend((2835).to_bytes(4, "little"))
        header.extend((2835).to_bytes(4, "little"))
        header.extend((0).to_bytes(4, "little"))
        header.extend((0).to_bytes(4, "little"))

        padding = b"\x00" * (row_stride - width * 3)
        pixels = bytearray()
        for row in range(height - 1, -1, -1):
            source = rgb[row * width * 3:(row + 1) * width * 3]
            pixels.extend(channel for i in range(0, len(source), 3) for channel in (source[i + 2], source[i + 1], source[i]))
            pixels.extend(padding)
        return bytes(header + pixels)
