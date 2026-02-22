# -*- coding: utf-8 -*-
"""启动前打印主要访问路由，供 run_local.bat 调用"""
import sys

PORT = sys.argv[1] if len(sys.argv) > 1 else "9900"
BASE = f"http://127.0.0.1:{PORT}"

ROUTES = [
    ("登录页",           f"{BASE}/login/"),
    ("学生 - 课程列表",  f"{BASE}/studentCourseList/"),
    ("教师 - 课程列表",  f"{BASE}/teacherCourseList/"),
    ("管理员 - 控制台",  f"{BASE}/manager/"),
    ("Django Admin",     f"{BASE}/admin/"),
]

print()
print("=" * 60)
print(f"  mycourse 实验报告收集系统  [测试端口 {PORT}]")
print("=" * 60)
for label, url in ROUTES:
    print(f"  {label:<18s}  {url}")
print("=" * 60)
print()
