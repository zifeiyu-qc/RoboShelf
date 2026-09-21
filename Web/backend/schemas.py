from typing import List, Optional

from pydantic import BaseModel, Field, conint


class OrderItemCreate(BaseModel):
    product_id: str
    quantity: conint(ge=1, le=10)

    class Config:
        extra = "forbid"


class OrderCreate(BaseModel):
    items: List[OrderItemCreate]

    class Config:
        extra = "forbid"


class OrderItemView(BaseModel):
    product_id: str
    product_name: str
    quantity: int
    unit_price: float
    completed: int = 0


class ProductView(BaseModel):
    product_id: str
    name: str
    unit_price: float
    image_url: str
    floor: int
    slot: int
    category: str
    max_quantity: int


class OrderView(BaseModel):
    task_id: Optional[str] = None
    robot_task_id: Optional[str] = None
    status: str
    step: str
    message: str
    error: Optional[str] = None
    items: List[OrderItemView] = Field(default_factory=list)
    current_product_id: Optional[str] = None
    current_product_name: Optional[str] = None
    current_index: int = 0
    total_items: int = 0
    completed_items: int = 0
    total_price: float = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
