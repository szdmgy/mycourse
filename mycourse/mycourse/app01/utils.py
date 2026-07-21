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


DOC_FORBIDDEN_MSG = (
    "系统不支持旧版 Word（.doc）文件，请使用 .docx 格式后重试。"
)


def is_legacy_doc_filename(name: str) -> bool:
    """True for .doc but not .docx."""
    n = (name or "").strip().lower()
    return n.endswith(".doc") and not n.endswith(".docx")


def parse_file_type_tokens(file_type: str) -> list:
    ft = (file_type or "*").strip()
    if not ft or ft == "*":
        return ["*"]
    return [t.strip().lower().lstrip(".") for t in ft.split(",") if t.strip()]


def file_type_setting_has_legacy_doc(file_type: str) -> bool:
    """作业允许类型里是否显式包含 .doc（不含 docx）。"""
    tokens = parse_file_type_tokens(file_type)
    return "doc" in tokens


def validate_file_type_setting(file_type: str):
    """
    校验老师配置的允许文件类型。
    返回 (error_or_None, normalized_file_type)。
    """
    raw = (file_type or "*").strip() or "*"
    if file_type_setting_has_legacy_doc(raw):
        return DOC_FORBIDDEN_MSG + "请在允许类型中填写 .docx，不要填写 .doc。", raw
    return None, raw


def sanitize_file_type_setting(file_type: str) -> str:
    """导入等场景：将 .doc 自动改为 .docx，避免写入非法配置。"""
    err, ft = validate_file_type_setting(file_type)
    if not err:
        return ft
    tokens = parse_file_type_tokens(file_type)
    if tokens == ["*"]:
        return "*"
    out = []
    for tok in tokens:
        if tok == "doc":
            tok = "docx"
        if tok not in out:
            out.append(tok)
    return ",".join("." + x if x != "*" else "*" for x in out) if out else "*"
