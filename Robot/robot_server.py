"""FastAPI service exposing one fixed UR30 pick/place task."""

import os
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

from task_executor import RUNNING_STATES, TaskExecutor


def env_bool(name, default=True):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


BASE_DIR = Path(__file__).resolve().parent
with (BASE_DIR / "config" / "poses.yaml").open(encoding="utf-8") as stream:
    CONFIG = yaml.safe_load(stream)


def resolve_robot_path(value):
    """Resolve paths in poses.yaml relative to Robot/, not the caller's CWD."""
    path = Path(value).expanduser()
    return str(path if path.is_absolute() else BASE_DIR / path)


for path_key in ("model_path", "handeye_file", "debug_dir"):
    if CONFIG.get("vision", {}).get(path_key):
        CONFIG["vision"][path_key] = resolve_robot_path(CONFIG["vision"][path_key])

MOCK_MODE = env_bool("MOCK_MODE", True)
MOCK_STEP_DELAY = float(os.getenv("MOCK_STEP_DELAY", "1.0"))
executor = TaskExecutor(MOCK_MODE, CONFIG, MOCK_STEP_DELAY)
app = FastAPI(title="UR30 Robot Picking Service", version="1.0.0")


class PickPlaceRequest(BaseModel):
    product_id: str

    class Config:
        extra = "forbid"


@app.get("/health")
def health():
    return executor.health()


@app.get("/status")
def get_status():
    return executor.status()


@app.post("/pick-place", status_code=status.HTTP_202_ACCEPTED)
def pick_place(request: PickPlaceRequest):
    current = executor.status()
    if current["status"] in RUNNING_STATES:
        raise HTTPException(status_code=409, detail="A pick/place task is already running")
    try:
        task = executor.start(request.product_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(status_code=409, detail="A pick/place task is already running")
    return task
