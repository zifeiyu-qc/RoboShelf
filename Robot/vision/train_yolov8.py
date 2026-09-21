#!/usr/bin/env python3
"""Validate and train the supermarket YOLOv8 detection dataset."""

import argparse
import os
from pathlib import Path

import torch
import yaml
from ultralytics import YOLO


SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = Path(os.environ["SUPERMARKET_PROJECT_ROOT"]).resolve() if os.getenv(
    "SUPERMARKET_PROJECT_ROOT"
) else SCRIPT_PATH.parents[2]
DEFAULT_DATA = PROJECT_ROOT / "supermarket.yolov8" / "data.yaml"
DEFAULT_MODEL = PROJECT_ROOT / "yolov8n.pt"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def parse_args():
    parser = argparse.ArgumentParser(description="Train YOLOv8 on the supermarket dataset")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default=None, help="For example: 0, 0,1, cpu; default auto-detects")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--patience", type=int, default=30)
    parser.add_argument("--name", default="supermarket_yolov8n")
    parser.add_argument("--resume", action="store_true", help="Resume from the model checkpoint")
    parser.add_argument("--validate-only", action="store_true", help="Validate the dataset without training")
    return parser.parse_args()


def validate_dataset(data_yaml):
    data_yaml = data_yaml.resolve()
    if not data_yaml.is_file():
        raise FileNotFoundError("Dataset YAML not found: {}".format(data_yaml))
    with data_yaml.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    names = config.get("names")
    if not isinstance(names, (list, dict)) or not names:
        raise ValueError("data.yaml must define a non-empty names list or mapping")
    class_count = len(names)
    if config.get("nc") not in (None, class_count):
        raise ValueError("nc does not match names: {} != {}".format(config["nc"], class_count))

    dataset_root = (data_yaml.parent / config.get("path", ".")).resolve()
    total_images = 0
    total_objects = 0
    class_objects = [0] * class_count
    for split_key in ("train", "val", "test"):
        relative_images = config.get(split_key)
        if not relative_images:
            if split_key in ("train", "val"):
                raise ValueError("data.yaml is missing {}".format(split_key))
            continue
        image_dir = (dataset_root / relative_images).resolve()
        if not image_dir.is_dir():
            raise FileNotFoundError("{} images directory not found: {}".format(split_key, image_dir))
        label_dir = image_dir.parent / "labels"
        if not label_dir.is_dir():
            raise FileNotFoundError("{} labels directory not found: {}".format(split_key, label_dir))

        images = {path.stem: path for path in image_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES}
        labels = {path.stem: path for path in label_dir.glob("*.txt")}
        missing = sorted(set(images) - set(labels))
        orphaned = sorted(set(labels) - set(images))
        if missing or orphaned:
            raise ValueError(
                "{} image/label mismatch: {} missing labels, {} orphan labels".format(
                    split_key, len(missing), len(orphaned)
                )
            )

        for label_path in labels.values():
            for line_number, line in enumerate(label_path.read_text().splitlines(), 1):
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) != 5:
                    raise ValueError(
                        "{}:{} expected 5 columns, found {}".format(
                            label_path, line_number, len(parts)
                        )
                    )
                class_id = int(parts[0])
                coordinates = [float(value) for value in parts[1:]]
                if not 0 <= class_id < class_count:
                    raise ValueError("{}:{} invalid class {}".format(label_path, line_number, class_id))
                if any(value < 0.0 or value > 1.0 for value in coordinates):
                    raise ValueError("{}:{} coordinates must be in [0, 1]".format(label_path, line_number))
                if coordinates[2] <= 0.0 or coordinates[3] <= 0.0:
                    raise ValueError("{}:{} bbox width/height must be positive".format(label_path, line_number))
                class_objects[class_id] += 1
                total_objects += 1
        total_images += len(images)
        print("{}: {} images, {} labels".format(split_key, len(images), len(labels)))

    missing_classes = [index for index, count in enumerate(class_objects) if count == 0]
    if missing_classes:
        raise ValueError("No bbox annotations for classes: {}".format(missing_classes))
    print("Dataset valid: {} images, {} bbox objects, {} classes".format(
        total_images, total_objects, class_count
    ))
    return data_yaml


def main():
    args = parse_args()
    data_yaml = validate_dataset(args.data)
    if args.validate_only:
        return
    device = args.device if args.device is not None else ("0" if torch.cuda.is_available() else "cpu")
    if device == "cpu":
        print("WARNING: CUDA is unavailable; CPU training will be slow.")
    model = YOLO(args.model)
    model.train(
        data=str(data_yaml), epochs=args.epochs, imgsz=args.imgsz,
        batch=args.batch, device=device, workers=args.workers,
        patience=args.patience, project=str(PROJECT_ROOT / "runs" / "detect"),
        name=args.name, seed=42, deterministic=True, resume=args.resume,
    )


if __name__ == "__main__":
    main()
