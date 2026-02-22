import openpyxl
from django.contrib.auth.models import User, Group
from app01 import models

def extract_import_data(upload_file,file_format):
    if file_format == 'course':
        return extract_course_data(upload_file)
    elif file_format == 'task':
        return extract_task_data(upload_file)
    elif file_format == 'student':
        return extract_student_data(upload_file)
    elif file_format == 'teacher':
        return extract_teacher_data(upload_file)
    elif file_format == 'user':
        return {'success': f'用户数据文件解析成功'}
    else:
        return {'error': f'{upload_file}文件解析失败'}


def extract_course_data(upload_file):
    try:
        wb = openpyxl.load_workbook(upload_file)
        ws = wb[wb.sheetnames[0]]
        courseTerm = ws.cell(3,1).value.strip()
        courseNumber = ws.cell(5, 3).value.strip()
        courseName = ws.cell(5, 18).value.strip()
        classNumber = ws.cell(5, 6).value.strip()
        teachers = ws.cell(6, 11).value.strip()
        # print(f'courseTerm:{courseTerm}')
        # print(f'courseNumber:{courseNumber}')
        # print(f'courseName:{courseName}')
        # print(f'classNumber:{classNumber}')
        # print(f'teachers:{teachers}')

        rows = ws.max_row
        students = []
        for row in range(10,rows):
            number,name,sex = ws.cell(row,2).value,ws.cell(row,3).value,ws.cell(row,4).value
            # print(row,number,name,sex)
            if number and name and sex:
                students.append([str(number),name,sex])
            else:
                break
        # print(len(students))
        # for each in students:
        #     print(each)

        create_course_data({'courseTerm':courseTerm,'courseNumber':courseNumber,
                            'courseName':courseName,'classNumber':classNumber,
                            'teachers':teachers,'students':students})
        # cols = ws.max_column
        # print(f'rows:{rows}')
        # print(f'cols:{cols}')
        return {'success': f'课程数据文件解析成功'}
    except Exception as e:
        print(e)
        return {'error': f'课程数据文件解析失败：{str(e)}'}

def extract_task_data(upload_file):
    try:
        wb = openpyxl.load_workbook(upload_file)
        ws = wb[wb.sheetnames[0]]
        rows = ws.max_row
        tasks = []
        for row in range(2, rows+1):
            id, tilte, content,uploadFileType,display = ws.cell(row, 1).value, ws.cell(row, 2).value, \
                ws.cell(row, 3).value, ws.cell(row, 4).value, ws.cell(row, 5).value
            # print(row,id, tilte, content,uploadFileType,display)
            if id and tilte and content:
                if display=='Y':
                    display=True
                else:
                    display = False
                tasks.append([int(id), tilte, content,uploadFileType,display])
            else:
                break

        create_task_data(tasks)
        return {'success': f'作业数据文件解析成功'}
    except Exception as e:
        print(e)
        return {'error': f'作业数据文件解析失败：{str(e)}'}

def extract_student_data(upload_file):
    try:
        wb = openpyxl.load_workbook(upload_file)
        ws = wb[wb.sheetnames[0]]
        rows = ws.max_row
        student_list = []
        for row in range(1, rows+1):
            number, name, sex = ws.cell(row, 1).value, ws.cell(row, 2).value, ws.cell(row, 3).value
            # print(row,number,name,sex)
            if number and name and sex:
                student_list.append([str(number), name, sex])
            else:
                break
        create_student_user(student_list)
        return {'success': f'学生数据文件解析成功'}
    except Exception as e:
        print(e)
        return {'error': f'学生数据文件解析失败：{str(e)}'}

def extract_teacher_data(upload_file):
    try:
        wb = openpyxl.load_workbook(upload_file)
        ws = wb[wb.sheetnames[0]]
        rows = ws.max_row
        teacher_list = []
        for row in range(1, rows + 1):
            number, name, sex = ws.cell(row, 1).value, ws.cell(row, 2).value, ws.cell(row, 3).value
            print(row, number, name, sex)
            if number and name and sex:
                teacher_list.append([str(number), name, sex])
            else:
                break
        create_teacher_user(teacher_list)
        return {'success': f'老师数据文件解析成功'}
    except Exception as e:
        print(e)
        return {'error': f'老师数据文件解析失败：{str(e)}'}

def create_teacher_user(teacher_list):
    # 创建不存在的老师
    for teacher in teacher_list:
        if models.User.objects.filter(username=teacher[0]).count() == 0:
            models.User.objects.create_user(username=teacher[0],
                                            password='szu'+teacher[0])
            models.UserProfile.objects.create(name=teacher[1], user=models.User.objects.filter(
                username=teacher[0]).first(), type='T',
                                              gender='M' if teacher[2] == '男' else 'F')
            # member = models.User.objects.filter(username=teacher[0]).first()
            # teacherGroup = Group.objects.get(name='teacher')
            # teacherGroup.user_set.add(member)
            # member.is_staff = True
            # member.save()

def create_student_user(student_list):
    # 创建不存在的学生
    # print('创建不存在的学生')
    # print(student_list)
    for student in student_list:
        if models.User.objects.filter(username=student[0]).count() == 0:
            models.User.objects.create_user(username=student[0],
                                            password="szu" + student[0][4:])
            models.UserProfile.objects.create(name=student[1], user=models.User.objects.filter(
                username=student[0]).first(), type='S',
                                              gender='M' if student[2] == '男' else 'F')


def create_course_data(course):
    # 创建课程
    models.Course.objects.create(courseTerm=course['courseTerm'], courseNumber=course['courseNumber'],
        courseName=course['courseName'], classNumber=course['classNumber'],teachers=course['teachers'])
    # print('创建课程')
    # 获得刚创建的课程
    course_obj = models.Course.objects.filter(courseTerm=course['courseTerm'], courseNumber=course['courseNumber'],
                                 courseName=course['courseName'], classNumber=course['classNumber']).first()
    # print('获得刚创建的课程')
    # 添加学生
    create_student_user(course['students'])
    # print('创建学生')
    for student in course['students']:
        course_obj.members.add(models.UserProfile.objects.filter(user__username=student[0]).first())
    # print('添加学生')
    # 添加老师
    for teacher in course['teachers'].split(','):
        if models.UserProfile.objects.filter(name=teacher).count() > 0:
            course_obj.members.add(models.UserProfile.objects.filter(name=teacher).first())
    # print('添加老师')

def create_task_data(tasks):
    for task in tasks:
        course = models.Course.objects.filter(id=task[0]).first()
        if course:
            if models.Task.objects.filter(courseBelongTo=course,title=task[1]).count() == 0:
                print(f'create:courseBelongTo={course},title={task[1]}')
                models.Task.objects.create(title=task[1], content=task[2], uploadFileType=task[3],courseBelongTo=course,display=task[4])
            else:
                print(f'exist:courseBelongTo={course},title={task[1]}')