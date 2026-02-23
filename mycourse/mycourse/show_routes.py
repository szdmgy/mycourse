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
        return "127.0.0.1"


IP = get_local_ip()
BASE = f"http://{IP}:{PORT}"

ROUTES = [
    ("登录页",           f"{BASE}/login/"),
    ("学生 - 课程列表",  f"{BASE}/studentCourseList/"),
    ("教师 - 课程列表",  f"{BASE}/teacherCourseList/"),
    ("管理员 - 控制台",  f"{BASE}/manager/"),
    ("Django Admin",     f"{BASE}/admin/"),
]

print()
print("=" * 60)
print(f"  mycourse 实验报告收集系统  [端口 {PORT}]")
print("=" * 60)
print(f"  本机局域网 IP: {IP}")
print("-" * 60)
for label, url in ROUTES:
    print(f"  {label:<18s}  {url}")
print("=" * 60)
print()
