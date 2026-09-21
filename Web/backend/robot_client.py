import os

import httpx


class RobotUnavailable(RuntimeError):
    pass


class RobotBusy(RuntimeError):
    pass


class RobotClient:
    def __init__(self):
        self.base_url = os.getenv("ROBOT_SERVER_URL", "http://127.0.0.1:8001").rstrip("/")
        self.timeout = httpx.Timeout(float(os.getenv("ROBOT_REQUEST_TIMEOUT", "3.0")))

    async def _request(self, method, path, json=None):
        try:
            # Robot traffic stays on the configured LAN and must not inherit
            # desktop HTTP/SOCKS proxy variables.
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                response = await client.request(method, self.base_url + path, json=json)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise RobotUnavailable("机器人控制服务离线或请求超时") from exc
        if response.status_code == 409:
            raise RobotBusy("机器人已有任务正在执行")
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise RobotUnavailable("机器人控制服务错误: {}".format(detail))
        try:
            return response.json()
        except ValueError as exc:
            raise RobotUnavailable("机器人控制服务返回了无效数据") from exc

    async def health(self):
        return await self._request("GET", "/health")

    async def status(self):
        return await self._request("GET", "/status")

    async def start_pick_place(self, product_id):
        return await self._request(
            "POST", "/pick-place", json={"product_id": product_id}
        )
