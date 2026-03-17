# mycourse API 说明

供外部应用（如考勤成绩计算）调用，仅提供学生作业提交状态查询。**无需 Token**，局域网内直接访问。

## 接口

### 学生作业提交状态

**URL**：`GET /api/v1/submission-status/`

**参数**（均需与数据库存储完全一致）：

| 参数 | 含义 | 示例 |
|------|------|------|
| course_term | 课程学期 | 2025-2026学年第一学期 |
| course_name | 课程名称 | 操作系统原理 |
| class_number | 班号 | 01 |
| task_title | 作业/实验名称 | 实验一 进程管理 |

**示例**：
```
GET /api/v1/submission-status/?course_term=2025-2026学年第一学期&course_name=操作系统原理&class_number=01&task_title=实验一
```

**成功响应**（code=0）：
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "course": {
      "courseTerm": "2025-2026学年第一学期",
      "courseNumber": "2201990076",
      "courseName": "操作系统原理",
      "classNumber": "01"
    },
    "task": {
      "title": "实验一",
      "deadline": "2025-03-15"
    },
    "students": [
      {
        "number": "2021001",
        "name": "张三",
        "status": "submitted",
        "submit_time": "2025-03-14T10:00:00",
        "delay": false
      },
      {
        "number": "2021002",
        "name": "李四",
        "status": "overdue",
        "submit_time": "2025-03-16T09:00:00",
        "delay": true
      },
      {
        "number": "2021003",
        "name": "王五",
        "status": "not_submitted",
        "submit_time": null,
        "delay": false
      }
    ]
  }
}
```

**status 取值**：
- `submitted`：按时提交
- `overdue`：逾期提交
- `not_submitted`：未提交

**delay**：是否逾期（true=逾期提交，便于考勤计分）

**错误响应**（code≠0）：
- 400：缺少参数
- 404：未找到课程或作业

## 调用示例（Python）

```python
import requests

BASE = "http://127.0.0.1:9900"  # 或实际服务地址

resp = requests.get(
    f"{BASE}/api/v1/submission-status/",
    params={
        "course_term": "2025-2026学年第一学期",
        "course_name": "操作系统原理",
        "class_number": "01",
        "task_title": "实验一",
    },
)
data = resp.json()
if data["code"] == 0:
    for s in data["data"]["students"]:
        # s["delay"] 为 True 表示逾期，可用于扣分等
        print(s["number"], s["name"], s["status"], s["delay"])
```
