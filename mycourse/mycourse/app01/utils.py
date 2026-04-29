import logging
import os
import re

logger = logging.getLogger('app01')

# 参考资料单文件上限（与需求文档一致）
REF_MATERIAL_MAX_BYTES = 500 * 1024 * 1024
REF_MATERIAL_MAX_MB = REF_MATERIAL_MAX_BYTES // (1024 * 1024)


def file_iterator(file_name, chunk_size=8192):
    """通用文件流式读取生成器，用于 StreamingHttpResponse"""
    with open(file_name, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if chunk:
                yield chunk
            else:
                break


def is_teacher_or_admin(user):
    """判断用户是否为教师或管理员（管理员权限 >= 教师）"""
    return user.is_superuser or user.profile.type == 'T'


def get_display_name(user):
    """获取用户展示名称（工号/学号 + 姓名）"""
    profile = user.profile
    if profile.type == 'T' or user.is_superuser:
        return f'工号：{user.username} 姓名：{profile.name}'
    return f'学号：{user.username} 姓名：{profile.name}'


def safe_filename(name):
    """将文件名中可能引起路径问题的字符替换掉"""
    import re
    name = name.replace('、', '_').replace('/', '_').replace('\\', '_')
    name = re.sub(r'[<>:"|?*\x00-\x1f]', '_', name)
    return name.strip('. ')


def reference_material_rel_dir(course):
    """参考资料目录，相对 BASE_DIR（不含末尾文件名）。"""
    return os.path.join(
        'file',
        course.courseTerm,
        course.courseName + course.classNumber,
        '参考资料',
    )


_WIN_RESERVED = frozenset({
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9',
})
_REF_ILLEGAL = re.compile(r'[<>:"|?*/\\\x00-\x1f]')


def validate_reference_material_filename(upload_name):
    """
    参考资料上传「预检」：不改写文件名。仅当 basename 合法时才允许落盘与入库。
    返回 (ok, basename, error_message)。ok 为 True 时 basename 为应写入磁盘的文件名。
    """
    if upload_name is None:
        return False, None, '文件名为空'
    raw = str(upload_name).strip()
    if not raw:
        return False, None, '文件名为空'

    if '/' in raw or '\\' in raw:
        return False, None, '文件名不能包含路径（请上传单个文件，不要带 / 或 \\）'

    base = os.path.basename(raw.replace('\\', '/'))
    if not base or base in ('.', '..'):
        return False, None, '文件名无效'

    if _REF_ILLEGAL.search(base):
        return False, None, '文件名不能包含下列字符：< > : " / \\ | ? * 以及控制字符'

    if base != base.rstrip(' .'):
        return False, None, '文件名不能以空格或英文句点结尾（Windows 不允许）'

    stem, ext = os.path.splitext(base)
    if not stem:
        return False, None, '文件名无效：不能只有扩展名而没有主名称'

    if len(base) > 200:
        return False, None, '文件名过长（含扩展名不超过 200 字符）'

    if stem.upper() in _WIN_RESERVED:
        return False, None, f'文件名不能使用 Windows 保留名「{stem}」'

    return True, base, None


def format_file_size(n):
    """人类可读文件大小"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return '—'
    if n >= 1024 * 1024:
        return f'{n / (1024 * 1024):.1f} MB'
    if n >= 1024:
        return f'{n / 1024:.1f} KB'
    return f'{n} B'


def can_manage_course(user, course):
    """教师需为课程成员；管理员可操作任意课程。"""
    if user.is_superuser:
        return True
    if not hasattr(user, 'profile'):
        return False
    if user.profile.type != 'T':
        return False
    return course.members.filter(user=user).exists()
