let PRODUCTS = {};

const UI = {
  connection: document.getElementById("connection"),
  connectionText: document.getElementById("connectionText"),
  submit: document.getElementById("submitOrder"),
  buttonText: document.getElementById("buttonText"),
  offlineNotice: document.getElementById("offlineNotice"),
  taskStatus: document.getElementById("taskStatus"),
  taskMessage: document.getElementById("taskMessage"),
  taskId: document.getElementById("taskId"),
  steps: [...document.querySelectorAll("#progressSteps li")],
  progress: document.getElementById("progressSteps"),
  result: document.getElementById("resultBanner"),
  resultIcon: document.querySelector(".result-icon"),
  resultTitle: document.getElementById("resultTitle"),
  resultMessage: document.getElementById("resultMessage"),
  retry: document.getElementById("retryButton"),
  cartLines: document.getElementById("cartLines"),
  cartTotal: document.getElementById("cartTotal"),
  selectionCount: document.getElementById("selectionCount"),
  marketShelf: document.getElementById("marketShelf"),
  cameraFeed: document.getElementById("cameraFeed"),
  cameraState: document.getElementById("cameraState"),
  cameraPlaceholder: document.getElementById("cameraPlaceholder")
};

const RUNNING = new Set(["QUEUED", "MOVING_TO_PICK", "GRASPING", "LIFTING", "MOVING_TO_PLACE", "RELEASING", "RETURNING_HOME"]);
const LABELS = {
  IDLE: "等待下单", QUEUED: "订单已提交", MOVING_TO_PICK: "前往抓取点",
  GRASPING: "正在抓取", LIFTING: "正在抬升", MOVING_TO_PLACE: "前往购物篮",
  RELEASING: "正在放置", RETURNING_HOME: "正在返回 Home", SUCCESS: "取货完成", FAILED: "取货失败"
};
const STEP_LABELS = {
  detecting_product: "正在寻找商品",
  moving_before_pick: "前往目标前方",
  approaching_pick: "正在靠近商品"
};
const STEP_INDEX = { IDLE: -1, QUEUED: 1, MOVING_TO_PICK: 2, GRASPING: 3, LIFTING: 3, MOVING_TO_PLACE: 4, RELEASING: 5, RETURNING_HOME: 5, SUCCESS: 6 };

const cart = {};
const stock = {};
let robotOnline = false;
let robotReady = false;
let submitting = false;
let restoredTerminalOrder = null;
let activeLocalTaskId = null;
const appliedCompletions = {};
let cameraStarted = false;

async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 4000);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
    let data = {};
    try { data = await response.json(); } catch (_) { /* handled below */ }
    if (!response.ok) throw new Error(data.detail || `请求失败 (${response.status})`);
    return data;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("网络请求超时，请检查服务连接");
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[character]);
}

function productMarkup(product) {
  const name = escapeHtml(product.name);
  return `<article class="shelf-slot shop-product" data-product-id="${escapeHtml(product.product_id)}">
    <h4>${name}</h4>
    <div class="product-photo"><img src="${escapeHtml(product.image_url)}" alt="${name}"></div>
    <p class="product-price"><span>￥</span>${product.unit_price.toFixed(2)}</p>
    <p class="stock-label" aria-live="polite"></p>
    <div class="quantity-control" aria-label="${name}数量">
      <button class="quantity-button decrease" type="button" aria-label="减少${name}数量">−</button>
      <output class="quantity-value" aria-live="polite">0</output>
      <button class="quantity-button increase" type="button" aria-label="增加${name}数量">+</button>
    </div>
  </article>`;
}

function renderShelf(catalog) {
  const occupied = new Map();
  catalog.forEach((product) => {
    if (!Number.isInteger(product.floor) || product.floor < 1 || product.floor > 3 ||
        !Number.isInteger(product.slot) || product.slot < 1 || product.slot > 5 ||
        !product.image_url.startsWith("/object_pic/")) {
      throw new Error(`商品目录位置或图片路径无效: ${product.product_id}`);
    }
    const key = `${product.floor}:${product.slot}`;
    if (occupied.has(key) || PRODUCTS[product.product_id]) {
      throw new Error(`商品目录存在重复货位或商品: ${product.product_id}`);
    }
    occupied.set(key, product);
    const configuredMaxQuantity = Number(product.max_quantity);
    const fallbackMaxQuantity = /cup|杯/.test(product.product_id + product.name) ? 2 : 1;
    const maxQuantity = Number.isInteger(configuredMaxQuantity) && configuredMaxQuantity > 0
      ? configuredMaxQuantity
      : fallbackMaxQuantity;
    PRODUCTS[product.product_id] = {
      name: product.name, price: Number(product.unit_price),
      imageUrl: product.image_url, floor: product.floor, slot: product.slot,
      maxQuantity
    };
    stock[product.product_id] = maxQuantity;
    cart[product.product_id] = 0;
  });

  UI.marketShelf.innerHTML = [3, 2, 1].map((floor) => {
    const floorProducts = catalog.filter((product) => product.floor === floor);
    const category = floorProducts[0] ? floorProducts[0].category : `第${floor}层`;
    const slots = [1, 2, 3, 4, 5].map((slot) => {
      const product = occupied.get(`${floor}:${slot}`);
      return product ? productMarkup(product) : '<div class="shelf-slot empty-slot" aria-hidden="true"></div>';
    }).join("");
    return `<section class="shelf-row" aria-labelledby="shelf-floor-${floor}">
      <header class="shelf-label"><h3 id="shelf-floor-${floor}">${escapeHtml(category)}</h3></header>
      <div class="shelf-slots">${slots}</div>
    </section>`;
  }).join("");
}

async function loadCatalog() {
  const catalog = await api("/api/products");
  if (!Array.isArray(catalog) || !catalog.length) throw new Error("商品目录为空");
  PRODUCTS = {};
  renderShelf(catalog);
}

function cartCount() {
  return Object.values(cart).reduce((sum, quantity) => sum + quantity, 0);
}

function renderCart() {
  const lines = Object.entries(cart).filter(([, quantity]) => quantity > 0);
  UI.cartLines.innerHTML = lines.length
    ? lines.map(([id, quantity]) => `<div class="order-line"><span>${PRODUCTS[id].name}</span><strong>￥${PRODUCTS[id].price.toFixed(2)} × ${quantity}</strong></div>`).join("")
    : '<p class="empty-cart">尚未选择商品</p>';
  const total = Object.entries(cart).reduce((sum, [id, quantity]) => sum + PRODUCTS[id].price * quantity, 0);
  UI.cartTotal.textContent = `￥${total.toFixed(2)}`;
  UI.selectionCount.textContent = cartCount() ? `已选 ${cartCount()} 件` : "未选择";
  document.querySelectorAll(".shop-product").forEach((card) => {
    const id = card.dataset.productId;
    const quantity = cart[id];
    const available = stock[id];
    const maxQuantity = PRODUCTS[id].maxQuantity;
    const busy = RUNNING.has(UI.submit.dataset.status);
    const soldOut = available === 0;
    card.classList.toggle("selected", quantity > 0);
    card.classList.toggle("out-of-stock", soldOut);
    card.setAttribute("aria-disabled", soldOut ? "true" : "false");
    card.querySelector(".quantity-value").textContent = quantity;
    card.querySelector(".stock-label").textContent = soldOut ? "已售罄" : "剩余 " + available + "/" + maxQuantity;
    card.querySelector(".decrease").disabled = quantity === 0 || busy;
    card.querySelector(".increase").disabled = quantity >= available || busy;
  });
  updateButton();
}

function setConnection(state) {
  robotOnline = state !== "OFFLINE";
  UI.connection.className = `connection ${state === "EXECUTING" ? "executing" : state.toLowerCase()}`;
  UI.connectionText.textContent = state === "ONLINE" ? "在线" : state === "EXECUTING" ? "执行中" : "离线";
  UI.offlineNotice.hidden = robotOnline;
  updateButton();
}

function updateButton(status = UI.submit.dataset.status || "IDLE") {
  UI.submit.dataset.status = status;
  const busy = RUNNING.has(status);
  UI.submit.disabled = !robotReady || busy || submitting || cartCount() === 0;
  const total = Object.entries(cart).reduce((sum, [id, quantity]) => sum + PRODUCTS[id].price * quantity, 0);
  UI.buttonText.textContent = !robotOnline ? "机器人当前离线" : !robotReady ? "机器人正在初始化" : busy || submitting ? "正在依次取货" : cartCount() === 0 ? "请先选择商品" : status === "FAILED" ? "重新下单（仅剩余商品）" : `下单 · ￥${total.toFixed(2)}`;
}

function applyCompletedStock(order) {
  if (!activeLocalTaskId || order.task_id !== activeLocalTaskId || !order.items) return;
  const completedForTask = appliedCompletions[order.task_id] || {};
  order.items.forEach((item) => {
    const completed = Math.max(0, Number(item.completed) || 0);
    const alreadyApplied = completedForTask[item.product_id] || 0;
    const delta = Math.max(0, completed - alreadyApplied);
    if (delta && item.product_id in stock) {
      stock[item.product_id] = Math.max(0, stock[item.product_id] - delta);
      cart[item.product_id] = Math.min(cart[item.product_id], stock[item.product_id]);
    }
    completedForTask[item.product_id] = completed;
  });
  appliedCompletions[order.task_id] = completedForTask;
}

function restoreFailedCart(order) {
  if (!activeLocalTaskId || order.task_id !== activeLocalTaskId ||
      order.status !== "FAILED" || !order.items || !order.items.length) return;
  const terminalKey = (order.task_id || "unknown") + ":" + order.status;
  if (restoredTerminalOrder === terminalKey) return;
  restoredTerminalOrder = terminalKey;
  Object.keys(cart).forEach((id) => { cart[id] = 0; });
  order.items.forEach((item) => {
    if (item.product_id in cart) {
      const remaining = Math.max(0, item.quantity - item.completed);
      cart[item.product_id] = Math.min(remaining, stock[item.product_id]);
    }
  });
}

function renderOrder(order) {
  const status = order.status || "IDLE";
  const currentIndex = STEP_INDEX[status] ?? -1;
  const itemProgress = order.total_items ? `（${order.completed_items}/${order.total_items} 件）` : "";
  UI.taskStatus.textContent = `${STEP_LABELS[order.step] || LABELS[status] || status}${itemProgress}`;
  UI.taskMessage.textContent = order.error || order.message || "等待提交取货订单";
  UI.taskId.textContent = order.task_id ? `订单 ${order.task_id.slice(0, 8)}` : "";
  UI.progress.classList.toggle("failed", status === "FAILED");
  UI.steps.forEach((step, index) => {
    step.classList.toggle("done", status === "SUCCESS" || index < currentIndex);
    step.classList.toggle("active", status !== "IDLE" && status !== "SUCCESS" && index === currentIndex);
  });
  UI.result.hidden = status !== "SUCCESS" && status !== "FAILED";
  UI.result.classList.toggle("failure", status === "FAILED");
  if (status === "SUCCESS") {
    UI.resultIcon.textContent = "✓";
    UI.resultTitle.textContent = "整单取货完成";
    UI.resultMessage.textContent = order.message;
    UI.retry.hidden = true;
  } else if (status === "FAILED") {
    UI.resultIcon.textContent = "!";
    UI.resultTitle.textContent = `取货失败（已完成 ${order.completed_items || 0}/${order.total_items || 0} 件）`;
    UI.resultMessage.textContent = order.error || "任务执行失败，请联系工作人员。";
    UI.retry.hidden = false;
  }
  applyCompletedStock(order);
  restoreFailedCart(order);
  updateButton(status);
  renderCart();
}

async function refresh() {
  try {
    const health = await api("/api/health");
    robotReady = Boolean(health.robot_health && health.robot_health.ready);
    setConnection(health.robot || "OFFLINE");
    if (robotOnline) renderOrder(await api("/api/orders/current"));
    else {
      UI.taskStatus.textContent = "机器人离线";
      UI.taskMessage.textContent = health.error || "请检查 Robot 服务是否启动";
    }
  } catch (error) {
    robotReady = false;
    setConnection("OFFLINE");
    UI.taskStatus.textContent = "网络连接异常";
    UI.taskMessage.textContent = error.message;
  }
}

async function refreshCamera() {
  if (!cameraStarted) {
    UI.cameraFeed.src = `/api/camera/stream?ts=${Date.now()}`;
    cameraStarted = true;
  }
  try {
    const status = await api("/api/camera/status");
    const connected = Boolean(status.connected);
    UI.cameraState.textContent = connected ? "在线" : "等待";
    UI.cameraState.className = `camera-state ${connected ? "online" : "offline"}`;
    UI.cameraPlaceholder.hidden = connected;
    UI.cameraFeed.classList.toggle("visible", connected);
  } catch (error) {
    UI.cameraState.textContent = "离线";
    UI.cameraState.className = "camera-state offline";
    UI.cameraPlaceholder.hidden = false;
    UI.cameraFeed.classList.remove("visible");
  }
}

async function submitOrder() {
  if (!robotReady || submitting || cartCount() === 0) return;
  submitting = true;
  updateButton();
  const items = Object.entries(cart).filter(([, quantity]) => quantity > 0).map(([product_id, quantity]) => ({ product_id, quantity }));
  try {
    const order = await api("/api/orders", { method: "POST", body: JSON.stringify({ items }) });
    activeLocalTaskId = order.task_id || null;
    if (activeLocalTaskId) appliedCompletions[activeLocalTaskId] = {};
    Object.keys(cart).forEach((id) => { cart[id] = 0; });
    renderOrder(order);
  } catch (error) {
    UI.taskStatus.textContent = "订单提交失败";
    UI.taskMessage.textContent = error.message;
    await refresh();
  } finally {
    submitting = false;
    updateButton(UI.submit.dataset.status);
  }
}

UI.marketShelf.addEventListener("click", (event) => {
  const button = event.target.closest(".quantity-button");
  const card = event.target.closest(".shop-product");
  if (!button || !card || RUNNING.has(UI.submit.dataset.status)) return;
  const id = card.dataset.productId;
  const change = button.classList.contains("increase") ? 1 : -1;
  cart[id] = Math.max(0, Math.min(stock[id], cart[id] + change));
  renderCart();
});
UI.submit.addEventListener("click", submitOrder);
UI.retry.addEventListener("click", submitOrder);

async function bootstrap() {
  try {
    await loadCatalog();
    renderCart();
    await refresh();
    await refreshCamera();
    window.setInterval(refresh, 1000);
    window.setInterval(refreshCamera, 2000);
  } catch (error) {
    robotReady = false;
    setConnection("OFFLINE");
    UI.taskStatus.textContent = "商品目录加载失败";
    UI.taskMessage.textContent = error.message;
    UI.buttonText.textContent = "暂时无法下单";
  }
}

bootstrap();
