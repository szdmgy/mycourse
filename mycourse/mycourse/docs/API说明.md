# mycourse API 说明

供外部应用（如考勤成绩计算、LLM Agent）调用。

## 鉴权策略

| 接口 | 鉴权 |
|------|------|
| `GET /api/v1/submission-status/` | **暂不强制**（兼容旧调用方）；后续将迁移为需 API Key |
| `GET/PATCH /api/v1/tasks/<id>/` | **必须** API Key |
| `POST/DELETE /api/v1/tasks/<id>/template/` | **必须** API Key |
| `GET/PUT/DELETE /api/v1/tasks/<id>/precheck/` | **必须** API Key |
| `GET /api/v1/tasks/<id>/grades/`、`.../grades/summary/` | **必须** API Key |
| `PUT/PATCH .../grades/<学号>/`、`.../homeworks/<id>/grade/` | **必须** API Key |

配置：在 `mycourse/mycourse/.env` 中设置：

```
MYCOURSE_API_KEY=请换成足够长的随机串
```

传递方式（二选一）：

- `Authorization: Bearer <MYCOURSE_API_KEY>`
- `X-API-Key: <MYCOURSE_API_KEY>`

---

## 学生作业提交状态（兼容旧接口）

**URL**：`GET /api/v1/submission-status/`

**参数**（均需与数据库存储完全一致）：

| 参数 | 含义 | 示例 |
|------|------|------|
| course_term | 课程学期 | 2025-2026学年第一学期 |
| course_name | 课程名称 | 操作系统原理 |
| class_number | 班号 | 01 |
| task_title | 作业/实验名称 | 实验一 进程管理 |

**成功响应**（code=0）学生字段：

| 字段 | 说明 |
|------|------|
| submit_time | 兼容字段，等于首次提交时间 |
| submitted_at | 首次成功提交时间 |
| updated_at | 最后更新时间 |
| delay | 是否逾期（按 **首次提交日期** 相对截止日期） |
| status | submitted / overdue / not_submitted |

---

## 作业设置（需 API Key）

**URL**：`GET|PATCH|PUT /api/v1/tasks/<task_id>/`

**GET**：返回作业基本信息（title、content、display、deadline、fileType、所属课程）。

**PATCH/PUT** 可更新字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| deadline | string | `YYYY-MM-DD` |
| display | bool | 是否对学生显示（开放） |
| title | string | 标题 |
| content | string | 正文 |
| fileType | string | 允许扩展名 |
| enable_template_download | bool | 允许学生下载模板（须已有模板） |
| enable_cover_autofill | bool | 下载时自动填封面（须已有模板） |

**示例**：

```bash
curl -X PATCH "http://127.0.0.1:9900/api/v1/tasks/1/" ^
  -H "Authorization: Bearer YOUR_KEY" ^
  -H "Content-Type: application/json" ^
  -d "{\"deadline\":\"2026-08-01\",\"display\":true}"
```


---



---

## 作业报告模板（需 API Key）

**URL**：`POST|DELETE /api/v1/tasks/<task_id>/template/`

**POST**（`multipart/form-data`）：字段 `file` = `.docx` 文件。上传成功后默认开启「允许学生下载」与「自动填封面」。

**DELETE**：删除模板并关闭相关开关。

作业设置 `GET/PATCH /api/v1/tasks/<id>/` 额外字段：

| 字段 | 说明 |
|------|------|
| has_template | 是否已有模板文件（只读，GET） |
| template_original_name | 原始文件名（只读，GET） |
| template_uploaded_at | 上传时间（只读，GET） |
| enable_template_download | 是否允许学生下载（可 PATCH） |
| enable_cover_autofill | 下载时是否自动填封面（可 PATCH） |

修改两个开关前须已上传模板。



---

## 作业框架预检规则包（需 API Key）

**URL**：`GET|PUT|DELETE /api/v1/tasks/<task_id>/precheck/`

**GET**：返回 `precheck_mode`、`precheck_fail_mode`、规则包、以及解析后的生效状态 `effective`。

**PUT** JSON 示例：

```json
{
  "precheck_mode": "cover_and_framework",
  "precheck_fail_mode": "block",
  "version": "1.0",
  "package": {
    "version": "1.0",
    "rules": [
      {"type": "contains", "text": "实验目的", "message": "缺少「实验目的」"},
      {"type": "contains_any", "texts": ["实验总结", "心得体会"], "message": "缺少总结类章节"},
      {"type": "min_chars", "value": 800, "message": "正文过短"}
    ]
  }
}
```

支持的 `rules[].type`：`contains` / `contains_any` / `contains_all` / `min_chars` / `regex`。

**封面日期内置校验**（封面出现「实验时间」「实验报告提交时间」时）：

- 须至少填到年月（可无日）；支持 `2026年5月6日`、`2026-5-6`、`2026/5/6`、两位年 `26年5月` 等
- 实验时间与当前系统日期相差不超过约半年；实验时间 ≤ 提交时间；提交时间 ≤ 作业截止日
- 若规则包要自行约束这两项，请任选其一以**跳过内置日期校验**：
  - 根级 `"skip_builtin_cover_dates": true` 或 `"cover_dates": "custom"`
  - 某条 rule 带 `"field"` / `"target"` / `"cover_field"` / `"label"` 为 `实验时间` 或 `实验报告提交时间`（或别名 `提交时间`）

**DELETE**：清空规则包（不自动改预检模式）。

课程总开关在网页「课程详情」配置；`precheck_mode=inherit` 且课程为「默认封面预检」时，**仅有报告模板的作业**会做封面预检。

## 定性成绩（需 API Key）

等级取值：A+ / A / B / C / D / F（F=不合格）。评语可选。  
可选 `score`：参考分，0–100 整数；仅教师/管理 API 可见，不参与不合格判定，不向学生端返回。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/v1/tasks/<task_id>/grades/ | 列出该作业全部成绩 |
| GET | /api/v1/tasks/<task_id>/grades/summary/ | 成绩汇总（进度/分布/名单） |
| PUT/PATCH | /api/v1/tasks/<task_id>/grades/<学号>/ | 按学号写入（须已有提交记录） |
| GET/PUT/PATCH | /api/v1/homeworks/<homework_id>/grade/ | 按提交记录 ID 读写 |

**写入示例 body**：
```json
{"letter_grade": "B", "score": 85, "comment": "结构完整"}
```

- 省略 `score`：不修改已有参考分（新建时为空）
- `"score": null` 或 `"score": ""`：清空参考分
- `score` 须为 **0–100 整数**（字符串数字亦可，如 `"85"`）

**教师侧序列化字段示例**（`for_student=false` / 管理 API）：
```json
{
  "letter_grade": "B",
  "score": 85,
  "comment": "结构完整",
  "is_fail": false,
  "needs_regrade": false,
  "graded_at": "2026-07-21T09:00:00+08:00",
  "graded_by": "teacher1",
  "updated_at": "2026-07-21T09:00:00+08:00"
}
```

说明：学生端页面仅当等级为 F 时可见（且不含参考分）；管理 API 始终返回完整成绩（含 `score`）。汇总接口按等级分布统计，参考分出现在名单明细中供导出使用，不单独做平均分。
