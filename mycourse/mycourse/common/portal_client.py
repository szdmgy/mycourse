"""
门户适配客户端：业务系统向统一门户报到、心跳、验 SSO 短票。

仅依赖 Python 标准库。失败一律 fail-open（返回 None/False，不抛到启动流程外）。

环境变量：
  REGISTRY_MODE: standalone | managed
  REGISTRY_URL: 门户根地址
  PORT, APP_SLUG, BASE_URL
  PORTAL_TOKEN: 与门户共享的 Bearer
  PORTAL_HEARTBEAT_SECONDS: 默认 60
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)

SSO_CONSUME_PATH = "/api/v1/portal/sso/consume/"
TEACHER_LOOKUP_PATH = "/api/v1/portal/teachers/"
CAPABILITIES_PATH = "/api/v1/meta/capabilities"

_REGISTRY_URL: Optional[str] = None
_HEARTBEAT_STARTED = False
_HEARTBEAT_LOCK = threading.Lock()
_HEARTBEAT_CONTEXT: dict[str, str] = {"slug": "", "base_url": ""}

DEFAULT_TIMEOUT = 5


def normalize_registry_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def set_registry_url(url: Optional[str]) -> None:
    """运行期覆盖门户地址（写入微服务库之后立刻生效，含心跳）。"""
    global _REGISTRY_URL
    _REGISTRY_URL = normalize_registry_url(url or "")


def _get_registry_url() -> Optional[str]:
    global _REGISTRY_URL
    if _REGISTRY_URL is not None:
        return _REGISTRY_URL or None
    mode = os.environ.get("REGISTRY_MODE", "standalone").strip().lower()
    if mode != "managed":
        _REGISTRY_URL = ""
        return None
    url = normalize_registry_url(os.environ.get("REGISTRY_URL", ""))
    _REGISTRY_URL = url
    return url or None


def reset_registry_cache() -> None:
    """测试用：清掉 URL 缓存。"""
    global _REGISTRY_URL
    _REGISTRY_URL = None


def _portal_token() -> str:
    return os.environ.get("PORTAL_TOKEN", "").strip()


def _request(
    method: str,
    path: str,
    data: Optional[dict] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Optional[dict]:
    base = _get_registry_url()
    if not base:
        return None
    url = f"{base}{path}"
    body = None
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    token = _portal_token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("portal_client %s %s failed: %s", method, path, exc)
        return None


def lan_base_url(port: int) -> str:
    """浏览器可达的根地址：优先 BASE_URL，否则局域网 IP+端口。"""
    explicit = os.environ.get("BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    host = os.environ.get("BASE_HOST", "").strip()
    if host:
        if "://" in host:
            return host.rstrip("/")
        return f"http://{host}:{port}"
    ip = _detect_lan_ip()
    return f"http://{ip}:{port}"


def _detect_lan_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


def portal_endpoint_entries() -> list[dict]:
    return [
        {
            "path": f"{TEACHER_LOOKUP_PATH}{{staff_id}}/",
            "method": "GET",
            "description": "按工号查询教师账号是否存在且启用",
        },
        {
            "path": TEACHER_LOOKUP_PATH,
            "method": "GET",
            "description": "教师账号列表（门户对账）",
        },
        {
            "path": SSO_CONSUME_PATH,
            "method": "POST",
            "description": "消费门户 SSO 短票并建立本地登录",
        },
        {
            "path": "/api/v1/portal/registry-url/",
            "method": "GET",
            "description": "读取本服务当前门户根地址",
        },
        {
            "path": "/api/v1/portal/registry-url/",
            "method": "PUT",
            "description": "下发/更新本服务门户根地址（写入本地库）",
        },
    ]


def report_to_registry(
    slug: str,
    name: str,
    port: int,
    base_url: str,
    scope: str = "domain",
    domain: Optional[str] = None,
    quick_links: Optional[dict] = None,
    endpoints: Optional[list] = None,
    project_path: str = "",
    start_cmd: str = "",
    sso_consume_path: str = SSO_CONSUME_PATH,
    teacher_lookup_path: str = TEACHER_LOOKUP_PATH,
    capabilities_path: str = CAPABILITIES_PATH,
    entry_audience: str = "",
) -> bool:
    """向门户汇报。standalone 或无 REGISTRY_URL 时返回 False。"""
    if not _get_registry_url():
        return False
    merged = list(endpoints or [])
    seen = {(e.get("path"), e.get("method")) for e in merged if isinstance(e, dict)}
    for extra in portal_endpoint_entries():
        key = (extra["path"], extra["method"])
        if key not in seen:
            merged.append(extra)
            seen.add(key)
    payload: dict[str, Any] = {
        "slug": slug,
        "name": name,
        "port": int(port),
        "base_url": (base_url or "").rstrip("/"),
        "scope": scope,
        "domain": domain,
        "quick_links": quick_links or {},
        "endpoints": merged,
        "project_path": project_path or "",
        "start_cmd": start_cmd or "",
        "sso_consume_path": sso_consume_path,
        "teacher_lookup_path": teacher_lookup_path,
        "capabilities_path": capabilities_path,
    }
    if entry_audience in ("teacher", "admin"):
        payload["entry_audience"] = entry_audience
    resp = _request("POST", "/api/v1/apps/report/", data=payload)
    if resp is None:
        return False
    ok = resp.get("code", -1) == 0
    if ok:
        logger.info("report_to_registry ok: %s", slug)
    else:
        logger.warning("report_to_registry rejected: %s", resp)
    return ok


def send_heartbeat(slug: str, status: str = "ok", base_url: str = "") -> bool:
    if not _get_registry_url():
        return False
    payload = {"slug": slug, "status": status}
    bu = normalize_registry_url(base_url or _HEARTBEAT_CONTEXT.get("base_url") or "")
    if bu:
        payload["base_url"] = bu
    resp = _request("POST", "/api/v1/apps/heartbeat/", data=payload)
    return bool(resp and resp.get("code", -1) == 0)


def start_heartbeat(slug: str, interval: Optional[int] = None, base_url: str = "") -> None:
    """守护线程定时心跳。可重复调用以更新 slug/base_url，线程只启动一次。"""
    global _HEARTBEAT_STARTED
    if slug:
        _HEARTBEAT_CONTEXT["slug"] = slug
    if base_url:
        _HEARTBEAT_CONTEXT["base_url"] = normalize_registry_url(base_url)
    if not slug or not _get_registry_url():
        return
    with _HEARTBEAT_LOCK:
        already = _HEARTBEAT_STARTED
        _HEARTBEAT_STARTED = True
    if already:
        return
    if interval is None:
        try:
            interval = int(os.environ.get("PORTAL_HEARTBEAT_SECONDS", "60") or "60")
        except ValueError:
            interval = 60
    interval = max(10, interval)

    def _loop() -> None:
        while True:
            try:
                send_heartbeat(_HEARTBEAT_CONTEXT.get("slug") or slug, base_url=_HEARTBEAT_CONTEXT.get("base_url") or "")
            except Exception as exc:
                logger.warning("heartbeat error: %s", exc)
            time.sleep(interval)

    threading.Thread(target=_loop, name="portal-heartbeat", daemon=True).start()


def get_service_url(slug: str) -> Optional[str]:
    if not slug or not _get_registry_url():
        return None
    resp = _request("GET", f"/api/v1/apps/{slug}/")
    if resp is None or resp.get("code", -1) != 0:
        return None
    data = resp.get("data") or {}
    url = data.get("base_url") or ""
    return url.rstrip("/") or None


def get_my_port(slug: Optional[str] = None) -> Optional[int]:
    base = _get_registry_url()
    if base:
        s = (slug or os.environ.get("APP_SLUG", "")).strip()
        if s:
            resp = _request("GET", f"/api/v1/apps/{s}/")
            if resp and resp.get("code", -1) == 0:
                data = resp.get("data") or {}
                if "port" in data:
                    try:
                        return int(data["port"])
                    except (TypeError, ValueError):
                        pass
    try:
        p = int(os.environ.get("PORT", "0") or "0")
        return p if p > 0 else None
    except ValueError:
        return None


def ack_native_login(staff_id: str, slug: str = "") -> bool:
    """本地密码登录成功后通知门户核验身份。SSO 收票不要调用。fail-open。"""
    staff_id = (staff_id or "").strip()
    slug = (slug or os.environ.get("APP_SLUG", "")).strip()
    if not staff_id or not slug:
        return False
    resp = _request("POST", "/api/v1/identity/ack/", data={"staff_id": staff_id, "slug": slug})
    return bool(resp and resp.get("code", -1) == 0)


def verify_sso_ticket(ticket: str, slug: str) -> Optional[dict]:
    """向门户校验一次性短票。成功返回 data（含 staff_id、slug、expires_at）。"""
    ticket = (ticket or "").strip()
    slug = (slug or "").strip()
    if not ticket or not slug:
        return None
    resp = _request("POST", "/api/v1/sso/tickets/verify/", data={"ticket": ticket, "slug": slug})
    if resp is None or resp.get("code", -1) != 0:
        return None
    data = resp.get("data")
    return data if isinstance(data, dict) else None
