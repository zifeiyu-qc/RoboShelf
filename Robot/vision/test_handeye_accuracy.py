#!/usr/bin/env python3
import argparse
import math
import sys
import time

import rospy
import tf2_ros


def quat_normalize(q):
    n = math.sqrt(sum(v * v for v in q))
    if n == 0:
        return [0.0, 0.0, 0.0, 1.0]
    return [v / n for v in q]


def quat_dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def quat_angle_deg(a, b):
    a = quat_normalize(a)
    b = quat_normalize(b)
    d = abs(max(-1.0, min(1.0, quat_dot(a, b))))
    return math.degrees(2.0 * math.acos(d))


def mean_quaternion(quats):
    if not quats:
        return [0.0, 0.0, 0.0, 1.0]
    ref = quats[0]
    acc = [0.0, 0.0, 0.0, 0.0]
    for q in quats:
        q = list(q)
        if quat_dot(ref, q) < 0:
            q = [-v for v in q]
        for i in range(4):
            acc[i] += q[i]
    return quat_normalize(acc)


def lookup_transform(buffer, base_frame, marker_frame, timeout):
    return buffer.lookup_transform(
        base_frame,
        marker_frame,
        rospy.Time(0),
        rospy.Duration(timeout),
    )


def transform_to_tuple(tf_msg):
    t = tf_msg.transform.translation
    r = tf_msg.transform.rotation
    return (t.x, t.y, t.z), (r.x, r.y, r.z, r.w)


def summarize(samples):
    positions = [p for p, _ in samples]
    quats = [q for _, q in samples]
    n = len(samples)
    mean = [sum(p[i] for p in positions) / n for i in range(3)]
    q_mean = mean_quaternion(quats)

    distances = []
    axis_errors = [[], [], []]
    angle_errors = []
    for p, q in samples:
        delta = [p[i] - mean[i] for i in range(3)]
        distances.append(math.sqrt(sum(v * v for v in delta)))
        for i in range(3):
            axis_errors[i].append(delta[i])
        angle_errors.append(quat_angle_deg(q_mean, q))

    rms = math.sqrt(sum(d * d for d in distances) / n)
    max_err = max(distances)
    std_axis = []
    for values in axis_errors:
        std_axis.append(math.sqrt(sum(v * v for v in values) / n))

    angle_rms = math.sqrt(sum(a * a for a in angle_errors) / n)
    angle_max = max(angle_errors)

    print("")
    print("==== Hand-eye accuracy summary ====")
    print("Samples: {}".format(n))
    print("Mean marker position in base frame: x={:.6f}, y={:.6f}, z={:.6f} m".format(*mean))
    print("Translation RMS error: {:.2f} mm".format(rms * 1000.0))
    print("Translation max error: {:.2f} mm".format(max_err * 1000.0))
    print("Axis RMS error: x={:.2f} mm, y={:.2f} mm, z={:.2f} mm".format(
        std_axis[0] * 1000.0,
        std_axis[1] * 1000.0,
        std_axis[2] * 1000.0,
    ))
    print("Orientation RMS error: {:.3f} deg".format(angle_rms))
    print("Orientation max error: {:.3f} deg".format(angle_max))
    print("")
    if rms < 0.005 and max_err < 0.010:
        print("Result: good for a first picking demo (<5 mm RMS, <10 mm max).")
    elif rms < 0.010 and max_err < 0.020:
        print("Result: usable but should be improved for precise grasping.")
    else:
        print("Result: poor. Recheck marker size, TF frames, camera focus/exposure, and sample diversity.")


def main():
    parser = argparse.ArgumentParser(
        description="Check eye-in-hand calibration by measuring marker pose stability in robot base frame."
    )
    parser.add_argument("--base-frame", default="base_link")
    parser.add_argument("--marker-frame", default="aruco_marker_frame")
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--auto-interval", type=float, default=0.0,
                        help="If >0, sample every N seconds instead of waiting for Enter.")
    args = parser.parse_args()

    rospy.init_node("supermarket_handeye_accuracy_test", anonymous=True)
    buffer = tf2_ros.Buffer(rospy.Duration(30.0))
    listener = tf2_ros.TransformListener(buffer)

    print("Testing marker stability: {} -> {}".format(args.base_frame, args.marker_frame))
    print("Keep the ArUco board fixed. Move the robot/camera to different viewpoints before each sample.")
    print("Make sure handeye TF publisher and ArUco detector are running.")
    time.sleep(1.0)

    samples = []
    while len(samples) < args.samples and not rospy.is_shutdown():
        idx = len(samples) + 1
        if args.auto_interval > 0:
            print("Waiting {:.1f}s before sample {}/{}...".format(args.auto_interval, idx, args.samples))
            rospy.sleep(args.auto_interval)
        else:
            try:
                input("Move to pose {}/{} and press Enter to sample...".format(idx, args.samples))
            except EOFError:
                pass

        try:
            tf_msg = lookup_transform(buffer, args.base_frame, args.marker_frame, args.timeout)
        except Exception as exc:
            print("Sample {} failed: {}".format(idx, exc))
            continue

        p, q = transform_to_tuple(tf_msg)
        samples.append((p, q))
        print("Sample {:02d}: x={:.6f}, y={:.6f}, z={:.6f} m | q=({:.5f}, {:.5f}, {:.5f}, {:.5f})".format(
            idx, p[0], p[1], p[2], q[0], q[1], q[2], q[3]
        ))

    if len(samples) < 2:
        print("Need at least 2 valid samples.")
        return 1

    summarize(samples)
    return 0


if __name__ == "__main__":
    sys.exit(main())
