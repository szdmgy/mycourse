# mycourse — 实验报告收集系统

基于 Django 5.2 的教学实验报告在线收集系统，面向高校教师与学生使用。

## 快速启动

### 环境要求

- Python 3.10+
- Windows（启动脚本为 `.bat` 格式）

### 首次部署

```bash
cd mycourse/mycourse          # manage.py 所在目录
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
```

### 启动服务

| 用途 | 脚本 | 端口 |
|------|------|------|
| 本地调试 | `run_local.bat`（项目根目录） | 9900 |
| 生产部署 | `mycourse/mycourse/start_server.bat` | 8001（Waitress） |

双击对应 `.bat` 即可启动，脚本会自动激活虚拟环境并清理端口残留进程。

### Windows 一键部署/升级（Git 同步）

脚本：**`mycourse_deploy_update.bat`**（放在 **Git 仓库根目录**，与 `run_local.bat` 同级；详细步骤见 **[docs/服务器部署升级速查.md](docs/服务器部署升级速查.md)**）

- 每次执行前会显示 Git 根目录、Django 目录（`mycourse/mycourse/`）等信息，并要求输入 **`Y`** 确认，避免误操作。
- **放在本仓库根目录执行**：进入「升级模式」——在仓库根拉代码，在 **`mycourse/mycourse/`** 内检查 **`.env`** 与 **`db.sqlite3`**，再执行依赖更新、**`migrate`**、**`collectstatic`**（与 `expense_log` 的 `expense_log_deploy_update.bat` 流程对齐，并适配本仓库双层目录）。
- **放在非项目目录执行**（如 `D:\apps\`）：以 **`脚本目录\mycourse`** 为目标；若无仓库则 **首次部署**（`git clone` + 在 Django 目录创建 **`venv`** + 安装依赖），并提示将 **`.env`**（可从 **`mycourse/mycourse/.env.example`** 复制）、**`db.sqlite3`** 放到 **`mycourse/mycourse/`** 后 **再执行一次**；第二次运行会 **`git pull`**、**`migrate`**、**`collectstatic`**，用迁移把已复制的数据库升级到当前代码版本。
- 虚拟环境目录名为 **`venv`**，与现有 `run_local.bat` / `start_server.bat` 一致。

### 默认管理员

- 用户名：`admin`
- 密码：`admin123`

## 使用说明

- [学生使用说明](docs/使用说明-学生版.md)
- [教师使用说明](docs/使用说明-教师版.md)（含定性批改与参考分）
- [变更记录](docs/变更记录.md)（功能与修复合订，便于对照验收）
- [API 说明](mycourse/mycourse/docs/API说明.md)（提交状态、成绩、预检等，需 API Key）
- [服务器部署升级速查](docs/服务器部署升级速查.md)

## 三种角色

### 管理员

- 导入课程数据（Excel 上传 → 预览确认 → 写入）
- 管理教师和学生账户（添加/删除/重置密码）
- 拥有教师的全部权限

### 教师

- 查看/管理所属课程
- 添加实验作业（每作业 1 个附件，可限制文件类型；可挂报告模板）
- 从历史课程复用实验配置（含预检相关设置）
- 查看提交统计、批量下载学生作业（ZIP）、附件在线预览
- 定性批改（A+/A/B/C/D/F）+ 可选参考分（0–100，仅教师可见）
- 成绩汇总与 Excel 导出；管理学生名单、延期记录

### 学生

- 查看已加入课程的作业列表
- 提交附件（支持覆盖重传；可选报告模板下载与预检）
- 不合格（F）时可见提示并可重交待重评
- 首次登录强制修改密码
- 默认密码：`szu` + 学号后六位

## 数据导入

管理员通过 Excel 文件导入课程数据，支持两种方式：

1. **预览后确认导入**（推荐）：上传 → 解析预览 → 人工确认 → 写入
2. **直接导入**：上传后立即写入，支持课程/学生/教师/作业四种类型

Excel 格式：深圳大学学生成绩登记表标准格式。

## 技术栈

| 组件 | 版本 |
|------|------|
| Django | 5.2 |
| Bootstrap | 5.1.3（离线） |
| Bootstrap Icons | 1.11.3（离线） |
| jQuery | 3.x（离线） |
| 数据库 | SQLite |
| 生产服务器 | Waitress |

所有前端资源均为离线部署，无需外网访问。

## 项目结构

```
mycourse/
├── README.md
├── run_local.bat               # 开发调试启动脚本（端口 9900）
├── 当前工作状态.md              # AI 开发状态追踪
├── 需求文档.md                  # 完整需求规格
├── 开发计划.md                  # 分阶段实施计划
└── mycourse/mycourse/          # Django 项目目录
    ├── manage.py
    ├── start_server.bat        # 生产部署脚本（Waitress 端口 8001）
    ├── mycourse/               # Django 配置
    │   ├── settings.py
    │   ├── urls.py
    │   └── wsgi.py
    ├── app01/                  # 主应用
    │   ├── models.py           # 5 个模型
    │   ├── views.py            # 所有视图
    │   ├── utils.py            # 工具函数
    │   ├── upload_data.py      # Excel 导入（解析/预览/写入）
    │   └── admin.py
    ├── templates/              # 17 个模板（全部继承 base.html）
    └── static/                 # 静态资源
        ├── css/                # 3 个文件（Bootstrap 5 + Icons + 全局样式）
        ├── js/                 # 3 个文件（Bootstrap 5 bundle + jQuery + xlsx）
        └── fonts/              # Bootstrap Icons 字体
```
