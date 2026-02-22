import logging
import openpyxl
from django.contrib.auth.models import User
from app01 import models

logger = logging.getLogger('app01')


def extract_import_data(upload_file, file_format):
    if file_format == 'course':
        return extract_course_data(upload_file)
    elif file_format == 'task':
        return extract_task_data(upload_file)
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
        wb = openpyxl.load_workbook(upload_file)
        ws = wb[wb.sheetnames[0]]
        courseTerm = ws.cell(3, 1).value.strip()
        courseNumber = ws.cell(5, 3).value.strip()
        courseName = ws.cell(5, 18).value.strip()
        classNumber = ws.cell(5, 6).value.strip()
        teachers = ws.cell(6, 11).value.strip()

        rows = ws.max_row
        students = []
        for row in range(10, rows):
            number, name, sex = ws.cell(row, 2).value, ws.cell(row, 3).value, ws.cell(row, 4).value
            if number and name and sex:
                students.append([str(number), name, sex])
            else:
                break

        create_course_data({
            'courseTerm': courseTerm, 'courseNumber': courseNumber,
            'courseName': courseName, 'classNumber': classNumber,
            'teachers': teachers, 'students': students,
        })
        return {'success': '课程数据文件解析成功'}
    except Exception as e:
        logger.exception("课程数据解析失败")
        return {'error': f'课程数据文件解析失败：{str(e)}'}


def extract_task_data(upload_file):
    try:
        wb = openpyxl.load_workbook(upload_file)
        ws = wb[wb.sheetnames[0]]
        rows = ws.max_row
        tasks = []
        for row in range(2, rows + 1):
            id_val, title, content, uploadFileType, display = (
                ws.cell(row, 1).value, ws.cell(row, 2).value,
                ws.cell(row, 3).value, ws.cell(row, 4).value, ws.cell(row, 5).value
            )
            if id_val and title and content:
                display = True if display == 'Y' else False
                tasks.append([int(id_val), title, content, uploadFileType, display])
            else:
                break

        create_task_data(tasks)
        return {'success': '作业数据文件解析成功'}
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
        create_student_user(student_list)
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
        create_teacher_user(teacher_list)
        return {'success': '老师数据文件解析成功'}
    except Exception as e:
        logger.exception("教师数据解析失败")
        return {'error': f'老师数据文件解析失败：{str(e)}'}


def create_teacher_user(teacher_list):
    for teacher in teacher_list:
        if models.User.objects.filter(username=teacher[0]).count() == 0:
            models.User.objects.create_user(username=teacher[0], password='szu' + teacher[0])
            models.UserProfile.objects.create(
                name=teacher[1],
                user=models.User.objects.filter(username=teacher[0]).first(),
                type='T',
                gender='M' if teacher[2] == '男' else 'F',
            )


def create_student_user(student_list):
    for student in student_list:
        if models.User.objects.filter(username=student[0]).count() == 0:
            models.User.objects.create_user(username=student[0], password="szu" + student[0][4:])
            models.UserProfile.objects.create(
                name=student[1],
                user=models.User.objects.filter(username=student[0]).first(),
                type='S',
                gender='M' if student[2] == '男' else 'F',
            )


def create_course_data(course):
    models.Course.objects.create(
        courseTerm=course['courseTerm'], courseNumber=course['courseNumber'],
        courseName=course['courseName'], classNumber=course['classNumber'],
        teachers=course['teachers'],
    )
    course_obj = models.Course.objects.filter(
        courseTerm=course['courseTerm'], courseNumber=course['courseNumber'],
        courseName=course['courseName'], classNumber=course['classNumber'],
    ).first()
    create_student_user(course['students'])
    for student in course['students']:
        course_obj.members.add(models.UserProfile.objects.filter(user__username=student[0]).first())
    for teacher in course['teachers'].split(','):
        profile = models.UserProfile.objects.filter(name=teacher.strip()).first()
        if profile:
            course_obj.members.add(profile)


def create_task_data(tasks):
    for task in tasks:
        course = models.Course.objects.filter(id=task[0]).first()
        if course:
            if not models.Task.objects.filter(courseBelongTo=course, title=task[1]).exists():
                logger.info("创建作业: course=%s, title=%s", course, task[1])
                models.Task.objects.create(
                    title=task[1], content=task[2], uploadFileType=task[3],
                    courseBelongTo=course, display=task[4],
                )
