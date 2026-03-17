#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
学生作业提交状态查询脚本（通过 API）
用于测试 /api/v1/submission-status/ 接口，本机生产方式默认端口 8001。
"""
import json
import sys
import urllib.parse
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:8001"


def main():
    base = DEFAULT_BASE
    if "--base" in sys.argv:
        idx = sys.argv.index("--base")
        if idx + 1 < len(sys.argv):
            base = sys.argv[idx + 1].rstrip("/")
        sys.argv = [a for i, a in enumerate(sys.argv) if i not in (idx, idx + 1)]

    print("=" * 50)
    print("学生作业提交状态查询（API 测试）")
    print("=" * 50)
    print(f"API 地址: {base}")
    print()

    course_term = input("课程学期（如 2025-2026学年第一学期）: ").strip()
    course_name = input("课程名称: ").strip()
    class_number = input("班号（如 01）: ").strip()
    task_title = input("作业/实验名称: ").strip()

    if not all([course_term, course_name, class_number, task_title]):
        print("错误：四个参数均不能为空。")
        sys.exit(1)

    params = {
        "course_term": course_term,
        "course_name": course_name,
        "class_number": class_number,
        "task_title": task_title,
    }
    url = f"{base}/api/v1/submission-status/?{urllib.parse.urlencode(params)}"

    print()
    print(f"请求: {url}")
    print()

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        msg = str(e)
        try:
            data = json.loads(body)
            if "message" in data:
                msg = data["message"]
        except Exception:
            if body.strip():
                msg = body[:300] + ("..." if len(body) > 300 else "")
        print(f"API 错误 ({e.code}): {msg}")
        if e.code == 404:
            print("提示：请核对课程学期、课程名、班号、作业名是否与系统中完全一致（含标点、空格）。")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"连接失败: {e.reason}")
        print("请确认 mycourse 服务已启动（start_server.bat）。")
        sys.exit(1)
    except Exception as e:
        print(f"请求异常: {e}")
        sys.exit(1)

    if data.get("code") != 0:
        print(f"错误: {data.get('message', '未知错误')}")
        sys.exit(1)

    d = data.get("data", {})
    course = d.get("course", {})
    task = d.get("task", {})
    students = d.get("students", [])

    print(f"课程：{course.get('courseTerm', '')} / {course.get('courseName', '')} / {course.get('classNumber', '')}班")
    print(f"作业：{task.get('title', '')}，截止日期：{task.get('deadline', '')}")
    print()

    status_cn = {"submitted": "已提交", "overdue": "逾期提交", "not_submitted": "未提交"}
    delay_cn = {True: "是", False: "否"}

    col_num = 12
    col_name = 10
    col_status = 10
    col_delay = 8
    print(f"{'学号':<{col_num}} {'姓名':<{col_name}} {'状态':<{col_status}} {'是否逾期':<{col_delay}}")
    print("-" * (col_num + col_name + col_status + col_delay + 3))

    delay_count = 0
    for s in students:
        st = status_cn.get(s.get("status", ""), s.get("status", ""))
        dl = s.get("delay", False)
        if dl:
            delay_count += 1
        dl_str = delay_cn.get(dl, "否")
        print(f"{s.get('number', ''):<{col_num}} {s.get('name', ''):<{col_name}} {st:<{col_status}} {dl_str:<{col_delay}}")

    print()
    print(f"共 {len(students)} 人，逾期 {delay_count} 人")


if __name__ == "__main__":
    main()
