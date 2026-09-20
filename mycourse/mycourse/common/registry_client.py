"""
应用管理 / 门户报到客户端（兼容层）。

新代码请使用 portal_client。本模块保留旧函数名，供已有 AppConfig.ready() 继续工作。
"""
from typing import Optional

try:
    from portal_client import (  # noqa: F401
        get_my_port,
        get_service_url,
        lan_base_url,
        normalize_registry_url,
        report_to_registry,
        reset_registry_cache,
        send_heartbeat,
        set_registry_url,
        start_heartbeat,
        verify_sso_ticket,
    )
except ImportError:
    from common.portal_client import (  # type: ignore  # noqa: F401
        get_my_port,
        get_service_url,
        lan_base_url,
        normalize_registry_url,
        report_to_registry,
        reset_registry_cache,
        send_heartbeat,
        set_registry_url,
        start_heartbeat,
        verify_sso_ticket,
    )

__all__ = [
    "report_to_registry",
    "get_service_url",
    "get_my_port",
    "lan_base_url",
    "normalize_registry_url",
    "reset_registry_cache",
    "send_heartbeat",
    "set_registry_url",
    "start_heartbeat",
    "verify_sso_ticket",
]


def _get_registry_url() -> Optional[str]:
    from portal_client import _get_registry_url as _inner

    return _inner()
