# YOLOv8 Training

商品检测数据集位于项目根目录 `supermarket.yolov8/`。训练入口为
`Robot/vision/train_yolov8.py`，它会先校验图片/标签配对、bbox 五列格式、类别编号和
归一化坐标，校验通过后才开始训练。

安装依赖：

```bash
cd /path/to/RoboShelf
python3 -m venv .yolo-venv
source .yolo-venv/bin/activate
pip install ultralytics PyYAML
```

默认训练：

```bash
cd /path/to/RoboShelf
source .yolo-venv/bin/activate
python3 Robot/vision/train_yolov8.py
```

只检查数据、不训练：

```bash
python3 Robot/vision/train_yolov8.py --validate-only
```

指定参数：

```bash
python3 Robot/vision/train_yolov8.py \
  --model yolov8n.pt \
  --epochs 100 \
  --imgsz 640 \
  --batch 32 \
  --device 0 \
  --name supermarket_yolov8n
```

训练结果默认位于 `runs/detect/supermarket_yolov8n/`，最佳权重为
`weights/best.pt`。如果显存不足，将 `--batch` 改为 `8` 或 `4`。没有可用 NVIDIA
驱动时可传 `--device cpu`，但训练会明显变慢。
