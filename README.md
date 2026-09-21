# RoboShelf

RoboShelf is a smart-supermarket picking system for a UR30 robot, a Robotiq 3F gripper, an Intel RealSense D405 camera, YOLOv8 product detection, and a FastAPI web interface. The repository contains this project's source and configuration only. Model weights, datasets, logs, build products, and vendored third-party ROS packages are intentionally excluded.

## Demo


https://github.com/user-attachments/assets/2c3361c0-0a71-46ff-bf55-3019e216016c



## Repository layout

```text
Robot/                         Robot API, motion, gripper, and vision logic
Robot/config/                  Product poses and hand-eye calibration configuration
Robot/ros_ws/src/              RoboShelf ROS bringup and MoveIt packages
Robot/vision/                  YOLO training and hand-eye verification scripts
Web/                           FastAPI web service and browser UI
docs/ROS_DEPENDENCIES.md       Exact ROS 1 dependency sources and build order
docs/ADAPTATION.md             Porting guide for another MoveIt-compatible arm
supermarket.yolov8/data.yaml   YOLO dataset manifest (images and labels are external)
```

## Requirements

- Ubuntu 20.04 with ROS Noetic and Python 3.8 (the real-hardware path)
- UR30 robot, Robotiq 3F gripper, Intel RealSense D405, and an operational emergency stop for real operation
- Python packages listed in `Robot/requirements.txt`, `Robot/vision/requirements.txt`, and `Web/backend/requirements.txt`
- For ROS: `catkin_tools`, `rosdep`, MoveIt, the Universal Robots ROS driver, UR description packages, Robotiq 3F packages, `realsense-ros`, `aruco_ros`, and `easy_handeye`

The project is designed to run in mock mode without ROS or hardware. Use it to validate the Robot and Web APIs before configuring a physical cell. The checked-in real-hardware launch files are a UR30 + Robotiq 3F reference integration, not a universal plug-and-play driver. See [ROS dependencies](docs/ROS_DEPENDENCIES.md) and [adapting another robot](docs/ADAPTATION.md) before working with hardware.

## Quick start: mock mode

```bash
git clone https://github.com/zifeiyu-qc/RoboShelf.git
cd RoboShelf
python3 -m venv .venv
source .venv/bin/activate
pip install -r Robot/requirements.txt
pip install -r Web/backend/requirements.txt

# Terminal 1: Robot API
MOCK_MODE=true ./Robot/start_robot.sh

# Terminal 2: Web API and UI
source .venv/bin/activate
ROBOT_SERVER_URL=http://127.0.0.1:8001 ./Web/start_web.sh
```

Open `http://127.0.0.1:8000`. To serve the UI on another LAN device, access `http://<web-host-lan-ip>:8000` and allow TCP port 8000 in the firewall.

## Real-hardware setup

### 1. Install ROS dependencies

Install ROS Noetic and initialize rosdep once on the host. Follow [ROS_DEPENDENCIES.md](docs/ROS_DEPENDENCIES.md) to clone the required third-party ROS 1 packages into `Robot/ros_ws/src/`; do not place them inside the RoboShelf repository unless their licenses and upstream notices permit it.

```bash
source /opt/ros/noetic/setup.bash
sudo rosdep init   # only when rosdep has not been initialized on this computer
rosdep update
```

After all dependencies are present:

```bash
cd /path/to/RoboShelf
source /opt/ros/noetic/setup.bash
cd Robot/ros_ws/src && catkin_init_workspace
cd ../../..
rosdep install --from-paths Robot/ros_ws/src --ignore-src -r -y
./Robot/build_ros.sh
```

### 2. Configure site-specific files

All values below are hardware-specific and must be validated in RViz at low speed before commanding the robot.

- `Robot/config/poses.yaml`: edit the Home, place, and per-floor pre-pick joint angles. Keep `product_id` and `yolo_class` aligned with `Web/backend/catalog.py` and the YOLO class list.
- `Robot/config/handeye.yaml`: replace with your own D405 eye-in-hand calibration result. The checked-in file is only the calibration used by the original cell and must not be reused blindly.
- `Robot/ros_ws/src/supermarket_robot_bringup/config/ur30_calibration.yaml`: replace with the calibration generated for your UR30.
- `Robot/ros_ws/src/supermarket_robot_bringup/urdf/`: verify the mounted Robotiq 3F geometry and TCP frames.
- `Robot/ros_ws/src/ur30_3f_moveit_config/`: verify planning limits, controllers, SRDF, and collision settings for the actual installation.
- `Web/backend/catalog.py`: update product labels, shelf locations, prices, and optional images.

The Web service expects the `object_pic/` directory to exist; the repository keeps only empty floor directories to avoid publishing product photographs. To show product photos, add files matching the `image_url` values in `Web/backend/catalog.py`, for example `object_pic/first_floor/apple.jpg`. Without a file, the service still runs but the corresponding browser image is unavailable.

### 3. Add the YOLO model

Train with your own dataset or download an appropriate model, then place the final weight at:

```text
Robot/vision/model/best.pt
```

The training data is deliberately excluded. Create or restore this layout when training:

```text
supermarket.yolov8/
  data.yaml
  train/images/  train/labels/
  valid/images/  valid/labels/
  test/images/   test/labels/  # optional
```

```bash
source .venv/bin/activate
pip install -r Robot/vision/requirements.txt
python3 Robot/vision/train_yolov8.py --data supermarket.yolov8/data.yaml
```

### 4. Start real services

Use separate terminals and replace the example network addresses with your own values:

```bash
./Robot/start_roscore.sh
ROBOT_IP=192.168.1.10 REVERSE_IP=<control-pc-wired-ip> ./Robot/start_ur30_driver.sh
GRIPPER_IP=192.168.1.11 ./Robot/start_gripper.sh
USE_RVIZ=true ./Robot/start_moveit.sh
./Robot/start_camera.sh
./Robot/start_handeye_publish.sh
MOCK_MODE=false ./Robot/start_robot.sh
ROBOT_SERVER_URL=http://127.0.0.1:8001 ./Web/start_web.sh
```

For calibration, start the camera, then run `./Robot/start_aruco.sh` and `./Robot/start_handeye_calibration.sh`. Save the result as `Robot/config/handeye.yaml`. You can verify repeatability with `SAMPLES=10 ./Robot/start_handeye_accuracy_test.sh`.

## Safety

This software issues robot-motion and gripper commands. It is not a substitute for a risk assessment, collision modeling, speed-limit validation, workspace guarding, or an accessible physical emergency stop. Test every changed joint angle, TCP, calibration, and planned path in RViz and at reduced speed before operation near people or equipment.

## Excluded from Git

The `.gitignore` excludes Python environments, ROS build products, YOLO datasets and weights, inference/training results, camera/debug images, and local notes. Store large reproducible assets in a release, artifact store, or a dataset/model registry rather than Git history.

## License

This project is licensed under the [MIT License](LICENSE). Third-party ROS packages and model/data assets are not included; use them according to their respective licenses.
