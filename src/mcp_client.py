"""
麦当劳 MCP 客户端（Streamable HTTP）

封装 JSON-RPC 2.0 over Streamable HTTP，含：
  - Session 管理（mcp-session-id）
  - SSE / JSON 双格式响应解析
  - 600 次/分钟限流（滑窗）
  - 401 / 429 专项错误处理与退避重试

用法：
    from mcp_client import MCPClient
    client = MCPClient()            # 从 .env 读取 MCP_TOKEN
    client.initialize()
    tools = client.list_tools()
    ret = client.call("now-time-info", {})
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from typing import Any

import httpx
from dotenv import load_dotenv

MCP_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-06-18"
RATE_LIMIT_PER_MIN = 600
DEFAULT_TIMEOUT = 30.0


class MCPError(Exception):
    """MCP 调用错误，携带可读的原因与处理建议。"""

    CODES = {
        401: ("MCP Token 无效、已过期或未提供",
              "检查 Authorization 请求头；重新到 https://open.mcd.cn/mcp 申请 Token"),
        429: ("触发限流（超过 600 次/分钟）",
              "降低请求频率；本客户端已内置滑窗限流，若仍触发请调小并发"),
    }

    def __init__(self, message: str, code: int | None = None):
        self.code = code
        reason, advice = self.CODES.get(code, ("", ""))
        self.reason = reason
        self.advice = advice
        super().__init__(f"{message}" + (f" | {reason}｜建议：{advice}" if reason else ""))


class RateLimiter:
    """滑动窗口限流器，默认 600 次 / 60 秒。"""

    def __init__(self, limit: int = RATE_LIMIT_PER_MIN, window: float = 60.0):
        self.limit = limit
        self.window = window
        self._hits: deque[float] = deque()

    def acquire(self) -> None:
        now = time.time()
        while self._hits and now - self._hits[0] > self.window:
            self._hits.popleft()
        if len(self._hits) >= self.limit:
            wait = self.window - (now - self._hits[0]) + 0.05
            if wait > 0:
                time.sleep(wait)
            now = time.time()
            self._hits.clear()
        self._hits.append(now)

    @property
    def used(self) -> int:
        now = time.time()
        while self._hits and now - self._hits[0] > self.window:
            self._hits.popleft()
        return len(self._hits)


class MCPClient:
    """麦当劳 MCP Server 客户端。"""

    def __init__(
        self,
        token: str | None = None,
        url: str = MCP_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = 3,
    ):
        load_dotenv()
        self.token = token or os.getenv("MCP_TOKEN", "").strip()
        if not self.token or self.token.startswith("your_"):
            raise MCPError(
                "未检测到有效的 MCP_TOKEN。\n"
                "  1) 打开 https://open.mcd.cn/mcp 用手机号登录\n"
                "  2) 进入「控制台」→「激活」→ 同意协议 → 复制 Token\n"
                "  3) 把 Token 写进 mcd-lab/.env：MCP_TOKEN=你的Token"
            )
        self.url = url
        self.timeout = timeout
        self.max_retries = max_retries
        self.session_id: str | None = None
        self.limiter = RateLimiter()
        self._id = 0
        self._client = httpx.Client(timeout=timeout)
        self.call_count = 0

    # ---------- 底层传输 ----------

    def _headers(self) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    @staticmethod
    def _parse(payload_text: str, content_type: str) -> dict:
        """兼容纯 JSON 与 SSE（text/event-stream）两种响应体。"""
        if "text/event-stream" in (content_type or ""):
            data_lines = [
                ln[5:].strip() for ln in payload_text.splitlines() if ln.startswith("data:")
            ]
            if not data_lines:
                raise MCPError("SSE 响应中没有 data 字段")
            payload_text = data_lines[-1]
        return json.loads(payload_text)

    def _post(self, body: dict, notification: bool = False) -> dict | None:
        self.limiter.acquire()
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.post(self.url, headers=self._headers(), json=body)
            except httpx.RequestError as e:
                last_err = e
                time.sleep(1.5 * (attempt + 1))
                continue

            if resp.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
                last_err = MCPError("请求被限流", 429)
                continue
            if resp.status_code == 401:
                raise MCPError("鉴权失败", 401)
            if resp.status_code >= 400:
                raise MCPError(f"HTTP {resp.status_code}: {resp.text[:200]}")

            # 保存 session
            sid = resp.headers.get("mcp-session-id")
            if sid:
                self.session_id = sid

            if notification or resp.status_code == 202 or not resp.text.strip():
                return None

            data = self._parse(resp.text, resp.headers.get("content-type", ""))
            self.call_count += 1
            if "error" in data:
                err = data["error"]
                raise MCPError(f"RPC 错误 {err.get('code')}: {err.get('message')}")
            return data

        raise MCPError("重试耗尽仍失败") from last_err

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            body["params"] = params
        return self._post(body) or {}

    # ---------- 对外 API ----------

    def initialize(self) -> dict:
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcd-lab", "version": "0.1.0"},
            },
        ).get("result", {})
        self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}, notification=True
        )
        return result

    def list_tools(self) -> list[dict]:
        """返回工具列表，每项含 name / description / inputSchema。"""
        return self._rpc("tools/list").get("result", {}).get("tools", [])

    def call(self, name: str, arguments: dict | None = None) -> Any:
        """调用指定工具；失败抛 MCPError。"""
        res = self._rpc("tools/call", {"name": name, "arguments": arguments or {}}).get(
            "result", {}
        )
        if res.get("isError"):
            for c in res.get("content", []):
                if c.get("type") == "text":
                    raise MCPError(f"{name} 调用失败：{c['text'][:300]}")
        return self._unwrap(res)

    @staticmethod
    def _brace_scan(text: str, start: int) -> int | None:
        """从 start（必须是 '{'）做括号配对扫描，返回配对 '}' 的下标。

        会跳过字符串字面量内的花括号，避免把 "a{b" 这类内容算进去。
        """
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i
        return None

    @staticmethod
    def _extract_json(text: str) -> Any:
        """从 Markdown 说明包裹的文本里抠出 JSON 主体。

        麦当劳 MCP 多数 Tool 返回形如：
            "## Response Structure ... \\n{\"success\":true,...}\\n## 展示要求..."
        即 JSON 夹在说明文字中间，前后都可能有内容，必须靠括号配对定位。
        """
        candidates: list[Any] = []
        idx = text.find("{")
        tries = 0
        while idx >= 0 and tries < 10:
            tries += 1
            end = MCPClient._brace_scan(text, idx)
            if end is not None:
                try:
                    obj = json.loads(text[idx : end + 1])
                    if isinstance(obj, dict):
                        # 命中标准响应信封（含 success/code 等）直接返回
                        if "success" in obj or "code" in obj or "data" in obj:
                            return obj
                        candidates.append(obj)
                except Exception:
                    pass
            idx = text.find("{", idx + 1)
        return candidates[0] if candidates else None

    @staticmethod
    def _unwrap(result: dict) -> Any:
        """把 MCP content 数组转成 Python 对象（优先结构化，其次裸文本）。"""
        content = result.get("content", [])
        if isinstance(content, list):
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            joined = "\n".join(t for t in texts if t)
            try:
                return json.loads(joined)
            except Exception:
                pass
            obj = MCPClient._extract_json(joined)
            if obj is not None:
                return obj
            return joined or content
        return result.get("structuredContent") or result

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
