"""
门户适配 Django 侧：3 个固定 URL + 教师解析钩子。

业务系统 urls.py：

    path("api/v1/portal/", include("common.portal_django")),
    path("api/v1/", include(portal_django.meta_urlpatterns)),

环境变量 / settings：
  PORTAL_TOKEN, PORTAL_SSO_ENABLED
  PORTAL_RESOLVE_TEACHER  点分路径，签名 resolve_teacher(staff_id, for_login=False)
  PORTAL_EXTRA_CAPABILITIES  list[dict] 或 可调用返回 list
  APP_SLUG
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import secrets
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import path
from django.utils.module_loading import import_string
from django.db import OperationalError
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)

PORTAL_CAPABILITIES = [
    {
        "name": "portal.teacher.lookup",
        "method": "GET",
        "path": "/api/v1/portal/teachers/{staff_id}/",
        "roles": ["portal"],
        "idempotent": True,
        "description": "按工号查询教师账号",
    },
    {
        "name": "portal.teacher.list",
        "method": "GET",
        "path": "/api/v1/portal/teachers/",
        "roles": ["portal"],
        "idempotent": True,
        "description": "教师账号列表",
    },
    {
        "name": "portal.sso.consume",
        "method": "POST",
        "path": "/api/v1/portal/sso/consume/",
        "roles": ["portal"],
        "idempotent": False,
        "description": "消费 SSO 短票",
    },
    {
        "name": "portal.registry_url.get",
        "method": "GET",
        "path": "/api/v1/portal/registry-url/",
        "roles": ["portal", "agent"],
        "idempotent": True,
        "description": "读取本服务当前门户根地址",
    },
    {
        "name": "portal.registry_url.set",
        "method": "PUT",
        "path": "/api/v1/portal/registry-url/",
        "roles": ["portal", "agent"],
        "idempotent": True,
        "description": "更新本服务门户根地址并写入本地库",
    },
]


def capability_entries() -> list[dict]:
    return list(PORTAL_CAPABILITIES)


def _json(code: int, message: str, data: Any = None, status: int = 200, error_code: str | None = None):
    payload = {"code": code, "message": message, "data": data}
    if error_code:
        payload["error_code"] = error_code
    return JsonResponse(payload, status=status, json_dumps_params={"ensure_ascii": False})


def _bearer_token(request) -> str:
    header = request.META.get("HTTP_AUTHORIZATION") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return (request.META.get("HTTP_X_API_KEY") or "").strip()


def _portal_token_ok(request) -> bool:
    expected = (
        getattr(settings, "PORTAL_TOKEN", None)
        or os.environ.get("PORTAL_TOKEN", "")
    ).strip()
    got = _bearer_token(request)
    if not expected or not got:
        return False
    return secrets.compare_digest(expected, got)


def _sso_enabled() -> bool:
    raw = os.environ.get("PORTAL_SSO_ENABLED", "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _safe_next(next_url: str) -> str:
    value = (next_url or "/").strip() or "/"
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return "/"
    if not value.startswith("/"):
        return "/"
    return value


def _call_resolver(staff_id: str, for_login: bool = False) -> Optional[dict]:
    path = (
        getattr(settings, "PORTAL_RESOLVE_TEACHER", None)
        or os.environ.get("PORTAL_RESOLVE_TEACHER", "")
    ).strip()
    func: Callable[..., Any]
    if path:
        func = import_string(path)
    else:
        func = default_resolve_teacher
    kwargs: dict[str, Any] = {}
    try:
        sig = inspect.signature(func)
        if "for_login" in sig.parameters:
            kwargs["for_login"] = for_login
    except (TypeError, ValueError):
        pass
    result = func(staff_id, **kwargs)
    if not result:
        return None
    if not isinstance(result, dict):
        return None
    return result


def default_resolve_teacher(staff_id: str, for_login: bool = False) -> Optional[dict]:
    User = get_user_model()
    user = User.objects.filter(username=staff_id).first()
    if user is None:
        return None
    role = str(getattr(user, "role", "") or "").lower()
    if role in ("student", "stu", "ROLE_STUDENT".lower()):
        return None
    display = ""
    if hasattr(user, "get_full_name"):
        display = (user.get_full_name() or "").strip()
    display = display or getattr(user, "first_name", "") or user.username
    return {
        "user": user,
        "staff_id": staff_id,
        "username": user.username,
        "display_name": display,
        "active": bool(getattr(user, "is_active", True)),
    }


def _public_teacher(row: dict) -> dict:
    return {
        "exists": True,
        "staff_id": row.get("staff_id") or "",
        "username": row.get("username") or "",
        "display_name": row.get("display_name") or "",
        "active": bool(row.get("active")),
    }


@csrf_exempt
@require_http_methods(["GET"])
def teacher_lookup(request, staff_id: str):
    if not _portal_token_ok(request):
        return _json(401, "未授权", status=401, error_code="unauthorized")
    staff_id = (staff_id or "").strip()
    row = _call_resolver(staff_id, for_login=False) if staff_id else None
    if not row:
        return _json(0, "ok", {"exists": False, "staff_id": staff_id, "username": "", "display_name": "", "active": False})
    data = _public_teacher(row)
    return _json(0, "ok", data)


@csrf_exempt
@require_http_methods(["GET"])
def teacher_list(request):
    if not _portal_token_ok(request):
        return _json(401, "未授权", status=401, error_code="unauthorized")
    lister = getattr(settings, "PORTAL_LIST_TEACHERS", None) or os.environ.get("PORTAL_LIST_TEACHERS", "")
    results: list[dict] = []
    if lister:
        func = import_string(lister) if isinstance(lister, str) else lister
        raw = func() or []
        for item in raw:
            if isinstance(item, dict):
                results.append(_public_teacher(item))
    try:
        page = max(1, int(request.GET.get("page", "1") or "1"))
    except ValueError:
        page = 1
    try:
        page_size = int(request.GET.get("page_size", "50") or "50")
    except ValueError:
        page_size = 50
    page_size = min(100, max(1, page_size))
    total = len(results)
    start = (page - 1) * page_size
    chunk = results[start : start + page_size]
    return _json(0, "ok", {"total": total, "page": page, "page_size": page_size, "results": chunk})


def _consume_ticket(request, ticket: str, next_url: str, as_json: bool):
    if not _sso_enabled():
        body = _json(1, "本系统未开启门户 SSO", error_code="sso_disabled")
        return body if as_json else HttpResponseRedirect("/accounts/login/" if False else _local_login_url())
    slug = (getattr(settings, "APP_SLUG", None) or os.environ.get("APP_SLUG", "")).strip()
    if not ticket or not slug:
        if as_json:
            return _json(1, "缺少 ticket 或 APP_SLUG", error_code="bad_request")
        return HttpResponseRedirect(_local_login_url())
    try:
        from portal_client import verify_sso_ticket
    except ImportError:
        from common.portal_client import verify_sso_ticket  # type: ignore
    data = verify_sso_ticket(ticket, slug)
    if not data:
        if as_json:
            return _json(1, "短票无效或已过期", error_code="ticket_invalid")
        return HttpResponseRedirect(_local_login_url())
    staff_id = str(data.get("staff_id") or "").strip()
    row = _call_resolver(staff_id, for_login=True) if staff_id else None
    user = row.get("user") if row else None
    if not row or not row.get("active") or user is None:
        if as_json:
            return _json(1, "本地无此教师或账号未启用", error_code="teacher_not_found")
        return HttpResponseRedirect(_local_login_url())
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    try:
        profile = getattr(user, "profile", None)
        if profile is not None and getattr(profile, "name", None):
            request.session["loginUserName"] = profile.name
    except Exception:
        pass
    nxt = _safe_next(next_url)
    if nxt in ("/", ""):
        default_next = (
            getattr(settings, "PORTAL_SSO_DEFAULT_NEXT", None)
            or os.environ.get("PORTAL_SSO_DEFAULT_NEXT", "")
            or "/"
        ).strip() or "/"
        nxt = _safe_next(default_next)
    if as_json:
        return _json(0, "ok", {"staff_id": staff_id, "next": nxt})
    return HttpResponseRedirect(nxt)


def _local_login_url() -> str:
    return getattr(settings, "LOGIN_URL", "/accounts/login/") or "/accounts/login/"


def notify_native_login(user) -> None:
    """业务系统本地密码登录成功后调用。学生账号与 SSO 收票不要调用。fail-open。"""
    if user is None:
        return
    role = str(getattr(user, "role", "") or "").lower()
    if role in ("student", "stu"):
        return
    username = (getattr(user, "username", "") or "").strip()
    if not username:
        return
    slug = (getattr(settings, "APP_SLUG", None) or os.environ.get("APP_SLUG", "")).strip()
    try:
        from portal_client import ack_native_login
    except ImportError:
        from common.portal_client import ack_native_login  # type: ignore
    try:
        ack_native_login(username, slug)
    except Exception as exc:
        logger.warning("notify_native_login failed: %s", exc)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def sso_consume(request):
    if request.method == "GET":
        ticket = (request.GET.get("ticket") or "").strip()
        next_url = request.GET.get("next") or "/"
        return _consume_ticket(request, ticket, next_url, as_json=False)
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        body = {}
    ticket = str(body.get("ticket") or request.POST.get("ticket") or "").strip()
    next_url = str(body.get("next") or request.POST.get("next") or "/")
    return _consume_ticket(request, ticket, next_url, as_json=True)


@require_http_methods(["GET"])
def capabilities_view(request):
    entries = capability_entries()
    extra = getattr(settings, "PORTAL_EXTRA_CAPABILITIES", None)
    if isinstance(extra, str) and extra.strip():
        extra = import_string(extra)
    if callable(extra):
        extra = extra()
    names = {e["name"] for e in entries}
    for item in extra or []:
        if isinstance(item, dict) and item.get("name") and item["name"] not in names:
            entries.append(item)
            names.add(item["name"])
    return _json(0, "ok", {"results": entries})


def _import_client():
    try:
        from portal_client import set_registry_url, reset_registry_cache, normalize_registry_url
    except ImportError:
        from common.portal_client import set_registry_url, reset_registry_cache, normalize_registry_url  # type: ignore
    return set_registry_url, reset_registry_cache, normalize_registry_url


def _config_row():
    from common.models import PortalRuntimeConfig

    row = PortalRuntimeConfig.objects.first()
    if row is None:
        row = PortalRuntimeConfig.objects.create(registry_url="")
    return row


def effective_registry_url() -> tuple[str, str]:
    """返回 (url, source) source=db|env|none。"""
    try:
        row = _config_row()
        db_url = (row.registry_url or "").strip().rstrip("/")
        if db_url:
            return db_url, "db"
    except OperationalError:
        pass
    env_url = (os.environ.get("REGISTRY_URL") or "").strip().rstrip("/")
    if env_url:
        return env_url, "env"
    return "", "none"


def apply_persisted_registry_url() -> str:
    """启动时：库优先，否则 managed 下用 .env。立刻写入 portal_client 缓存。"""
    set_registry_url, reset_registry_cache, _norm = _import_client()
    try:
        url, source = effective_registry_url()
    except Exception:
        logger.warning("读取门户地址失败，回退环境变量")
        reset_registry_cache()
        return ""
    if source == "db" and url:
        set_registry_url(url)
        return url
    reset_registry_cache()
    return url


def persist_registry_url(url: str) -> str:
    set_registry_url, _reset, normalize_registry_url = _import_client()
    url = normalize_registry_url(url)
    if url and not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("门户地址须以 http:// 或 https:// 开头")
    row = _config_row()
    row.registry_url = url
    row.save(update_fields=["registry_url", "updated_at"])
    if url:
        set_registry_url(url)
    else:
        _reset()
    return url


@csrf_exempt
@require_http_methods(["GET", "PUT", "POST"])
def registry_url_view(request):
    if not _portal_token_ok(request):
        return _json(401, "未授权", status=401, error_code="unauthorized")
    if request.method == "GET":
        url, source = effective_registry_url()
        return _json(0, "ok", {"registry_url": url, "source": source})
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        body = {}
    new_url = str(body.get("registry_url") or "").strip()
    try:
        saved = persist_registry_url(new_url)
    except ValueError as exc:
        return _json(1, str(exc), error_code="bad_request")
    except OperationalError:
        return _json(1, "本地配置表不可用，请先 migrate", error_code="db_unavailable", status=500)
    slug = (getattr(settings, "APP_SLUG", None) or os.environ.get("APP_SLUG", "")).strip()
    try:
        from portal_client import report_to_registry, lan_base_url, start_heartbeat
    except ImportError:
        from common.portal_client import report_to_registry, lan_base_url, start_heartbeat  # type: ignore
    if saved and slug:
        try:
            port = int(os.environ.get("PORT", "0") or "0")
        except ValueError:
            port = 0
        report_to_registry(
            slug=slug,
            name=str(getattr(settings, "PORTAL_APP_NAME", None) or slug),
            port=port or 0,
            base_url=lan_base_url(port or 80),
        )
        start_heartbeat(slug, base_url=lan_base_url(port or 80) if port else "")
    return _json(0, "ok", {"registry_url": saved, "source": "db" if saved else "none"})


urlpatterns = [
    path("teachers/", teacher_list),
    path("teachers/<str:staff_id>/", teacher_lookup),
    path("sso/consume/", sso_consume),
    path("registry-url/", registry_url_view),
]

meta_urlpatterns = [
    path("meta/capabilities", capabilities_view),
    path("meta/capabilities/", capabilities_view),
]
