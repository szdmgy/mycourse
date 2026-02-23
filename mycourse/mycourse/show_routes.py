# -*- coding: utf-8 -*-
"""启动前打印主要访问路由，供 start_server.bat / run_local.bat 调用"""
import socket
import sys

PORT = sys.argv[1] if len(sys.argv) > 1 else "9900"


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


LAN_IP = get_local_ip()
LOCAL = f"http://127.0.0.1:{PORT}"

ROUTES = [
    ("登录页",           "/login/"),
    ("学生 - 课程列表",  "/studentCourseList/"),
    ("教师 - 课程列表",  "/teacherCourseList/"),
    ("管理员 - 控制台",  "/manager/"),
    ("Django Admin",     "/admin/"),
]

print()
print("=" * 60)
print(f"  mycourse 实验报告收集系统  [端口 {PORT}]")
print("=" * 60)
print(f"  本机访问: http://127.0.0.1:{PORT}")
if LAN_IP:
    print(f"  局域网访问: http://{LAN_IP}:{PORT}")
print("-" * 60)
for label, path in ROUTES:
    print(f"  {label:<18s}  {LOCAL}{path}")
print("=" * 60)
print()
