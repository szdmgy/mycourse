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

### 默认管理员

- 用户名：`admin`
- 密码：`admin123`

## 三种角色

### 管理员

- 导入课程数据（Excel 上传 → 预览确认 → 写入）
- 管理教师和学生账户（添加/删除/重置密码）
- 拥有教师的全部权限

### 教师

- 查看/管理所属课程
- 添加实验作业（支持 1~3 个附件位，每位独立命名和文件类型限制）
- 从历史课程复用实验配置
- 查看提交统计、批量下载学生作业（ZIP）
- 管理课程学生名单、查看延期提交记录

### 学生

- 查看已加入课程的作业列表
- 按附件位提交文件（支持覆盖重传）
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
