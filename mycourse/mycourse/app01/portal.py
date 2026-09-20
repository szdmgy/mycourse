"""mycourse 门户钩子：只认教师/超管，排除学生。"""
from django.contrib.auth.models import User

from app01.models import UserProfile


def resolve_teacher(staff_id: str, for_login: bool = False):
    staff_id = (staff_id or "").strip()
    if not staff_id:
        return None
    user = User.objects.filter(username=staff_id).first()
    if user is None:
        return None
    if user.is_superuser:
        display = (user.get_full_name() or "").strip() or user.username
        return {
            "user": user,
            "staff_id": staff_id,
            "username": user.username,
            "display_name": display,
            "active": bool(user.is_active),
        }
    profile = UserProfile.objects.filter(user=user).first()
    if profile is None or profile.type != "T":
        return None
    return {
        "user": user,
        "staff_id": staff_id,
        "username": user.username,
        "display_name": profile.name or user.username,
        "active": bool(user.is_active),
    }


def list_teachers():
    rows = []
    qs = (
        UserProfile.objects.filter(type="T")
        .select_related("user")
        .order_by("user__username")
    )
    for profile in qs:
        user = profile.user
        rows.append(
            {
                "staff_id": user.username,
                "username": user.username,
                "display_name": profile.name or user.username,
                "active": bool(user.is_active),
            }
        )
    for user in User.objects.filter(is_superuser=True, is_active=True).order_by("username"):
        if any(r["username"] == user.username for r in rows):
            continue
        rows.append(
            {
                "staff_id": user.username,
                "username": user.username,
                "display_name": (user.get_full_name() or "").strip() or user.username,
                "active": True,
            }
        )
    return rows
