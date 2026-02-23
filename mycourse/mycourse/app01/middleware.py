import logging
import time

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

        logger.info(
            '%s %s%s → %s (%.0fms)',
            request.method, request.path, uid,
            response.status_code, duration,
        )
        return response
