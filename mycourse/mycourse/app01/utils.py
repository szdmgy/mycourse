import logging
import os

logger = logging.getLogger('app01')


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
    return name.replace('、', '_').replace('/', '_').replace('\\', '_')
