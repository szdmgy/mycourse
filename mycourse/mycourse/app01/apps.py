from django.apps import AppConfig


class App01Config(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app01'

    def ready(self):
        import logging
        import os
        import sys
        from pathlib import Path

        if "migrate" in sys.argv or "makemigrations" in sys.argv:
            return
        if "runserver" in sys.argv and os.environ.get("RUN_MAIN") != "true":
            return
        logger = logging.getLogger(__name__)
        try:
            from common.portal_client import lan_base_url, report_to_registry, start_heartbeat
            from common.portal_django import apply_persisted_registry_url

            apply_persisted_registry_url()
            port = int(os.environ.get("PORT", "8001") or "8001")
            slug = os.environ.get("APP_SLUG", "mycourse").strip() or "mycourse"
            base_url = lan_base_url(port)
            ok = report_to_registry(
                slug=slug,
                name=os.environ.get("APP_NAME", "实验报告收集系统"),
                port=port,
                base_url=base_url,
                scope="domain",
                domain="teaching",
                entry_audience="teacher",
                quick_links={"教师首页": "/teacherCourseList/", "登录": "/login/"},
                endpoints=[
                    {"path": "/api/v1/submission-status/", "method": "GET", "description": "作业提交状态"},
                ],
                project_path=str(Path(__file__).resolve().parent.parent),
                start_cmd="start_server.bat",
            )
            if not ok:
                logger.warning("向门户报到失败（不影响启动）: %s", slug)
            start_heartbeat(slug, base_url=base_url)
        except Exception as exc:
            logger.warning("向门户报到异常（不影响启动）: %s", exc)
