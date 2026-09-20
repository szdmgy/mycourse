"""Django AppConfig 源文件。复制到各项目 common/apps.py，勿放在 PYTHONPATH 根上名为 apps.py。"""
from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "common"
    label = "portal_common"
    verbose_name = "门户适配"
