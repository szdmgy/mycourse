import logging
import openpyxl
from django.contrib.auth.models import User
from app01 import models

logger = logging.getLogger('app01')


# ═══════════════════════ 旧版一步式接口（保留兼容） ═══════════════════════

def extract_import_data(upload_file, file_format, **kwargs):
    if file_format == 'course':
        return extract_course_data(upload_file)
    elif file_format == 'task':
        course_id = kwargs.get('course_id')
        return extract_task_data(upload_file, course_id)
    elif file_format == 'student':
        return extract_student_data(upload_file)
    elif file_format == 'teacher':
        return extract_teacher_data(upload_file)
    elif file_format == 'user':
        return {'success': '用户数据文件解析成功'}
    else:
        return {'error': f'{upload_file}文件解析失败'}


def extract_course_data(upload_file):
    try:
        parsed = parse_course_excel(upload_file)
        if 'error' in parsed:
            return parsed
        write_course_data(parsed)
        return {'success': '课程数据文件解析成功'}
    except Exception as e:
        logger.exception("课程数据解析失败")
        return {'error': f'课程数据文件解析失败：{str(e)}'}


def extract_task_data(upload_file, course_id):
    """解析作业 Excel 并写入指定课程。
    Excel 列：A标题 B内容 C附件1名称 D附件1类型 E附件2名称 F附件2类型
              G附件3名称 H附件3类型 I显示(Y/N)
    课程由前端下拉框选定，截止日期默认导入日+120天。
    """
    from datetime import date, timedelta

    if not course_id:
        return {'error': '请先选择要导入的课程'}
    course = models.Course.objects.filter(id=course_id).first()
    if not course:
        return {'error': f'课程 ID={course_id} 不存在'}

    try:
        wb = openpyxl.load_workbook(upload_file)
        ws = wb[wb.sheetnames[0]]
        default_deadline = date.today() + timedelta(days=120)
        created, skipped = 0, 0

        for row in range(2, ws.max_row + 1):
            title = ws.cell(row, 1).value
            content = ws.cell(row, 2).value
            if not title or not content:
                break

            slot1Name = ws.cell(row, 3).value or ''
            slot1Type = ws.cell(row, 4).value or '*'
            slot2Name = ws.cell(row, 5).value or ''
            slot2Type = ws.cell(row, 6).value or ''
            slot3Name = ws.cell(row, 7).value or ''
            slot3Type = ws.cell(row, 8).value or ''
            display_val = ws.cell(row, 9).value
            display = False if str(display_val).strip().upper() == 'N' else True

            max_files = 1
            if slot2Name:
                max_files = 2
            if slot3Name:
                max_files = 3

            if models.Task.objects.filter(courseBelongTo=course, title=str(title).strip()).exists():
                skipped += 1
                continue

            models.Task.objects.create(
                title=str(title).strip(),
                content=str(content).strip(),
                courseBelongTo=course,
                deadline=default_deadline,
                display=display,
                maxFiles=max_files,
                slot1Name=slot1Name, slot1Type=slot1Type,
                slot2Name=slot2Name, slot2Type=slot2Type,
                slot3Name=slot3Name, slot3Type=slot3Type,
            )
            created += 1

        msg = f'导入完成：新增 {created} 个作业'
        if skipped:
            msg += f'，跳过 {skipped} 个同名作业'
        return {'success': msg}
    except Exception as e:
        logger.exception("作业数据解析失败")
        return {'error': f'作业数据文件解析失败：{str(e)}'}


def extract_student_data(upload_file):
    try:
        wb = openpyxl.load_workbook(upload_file)
        ws = wb[wb.sheetnames[0]]
        rows = ws.max_row
        student_list = []
        for row in range(1, rows + 1):
            number, name, sex = ws.cell(row, 1).value, ws.cell(row, 2).value, ws.cell(row, 3).value
            if number and name and sex:
                student_list.append([str(number), name, sex])
            else:
                break
        write_student_users(student_list)
        return {'success': '学生数据文件解析成功'}
    except Exception as e:
        logger.exception("学生数据解析失败")
        return {'error': f'学生数据文件解析失败：{str(e)}'}


def extract_teacher_data(upload_file):
    try:
        wb = openpyxl.load_workbook(upload_file)
        ws = wb[wb.sheetnames[0]]
        rows = ws.max_row
        teacher_list = []
        for row in range(1, rows + 1):
            number, name, sex = ws.cell(row, 1).value, ws.cell(row, 2).value, ws.cell(row, 3).value
            if number and name and sex:
                teacher_list.append([str(number), name, sex])
            else:
                break
        write_teacher_users(teacher_list)
        return {'success': '老师数据文件解析成功'}
    except Exception as e:
        logger.exception("教师数据解析失败")
        return {'error': f'老师数据文件解析失败：{str(e)}'}


# ═══════════════════════ 第一层：纯解析（不访问 DB） ═══════════════════════

def parse_course_excel(upload_file):
    """解析课程 Excel，返回结构化数据（不写库、不查库）"""
    try:
        wb = openpyxl.load_workbook(upload_file)
        ws = wb[wb.sheetnames[0]]

        def cell_str(row, col):
            v = ws.cell(row, col).value
            return str(v).strip() if v is not None else ''

        course_term = cell_str(3, 1)
        course_number = cell_str(5, 3)
        course_name = cell_str(5, 18)
        class_number = cell_str(5, 6)
        teachers_str = cell_str(6, 11)

        errors = []
        if not course_term:
            errors.append('学期（A3）为空')
        if not course_number:
            errors.append('课程编号（C5）为空')
        if not course_name:
            errors.append('课程名（R5）为空')
        if not class_number:
            errors.append('班号（F5）为空')

        teacher_names = [t.strip() for t in teachers_str.split(',') if t.strip()] if teachers_str else []

        students = []
        for row in range(10, ws.max_row + 1):
            number = ws.cell(row, 2).value
            name = ws.cell(row, 3).value
            sex = ws.cell(row, 4).value
            if not number and not name:
                break
            if number and name:
                students.append({
                    'number': str(number).strip(),
                    'name': str(name).strip(),
                    'gender': str(sex).strip() if sex else '男',
                })
            else:
                errors.append(f'第{row}行数据不完整：学号={number}, 姓名={name}')

        if errors:
            return {'error': '；'.join(errors)}

        return {
            'courseTerm': course_term,
            'courseNumber': course_number,
            'courseName': course_name,
            'classNumber': class_number,
            'teachers': teacher_names,
            'students': students,
        }
    except Exception as e:
        logger.exception("课程 Excel 解析异常")
        return {'error': f'文件解析失败：{str(e)}'}


# ═══════════════════════ 第二层：预览（读 DB 标注状态，不写 DB） ═══════════════════════

def preview_course_import(parsed):
    """对比 DB 标注每条数据的状态（新建/已存在/冲突），不写库"""
    result = {
        'course': {
            'courseTerm': parsed['courseTerm'],
            'courseNumber': parsed['courseNumber'],
            'courseName': parsed['courseName'],
            'classNumber': parsed['classNumber'],
        },
        'teachers': [],
        'students': [],
        'errors': [],
        'summary': {},
    }

    existing = models.Course.objects.filter(
        courseTerm=parsed['courseTerm'],
        courseNumber=parsed['courseNumber'],
        classNumber=parsed['classNumber'],
    ).first()
    result['course']['status'] = '已存在(将关联)' if existing else '新建'
    result['course']['exists'] = existing is not None

    for tname in parsed['teachers']:
        profile = models.UserProfile.objects.filter(name=tname, type='T').first()
        if profile:
            result['teachers'].append({
                'name': tname, 'number': profile.user.username, 'status': '已存在',
            })
        else:
            result['teachers'].append({
                'name': tname, 'number': '—', 'status': '仅关联名称(无账号)',
            })

    new_count = 0
    exist_count = 0
    error_count = 0
    for stu in parsed['students']:
        user = User.objects.filter(username=stu['number']).first()
        if user:
            profile = models.UserProfile.objects.filter(user=user).first()
            if profile and profile.name != stu['name']:
                result['students'].append({
                    **stu, 'status': f'已存在(姓名不一致: 库中={profile.name})',
                    'conflict': True,
                })
                error_count += 1
            else:
                result['students'].append({**stu, 'status': '已存在', 'conflict': False})
                exist_count += 1
        else:
            result['students'].append({**stu, 'status': '新建账号', 'conflict': False})
            new_count += 1

    result['summary'] = {
        'student_new': new_count,
        'student_exist': exist_count,
        'student_error': error_count,
        'student_total': len(parsed['students']),
        'teacher_count': len(parsed['teachers']),
        'course_status': result['course']['status'],
    }

    return result


# ═══════════════════════ 第三层：写入 DB ═══════════════════════

def write_course_data(parsed):
    """将解析后的课程数据写入数据库"""
    course_obj, created = models.Course.objects.get_or_create(
        courseTerm=parsed['courseTerm'],
        courseNumber=parsed['courseNumber'],
        classNumber=parsed['classNumber'],
        defaults={
            'courseName': parsed['courseName'],
            'teachers': ','.join(parsed['teachers']) if isinstance(parsed['teachers'], list) else parsed.get('teachers', ''),
        }
    )

    if isinstance(parsed['students'], list) and parsed['students']:
        if isinstance(parsed['students'][0], dict):
            student_list = [[s['number'], s['name'], s.get('gender', '男')] for s in parsed['students']]
        else:
            student_list = parsed['students']
    else:
        student_list = parsed.get('students', [])

    write_student_users(student_list)
    for stu in student_list:
        number = stu[0] if isinstance(stu, list) else stu['number']
        profile = models.UserProfile.objects.filter(user__username=number).first()
        if profile:
            course_obj.members.add(profile)

    teachers = parsed['teachers']
    if isinstance(teachers, str):
        teachers = [t.strip() for t in teachers.split(',') if t.strip()]
    for tname in teachers:
        profile = models.UserProfile.objects.filter(name=tname).first()
        if profile:
            course_obj.members.add(profile)

    return course_obj


def write_student_users(student_list):
    """创建学生账号（已存在则跳过）"""
    for stu in student_list:
        if isinstance(stu, dict):
            number, name, gender = stu['number'], stu['name'], stu.get('gender', '男')
        else:
            number, name, gender = stu[0], stu[1], stu[2] if len(stu) > 2 else '男'

        if not User.objects.filter(username=number).exists():
            user_obj = User.objects.create_user(username=number, password='szu' + number[-6:])
            models.UserProfile.objects.create(
                name=name, user=user_obj, type='S',
                gender='M' if gender == '男' else 'F',
            )


def write_teacher_users(teacher_list):
    """创建教师账号（已存在则跳过）"""
    for teacher in teacher_list:
        if isinstance(teacher, dict):
            number, name, gender = teacher['number'], teacher['name'], teacher.get('gender', '男')
        else:
            number, name, gender = teacher[0], teacher[1], teacher[2] if len(teacher) > 2 else '男'

        if not User.objects.filter(username=number).exists():
            User.objects.create_user(username=number, password='szu' + number)
            models.UserProfile.objects.create(
                name=name,
                user=User.objects.filter(username=number).first(),
                type='T',
                gender='M' if gender == '男' else 'F',
            )


def write_task_data(tasks):
    """已废弃，保留空壳兼容旧调用"""
    logger.warning("write_task_data 已废弃，请使用 extract_task_data(file, course_id)")
