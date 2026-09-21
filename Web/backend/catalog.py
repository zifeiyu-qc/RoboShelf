"""Single source of truth for customer-facing product metadata."""

PRODUCTS = {
    "apple": {"name": "苹果", "unit_price": 3.0, "image_url": "/object_pic/first_floor/apple.jpg", "floor": 3, "slot": 2, "category": "日用品", "max_quantity": 1},
    "red_cup": {"name": "杯子", "unit_price": 3.0, "image_url": "/object_pic/first_floor/red_cup.png", "floor": 3, "slot": 3, "category": "日用品", "max_quantity": 2},
    "xbox_charger": {"name": "Xbox充电器", "unit_price": 20.0, "image_url": "/object_pic/first_floor/xbox_charger.jpg", "floor": 3, "slot": 4, "category": "日用品", "max_quantity": 1},
    "dishwashing": {"name": "洗洁精", "unit_price": 5.0, "image_url": "/object_pic/first_floor/xijiejing.jpg", "floor": 3, "slot": 5, "category": "日用品", "max_quantity": 1},
    "water560": {"name": "560ml矿泉水", "unit_price": 3.0, "image_url": "/object_pic/second_floor/water560.jpg", "floor": 2, "slot": 1, "category": "酒水饮料", "max_quantity": 1},
    "tea": {"name": "东方树叶", "unit_price": 5.0, "image_url": "/object_pic/second_floor/tea.jpg", "floor": 2, "slot": 2, "category": "酒水饮料", "max_quantity": 1},
    "water1500": {"name": "1.5L矿泉水", "unit_price": 5.0, "image_url": "/object_pic/second_floor/water1500.jpg", "floor": 2, "slot": 3, "category": "酒水饮料", "max_quantity": 1},
    "dongpeng": {"name": "东鹏特饮", "unit_price": 5.0, "image_url": "/object_pic/second_floor/dongpeng.jpg", "floor": 2, "slot": 4, "category": "酒水饮料", "max_quantity": 1},
    "milk": {"name": "牛奶", "unit_price": 3.0, "image_url": "/object_pic/second_floor/milk.jpg", "floor": 2, "slot": 5, "category": "酒水饮料", "max_quantity": 1},
    "yanmai": {"name": "燕麦", "unit_price": 15.0, "image_url": "/object_pic/third_floor/yanmai.jpg", "floor": 1, "slot": 3, "category": "大件物品", "max_quantity": 1},
}

PRODUCT_ORDER = tuple(PRODUCTS)
