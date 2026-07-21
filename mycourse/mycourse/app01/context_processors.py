from app01.impersonation import is_impersonating, real_user


def impersonation(request):
    """模板可用：is_impersonating / impersonator / real_user"""
    impersonator = getattr(request, 'impersonator', None)
    return {
        'is_impersonating': impersonator is not None,
        'impersonator': impersonator,
        'real_user': real_user(request),
    }
