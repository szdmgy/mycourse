import logging
import time

from django.contrib.auth.models import User

from app01.impersonation import SESSION_IMPERSONATOR, SESSION_IMPERSONATE_AS

logger = logging.getLogger('mycourse.access')


class RequestLogMiddleware:
    """在控制台打印每个 HTTP 请求的方法、路径、状态码和耗时"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.time()
        response = self.get_response(request)
        duration = (time.time() - start) * 1000

        user = getattr(request, 'user', None)
        uid = ''
        if user and user.is_authenticated:
            uid = f' [{user.username}]'
            impersonator = getattr(request, 'impersonator', None)
            if impersonator is not None:
                uid = f' [{impersonator.username}->as:{user.username}]'

        logger.info(
            '%s %s%s → %s (%.0fms)',
            request.method, request.path, uid,
            response.status_code, duration,
        )
        return response


class ImpersonationMiddleware:
    """
    在 AuthenticationMiddleware 之后运行：
    若 Session 中有切换记录，将 request.user 替换为目标用户，
    并设置 request.impersonator 为真实超管。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.impersonator = None
        session = getattr(request, 'session', None)
        user = getattr(request, 'user', None)

        if session is not None and user is not None and user.is_authenticated:
            impersonator_id = session.get(SESSION_IMPERSONATOR)
            as_id = session.get(SESSION_IMPERSONATE_AS)
            if impersonator_id and as_id and user.pk == impersonator_id and user.is_superuser:
                target = User.objects.filter(pk=as_id, is_active=True).select_related('profile').first()
                if target is not None and not target.is_superuser:
                    request.impersonator = user
                    request.user = target
                else:
                    session.pop(SESSION_IMPERSONATOR, None)
                    session.pop(SESSION_IMPERSONATE_AS, None)
                    session.modified = True

        return self.get_response(request)
