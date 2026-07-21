# 第一阶段设计（P0 + 超管身份切换）

> 2026-07-15。需求已确认；本文档对应第一阶段已实现/待验收范围。

## 范围

1. Homework：`submitted_at`（首次）+ `updated_at`（最后更新）；逾期按首次提交日期
2. API Key 鉴权骨架；作业可写 API（deadline / display）
3. 旧 `submission-status` 兼容，增加两套时间字段
4. 超级管理员身份切换（搜索、课程筛选、横幅、审计）

## 模型

- `Homework.submitted_at` / `Homework.updated_at`（移除原 `time`）
- `ImpersonationLog`：超管切换起停审计

## API

| 方法 | 路径 | 鉴权 |
|------|------|------|
| GET | `/api/v1/submission-status/` | 暂不强制（兼容）；响应含 `submitted_at`/`updated_at`，`submit_time`=首次 |
| GET/PATCH | `/api/v1/tasks/<id>/` | 必须 `Authorization: Bearer <API_KEY>` 或 `X-API-Key` |

## 身份切换

- Session：`impersonator_id` + `impersonate_as_id`
- 中间件在认证后替换 `request.user`，并设置 `request.impersonator`
- 禁止切换其他超管；顶栏横幅 + 一键恢复

## 环境变量

- `MYCOURSE_API_KEY`：管理 API 密钥（写入 `.env`）
