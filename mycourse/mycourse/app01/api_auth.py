"""API Key 鉴权：新写接口与敏感读接口使用。"""
from functools import wraps
import secrets

from django.conf import settings
from django.http import JsonResponse


def _extract_api_key(request):
    auth = request.META.get('HTTP_AUTHORIZATION', '') or ''
    if auth.lower().startswith('bearer '):
        return auth[7:].strip()
    return (request.META.get('HTTP_X_API_KEY') or '').strip()


def check_api_key(request):
    """校验请求中的 API Key，返回 (ok, error_response_or_None)。"""
    expected = getattr(settings, 'MYCOURSE_API_KEY', '') or ''
    if not expected:
        return False, JsonResponse({
            'code': 503,
            'message': '服务端未配置 MYCOURSE_API_KEY，拒绝 API 写操作',
            'data': None,
        }, status=503)
    provided = _extract_api_key(request)
    if not provided or not secrets.compare_digest(provided, expected):
        return False, JsonResponse({
            'code': 401,
            'message': '未授权：请提供有效的 API Key（Authorization: Bearer <key> 或 X-API-Key）',
            'data': None,
        }, status=401)
    return True, None


def require_api_key(view_func):
    """装饰器：要求有效 API Key。"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        ok, err = check_api_key(request)
        if not ok:
            return err
        return view_func(request, *args, **kwargs)
    return wrapper
