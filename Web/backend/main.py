import asyncio
import copy
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from camera_stream import BOUNDARY, CameraStream
from catalog import PRODUCTS, PRODUCT_ORDER
from robot_client import RobotBusy, RobotClient, RobotUnavailable
from schemas import OrderCreate, OrderView, ProductView

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent.parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"
PRODUCT_IMAGE_DIR = PROJECT_DIR / "object_pic"
RUNNING_STATES = {
    "QUEUED", "MOVING_TO_PICK", "GRASPING", "LIFTING",
    "MOVING_TO_PLACE", "RELEASING", "RETURNING_HOME",
}
app = FastAPI(title="Smart Supermarket Picking Web", version="2.0.0")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/object_pic", StaticFiles(directory=PRODUCT_IMAGE_DIR), name="object_pic")
robot = RobotClient()
camera = CameraStream()
order_lock = asyncio.Lock()
current = {
    "task_id": None, "robot_task_id": None, "status": "IDLE", "step": "idle",
    "message": "请选择商品并下单", "error": None, "items": [],
    "current_product_id": None, "current_product_name": None,
    "current_index": 0, "total_items": 0, "completed_items": 0,
    "total_price": 0, "started_at": None, "finished_at": None,
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def snapshot():
    return copy.deepcopy(current)


def set_current(**changes):
    current.update(changes)


async def run_order(queue):
    try:
        for index, product_id in enumerate(queue, start=1):
            product = PRODUCTS[product_id]
            prefix = "第 {}/{} 件：{}".format(index, len(queue), product["name"])
            set_current(
                status="QUEUED", step="queued", message=prefix + "正在等待机器人",
                error=None, robot_task_id=None, current_product_id=product_id,
                current_product_name=product["name"], current_index=index,
            )
            robot_task = await robot.start_pick_place(product_id)
            set_current(robot_task_id=robot_task.get("task_id"))

            while True:
                result = await robot.status()
                robot_status = result.get("status", "FAILED")
                set_current(
                    robot_task_id=result.get("task_id"), status=robot_status,
                    step=result.get("step", "unknown"),
                    message=prefix + "，" + result.get("message", "正在执行"),
                    error=result.get("error"),
                )
                if robot_status == "SUCCESS":
                    break
                if robot_status == "FAILED":
                    raise RuntimeError(result.get("error") or "机器人抓取失败")
                await asyncio.sleep(0.5)

            for item in current["items"]:
                if item["product_id"] == product_id:
                    item["completed"] += 1
                    break
            set_current(completed_items=index)

        set_current(
            status="SUCCESS", step="completed",
            message="订单中的全部商品已放入购物篮，请取走商品。",
            current_product_id=None, current_product_name=None,
            finished_at=utc_now(),
        )
    except (RobotBusy, RobotUnavailable, RuntimeError) as exc:
        set_current(
            status="FAILED", step="failed", message="订单取货失败",
            error=str(exc), finished_at=utc_now(),
        )


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
async def health():
    try:
        result = await robot.health()
        ready = bool(result.get("ready", False))
        busy = current["status"] in RUNNING_STATES or bool(result.get("initializing", False))
        connection_status = "EXECUTING" if busy else ("ONLINE" if ready else "OFFLINE")
        return {"web": "online", "robot": connection_status, "robot_health": result}
    except RobotUnavailable as exc:
        return {"web": "online", "robot": "OFFLINE", "robot_health": None, "error": str(exc)}


@app.get("/api/products", response_model=List[ProductView])
async def products():
    return [dict(product_id=product_id, **product) for product_id, product in PRODUCTS.items()]


@app.get("/api/camera/status")
async def camera_status():
    return camera.status()


@app.get("/api/camera/stream")
async def camera_stream():
    return StreamingResponse(
        camera.frames(),
        media_type="multipart/x-mixed-replace; boundary={}".format(BOUNDARY),
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/orders", response_model=OrderView, status_code=status.HTTP_202_ACCEPTED)
async def create_order(order: OrderCreate):
    async with order_lock:
        if current["status"] in RUNNING_STATES:
            raise HTTPException(status_code=409, detail="当前已有取货订单正在执行")
        quantities = {}
        for item in order.items:
            if item.product_id not in PRODUCTS:
                raise HTTPException(status_code=422, detail="不支持的商品: {}".format(item.product_id))
            quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
        for product_id, quantity in quantities.items():
            max_quantity = int(PRODUCTS[product_id].get("max_quantity", 1))
            if quantity > max_quantity:
                raise HTTPException(
                    status_code=422,
                    detail="{}最多可选择 {} 件".format(PRODUCTS[product_id]["name"], max_quantity),
                )
        if not quantities:
            raise HTTPException(status_code=422, detail="购物车不能为空")
        if sum(quantities.values()) > 20:
            raise HTTPException(status_code=422, detail="单次订单最多包含 20 件商品")

        try:
            health_result = await robot.health()
            if not health_result.get("ready", False):
                raise RobotUnavailable("机器人尚未就绪")
            robot_status = await robot.status()
            if robot_status.get("status") in RUNNING_STATES:
                raise RobotBusy("机器人已有任务正在执行")
        except RobotBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RobotUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        items = []
        queue = []
        for product_id in PRODUCT_ORDER:
            quantity = quantities.get(product_id, 0)
            if quantity:
                product = PRODUCTS[product_id]
                items.append({
                    "product_id": product_id, "product_name": product["name"],
                    "quantity": quantity, "unit_price": product["unit_price"],
                    "completed": 0,
                })
                queue.extend([product_id] * quantity)

        set_current(
            task_id=str(uuid.uuid4()), robot_task_id=None, status="QUEUED",
            step="queued", message="订单已提交，正在等待机器人", error=None,
            items=items, current_product_id=None, current_product_name=None,
            current_index=0, total_items=len(queue), completed_items=0,
            total_price=sum(item["quantity"] * item["unit_price"] for item in items),
            started_at=utc_now(), finished_at=None,
        )
        asyncio.create_task(run_order(queue))
        return snapshot()


@app.get("/api/orders/current", response_model=OrderView)
async def current_order():
    return snapshot()
