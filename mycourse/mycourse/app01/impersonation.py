"""超级管理员身份切换辅助函数。"""
from django.contrib.auth.models import User

from app01.models import ImpersonationLog

SESSION_IMPERSONATOR = 'impersonator_id'
SESSION_IMPERSONATE_AS = 'impersonate_as_id'
SESSION_RECENT = 'impersonate_recent_ids'
RECENT_MAX = 20


def client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def real_user(request):
    """返回真实登录用户（切换中则为超管本人）。"""
    impersonator = getattr(request, 'impersonator', None)
    if impersonator is not None:
        return impersonator
    return request.user if getattr(request.user, 'is_authenticated', False) else None


def is_impersonating(request):
    return getattr(request, 'impersonator', None) is not None


def can_start_impersonation(request):
    user = real_user(request)
    return bool(user and user.is_authenticated and user.is_superuser and not is_impersonating(request))


def remember_recent(session, user_id):
    recent = session.get(SESSION_RECENT) or []
    uid = int(user_id)
    recent = [uid] + [x for x in recent if int(x) != uid]
    session[SESSION_RECENT] = recent[:RECENT_MAX]
    session.modified = True


def start_impersonation(request, target: User):
    if not can_start_impersonation(request):
        return False, '无权切换身份，或当前已在模拟中'
    if not target.is_active:
        return False, '目标用户已停用'
    if target.is_superuser:
        return False, '禁止切换为其他超级管理员'
    actor = real_user(request)
    request.session[SESSION_IMPERSONATOR] = actor.pk
    request.session[SESSION_IMPERSONATE_AS] = target.pk
    remember_recent(request.session, target.pk)
    ImpersonationLog.objects.create(
        impersonator=actor,
        target_user=target,
        action=ImpersonationLog.ACTION_START,
        ip_address=client_ip(request),
    )
    return True, 'ok'


def stop_impersonation(request):
    impersonator_id = request.session.get(SESSION_IMPERSONATOR)
    target_id = request.session.get(SESSION_IMPERSONATE_AS)
    if not impersonator_id or not target_id:
        return False, '当前未在模拟身份中'
    actor = User.objects.filter(pk=impersonator_id).first()
    target = User.objects.filter(pk=target_id).first()
    if actor and target:
        ImpersonationLog.objects.create(
            impersonator=actor,
            target_user=target,
            action=ImpersonationLog.ACTION_STOP,
            ip_address=client_ip(request),
        )
    request.session.pop(SESSION_IMPERSONATOR, None)
    request.session.pop(SESSION_IMPERSONATE_AS, None)
    request.session.modified = True
    return True, 'ok'
