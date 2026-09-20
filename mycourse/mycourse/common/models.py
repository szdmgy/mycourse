"""门户运行期配置模型。复制到各项目 common/models.py（或并入已有 models）。"""
from django.db import models


class PortalRuntimeConfig(models.Model):
    """单行：当前门户根地址。空则回退 .env 的 REGISTRY_URL。"""

    registry_url = models.CharField("门户根地址", max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "门户运行配置"
        verbose_name_plural = "门户运行配置"

    def __str__(self):
        return self.registry_url or "(empty)"
