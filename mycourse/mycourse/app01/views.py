import json
import logging
import os
import tempfile
import zipfile

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.http import HttpResponse, HttpResponseRedirect, StreamingHttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods
from django import forms

from app01 import models
from app01.models import Task, UserProfile, HomeworkFile
from app01.upload_data import (
    extract_import_data, parse_course_excel, preview_course_import, write_course_data,
    parse_task_excel, write_task_import,
    parse_teacher_excel, preview_teacher_import, write_teacher_users,
)
from app01.utils import file_iterator, is_teacher_or_admin, get_display_name, safe_filename
from mycourse.settings import BASE_DIR, FILES_ROOT

logger = logging.getLogger('app01')

# ──────────────────────────── 认证相关 ────────────────────────────

def log_in(request):
    return render(request, 'login.html')


def log_out(request):
    logout(request)
    return HttpResponseRedirect('/login/')


def user(request):
    if request.method == 'GET':
        return render(request, 'login.html')

    uname = request.POST.get("uname", "")
    pwd = request.POST.get("pwd", "")
    user_obj = authenticate(request, username=uname, password=pwd)
    if user_obj is None:
        return HttpResponse("账户或密码不正确！")

    login(request, user_obj)

    if models.UserProfile.objects.filter(user=user_obj).count() == 0 and user_obj.is_superuser:
        models.UserProfile.objects.create(user=user_obj, name=user_obj.username, gender='M', type='T')
    profile = models.UserProfile.objects.filter(user=user_obj).first()
    request.session['loginUserName'] = profile.name

    if is_default_password(profile.type, uname, pwd):
        request.session['password_change_error'] = '你现在使用的是缺省密码，为了你的帐户安全，请立即修改密码！'
        return redirect('change_password')

    if profile.type == 'T' or user_obj.is_superuser:
        return HttpResponseRedirect('/teacherCourseList/')
    else:
        return HttpResponseRedirect('/studentCourseList/')


def is_default_password(user_type, name, password):
    if user_type == 'T':
        return ('szu' + name) == password
    else:
        return ('szu' + name[-6:]) == password


# ──────────────────────────── 用户设置 ────────────────────────────

@login_required
def change_password(request):
    success_msg = request.session.pop('password_change_success', None)
    error_msg = request.session.pop('password_change_error', None)

    if request.method == 'POST':
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user)
            request.session['password_change_success'] = '密码修改成功！'
            return redirect('change_password')
    else:
        form = PasswordChangeForm(user=request.user)

    context = {
        'type': 'T' if is_teacher_or_admin(request.user) else 'S',
        'name': get_display_name(request.user),
        'form': form,
        'success_msg': success_msg,
        'error_msg': error_msg,
    }
    return render(request, 'change_password.html', context)


class UserProfileEditForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['name', 'email', 'phone']
        widgets = {
            'name': forms.TextInput(attrs={'readonly': 'readonly', 'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'name': '姓名',
            'email': '邮箱',
            'phone': '手机号',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].initial = self.instance.name


@login_required
def profile_edit(request):
    profile = request.user.profile
    ok = False
    if request.method == 'POST':
        form = UserProfileEditForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            ok = True
    else:
        form = UserProfileEditForm(instance=profile)

    context = {
        'name': get_display_name(request.user),
        'ok': ok,
        'form': form,
        'profile': profile,
    }
    return render(request, 'profile.html', context)


class TaskDetailForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].disabled = True
            self.fields[field].widget.attrs['readonly'] = True


# ──────────────────────────── 学生端 ────────────────────────────

@login_required
def taskSubmit(request, taskID, taskTitle):
    if request.user.profile.type != 'S':
        return HttpResponse("您不是学生，无法进行该操作！")

    task = get_object_or_404(Task, pk=taskID)
    course = task.courseBelongTo

    homework = models.Homework.objects.filter(user=request.user.profile, task=task).first()

    hw_file = None
    if homework:
        hw_file = HomeworkFile.objects.filter(homework=homework).first()

    context = {
        'name': get_display_name(request.user),
        'course': course,
        'task': task,
        'hw_file': hw_file,
    }
    return render(request, 'studentSubmit.html', context)


@login_required
def studentCourse(request, courseTerm, courseName, classNumber):
    student = request.user.profile
    course = models.Course.objects.filter(
        courseTerm=courseTerm, courseName=courseName, classNumber=classNumber
    ).first()
    tasks = models.Task.objects.filter(courseBelongTo=course, display=True)

    taskRecords = []
    for task in tasks:
        homework = models.Homework.objects.filter(task=task, user=student).first()
        today = timezone.now().date()
        past_deadline = today > task.deadline

        if homework:
            has_file = HomeworkFile.objects.filter(homework=homework).exists()
            is_delay = homework.time.date() > task.deadline

            if is_delay:
                status = 'delay_submitted'
                status_text = '逾期提交'
            else:
                status = 'submitted'
                status_text = '已提交'

            taskRecords.append({
                'title': task.title, 'id': task.id,
                'time': homework.time, 'deadline': task.deadline,
                'status': status, 'status_text': status_text,
                'has_file': has_file,
            })
        else:
            if past_deadline:
                status = 'overdue'
                status_text = '逾期未提交'
            else:
                status = 'pending'
                status_text = '未提交'

            taskRecords.append({
                'title': task.title, 'id': task.id,
                'time': '', 'deadline': task.deadline,
                'status': status, 'status_text': status_text,
                'has_file': False,
            })

    context = {
        'taskRecords': taskRecords,
        'name': get_display_name(request.user),
        'course': course,
    }
    return render(request, 'studentTaskList.html', context)


@login_required
def studentGetTaskByCoursename(request, courseTerm, courseName, classNumber):
    return redirect('studentCourse', courseTerm=courseTerm,
                    courseName=courseName, classNumber=classNumber)


@login_required
def studentCourseList(request):
    courses = models.Course.objects.filter(members__user=request.user)
    courseList = [c for c in courses if c.status == 'Y']
    taskCountList = [models.Task.objects.filter(courseBelongTo=c).count() for c in courseList]

    context = {
        'course': zip(courseList, taskCountList) if courseList else None,
        'name': get_display_name(request.user),
    }
    return render(request, 'studentCourseList.html', context)


# ──────────────────────────── 学生上传/下载 ────────────────────────────

@login_required
def post_file(request):
    if request.FILES.get('file', '') == '':
        return HttpResponse('error')

    file_obj = request.FILES.get('file')
    suffix = file_obj.name.rsplit('.', 1)[-1] if '.' in file_obj.name else ''
    task_id = request.POST.get('taskId')
    task = models.Task.objects.get(id=task_id)

    if task.fileType != '*' and suffix:
        allowed = [t.strip().lower().lstrip('.') for t in task.fileType.split(',')]
        if suffix.lower() not in allowed:
            return HttpResponse(f'文件类型不允许，仅支持：{task.fileType}')

    title_safe = safe_filename(task.title)
    student_name = safe_filename(request.user.profile.name)
    rel_dir = os.path.join(
        'file', task.courseBelongTo.courseTerm,
        task.courseBelongTo.courseName + task.courseBelongTo.classNumber, title_safe
    )
    abs_dir = os.path.join(BASE_DIR, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    file_name = f'{title_safe}_{request.user.username}_{student_name}.{suffix}'
    rel_path = os.path.join(rel_dir, file_name)
    abs_path = os.path.join(BASE_DIR, rel_path)

    homework, _ = models.Homework.objects.get_or_create(
        user=request.user.profile, task=task
    )
    HomeworkFile.objects.update_or_create(
        homework=homework,
        defaults={'filePath': rel_path, 'originalName': file_obj.name}
    )

    with open(abs_path, 'wb') as f:
        f.write(file_obj.read())

    logger.info("文件上传: %s -> %s", request.user.username, file_name)
    return HttpResponse('YES')


@login_required
def download_file(request):
    """旧版下载接口（保留向后兼容）"""
    if request.GET.get('url', '') == '':
        return HttpResponse('error')

    filename = request.GET["url"]
    taskid = request.GET["task"]
    task = models.Task.objects.filter(id=taskid).first()
    title = safe_filename(task.title)
    filename = safe_filename(filename)
    course = task.courseBelongTo

    file_path = os.path.join(
        BASE_DIR, 'file', course.courseTerm,
        course.courseName + course.classNumber, title, filename
    )

    response = StreamingHttpResponse(file_iterator(file_path))
    response['Content-Type'] = 'application/octet-stream'
    response['Content-Disposition'] = 'attachment;filename=' + filename.encode('utf-8').decode('ISO-8859-1')
    return response


@login_required
def download_homework_file(request, file_id):
    """通过 HomeworkFile ID 下载文件（推荐使用）"""
    hw_file = get_object_or_404(HomeworkFile, pk=file_id)

    if not is_teacher_or_admin(request.user):
        if hw_file.homework.user != request.user.profile:
            return HttpResponse("无权下载此文件")

    file_path = hw_file.absPath
    if not os.path.exists(file_path):
        return HttpResponse("文件不存在")

    filename = hw_file.standardName
    response = StreamingHttpResponse(file_iterator(file_path))
    response['Content-Type'] = 'application/octet-stream'
    response['Content-Disposition'] = 'attachment;filename=' + filename.encode('utf-8').decode('ISO-8859-1')
    return response


# ──────────────────────────── 教师端 ────────────────────────────

@login_required
def teacherGetTaskByCoursename(request, courseTerm, courseName, classNumber):
    return redirect('teacherCourseChange', courseTerm=courseTerm,
                    courseName=courseName, classNumber=classNumber)


@login_required
def teacherCourseList(request):
    from django.db.models import Count
    from collections import OrderedDict

    isManager = request.user.is_superuser
    if isManager:
        courses = models.Course.objects.filter(status='Y')
    else:
        courses = models.Course.objects.filter(members__user=request.user, status='Y')

    courses = courses.annotate(task_count=Count('task')).order_by('-courseTerm', 'courseName')

    term_groups = OrderedDict()
    for c in courses:
        term_groups.setdefault(c.courseTerm, []).append(c)

    context = {
        'term_groups': term_groups,
        'total_courses': courses.count(),
        'isManager': isManager,
        'name': get_display_name(request.user),
    }
    return render(request, 'teacherCourseList.html', context)


@login_required
@require_POST
def teacherDownloadByHomeworknameAndStudentnumber(request):
    data = json.loads(request.body.decode("utf-8"))
    taskId = data["taskId"]
    downloadTask = models.Task.objects.filter(id=int(taskId)).first()
    if not downloadTask:
        return HttpResponse("作业不存在")

    file_entries = []
    for studentNumber in data["studentNumberList"]:
        homework = models.Homework.objects.filter(
            task=downloadTask, user__user__username=studentNumber
        ).last()
        if homework:
            hw_file = HomeworkFile.objects.filter(homework=homework).first()
            if hw_file and os.path.exists(hw_file.absPath):
                file_entries.append(('', os.path.basename(hw_file.absPath), hw_file.absPath))

    if not file_entries:
        return HttpResponse("没有可下载的文件")

    if len(file_entries) == 1 and len(data["studentNumberList"]) == 1:
        filepath = file_entries[0][2]
        fileName = os.path.basename(filepath)
        logger.info("下载文件: %s", fileName)
        response = StreamingHttpResponse(file_iterator(filepath))
        response['Content-Type'] = 'application/octet-stream'
        response['Content-Disposition'] = 'attachment;filename=' + fileName.encode('utf-8').decode('ISO-8859-1')
        return response

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    with zipfile.ZipFile(tmp, mode="w", compression=zipfile.ZIP_STORED) as zf:
        for student_dir, arc_name, filepath in file_entries:
            zf.write(filepath, arc_name)
    tmp.close()

    zip_path = tmp.name
    zipName = safe_filename(downloadTask.title) + ".zip"

    def stream_and_cleanup():
        try:
            yield from file_iterator(zip_path)
        finally:
            try:
                os.unlink(zip_path)
            except OSError:
                pass

    response = StreamingHttpResponse(stream_and_cleanup())
    response['Content-Type'] = 'application/octet-stream'
    response['Content-Disposition'] = 'attachment;filename=' + zipName.encode('utf-8').decode('ISO-8859-1')
    return response


@login_required
@require_POST
def addHomework(request):
    if not is_teacher_or_admin(request.user):
        return HttpResponse("您没有权限添加作业！")

    homeworkTitle = request.POST.get('title', "")
    homeworkContent = request.POST.get('content', "") or f"请完成{homeworkTitle}"
    courseID = request.POST.get('courseID', "")
    if not courseID:
        courseNumber = request.POST.get('courseNumber', "")
        courseName = request.POST.get('courseName', "")
        if not courseName or not courseNumber:
            return HttpResponse("任务失败")
        course = models.Course.objects.filter(courseNumber=courseNumber, courseName=courseName).first()
    else:
        course = models.Course.objects.filter(id=int(courseID)).first()

    if not course:
        return HttpResponse("课程不存在")
    if not homeworkTitle:
        return HttpResponse("作业标题不能为空")
    if models.Task.objects.filter(courseBelongTo=course, title=homeworkTitle).exists():
        return HttpResponse("作业标题已经存在")

    deadline_str = request.POST.get('deadline', '')
    fileType = request.POST.get('fileType', '') or '*'

    task_data = dict(
        title=homeworkTitle, content=homeworkContent,
        courseBelongTo=course, fileType=fileType,
    )
    if deadline_str:
        from datetime import date as _date
        task_data['deadline'] = _date.fromisoformat(deadline_str)

    models.Task.objects.create(**task_data)
    return HttpResponseRedirect(request.headers.get("Referer"))


@login_required
@require_POST
def addCourse(request):
    if not is_teacher_or_admin(request.user):
        return HttpResponse("您没有权限添加课程！")

    courseName = request.POST.get('courseName', "")
    courseNumber = request.POST.get('courseNumber', "")
    studentList = request.POST.get('studentList', "")

    if not courseName or not courseNumber or not studentList:
        return HttpResponse("课程信息有错误，请重新填写")
    if models.Course.objects.filter(courseName=courseName, courseNumber=courseNumber).exists():
        return HttpResponse("该课程已经存在！无法添加")

    studentList = [s for s in studentList.split(';') if s]

    for studentStr in studentList:
        parts = studentStr.split(',')
        if models.User.objects.filter(username=parts[0]).count() == 0:
            models.User.objects.create_user(username=parts[0], password="szu" + parts[0][4:])
            models.UserProfile.objects.create(
                name=parts[1], user=models.User.objects.filter(username=parts[0]).first(),
                type='S', gender='M' if parts[2] == '男' else 'F'
            )

    models.Course.objects.create(courseName=courseName, courseNumber=courseNumber)
    course = models.Course.objects.filter(courseName=courseName, courseNumber=courseNumber).first()
    for studentStr in studentList:
        parts = studentStr.split(',')
        course.members.add(models.UserProfile.objects.filter(user__username=parts[0]).first())
    course.members.add(models.UserProfile.objects.filter(user=request.user).first())

    return HttpResponseRedirect(request.headers.get("Referer"))


@login_required
def deleteCourse(request, courseNumber, courseName):
    if not request.user.is_superuser:
        return HttpResponse("仅管理员可以删除课程！")
    course = models.Course.objects.filter(courseName=courseName, courseNumber=courseNumber).first()
    if course:
        course.delete()
    return HttpResponseRedirect('/teacherCourseList/')


@login_required
@require_POST
def changeCourseMsgByTeacher(request):
    if not is_teacher_or_admin(request.user):
        return HttpResponse("您没有权限修改课程信息！")

    courseNumber = request.POST.get("courseNumber")
    courseName = request.POST.get("courseName")
    changedCourseName = request.POST.get("changedCourseName")
    changedCourseNumber = request.POST.get("changedCourseNumber")

    if not changedCourseName or not changedCourseNumber:
        return HttpResponseRedirect(request.headers.get('Referer'))

    course = models.Course.objects.filter(courseNumber=courseNumber, courseName=courseName).first()
    if not course:
        return HttpResponse("该课程不存在！请重试！")
    course.courseName = changedCourseName
    course.courseNumber = changedCourseNumber
    course.status = 'Y'
    course.save()

    return HttpResponseRedirect('/teacherCourseList/')


@login_required
def deleteTaskByTeacher(request, taskId):
    if not is_teacher_or_admin(request.user):
        return HttpResponse("您没有权限删除该作业！")
    task = models.Task.objects.filter(id=taskId).first()
    if not task:
        return HttpResponse("该作业不存在！无法删除该作业！")
    task.delete()
    return HttpResponseRedirect(request.headers.get('Referer'))


@login_required
def removeStudentFromCourse(request, courseNumber, courseName, studentNumber):
    if not is_teacher_or_admin(request.user):
        return HttpResponse("您没有权限进行该操作！")

    course = models.Course.objects.filter(courseNumber=courseNumber, courseName=courseName).first()
    if not course or models.User.objects.filter(username=studentNumber).count() == 0:
        return HttpResponse("此课程或此学生不存在！")
    student = models.UserProfile.objects.filter(user__username=studentNumber).first()
    course.members.remove(student)

    return HttpResponseRedirect(request.headers.get('Referer'))


@login_required
def removeStudent(request, courseID, studentNumber):
    if not is_teacher_or_admin(request.user):
        return HttpResponse("您没有权限进行该操作！")

    course = models.Course.objects.filter(id=courseID).first()
    if not course or models.User.objects.filter(username=studentNumber).count() == 0:
        return HttpResponse("此课程或此学生不存在！")
    student = models.UserProfile.objects.filter(user__username=studentNumber).first()
    course.members.remove(student)

    return HttpResponseRedirect(request.headers.get('Referer'))


@login_required
def delayRecords(request, courseID):
    if not is_teacher_or_admin(request.user):
        return HttpResponse("您没有权限进行该操作！")
    try:
        course = models.Course.objects.filter(id=courseID).first()
        tasks = list(models.Task.objects.filter(courseBelongTo=course))
        students = course.members.filter(type='S')

        records = []
        for task in tasks:
            for student in students:
                homework = models.Homework.objects.filter(task=task, user=student).first()
                if homework:
                    has_file = HomeworkFile.objects.filter(homework=homework).exists()
                    is_delay = homework.time.date() > task.deadline
                    if is_delay:
                        records.append({
                            'title': task.title, 'name': student.name,
                            'number': student.user.username,
                            'time': homework.time, 'deadline': task.deadline,
                            'status': '延期提交',
                            'has_file': has_file,
                        })
                else:
                    if timezone.now().date() > task.deadline:
                        records.append({
                            'title': task.title, 'name': student.name,
                            'number': student.user.username,
                            'time': '', 'deadline': task.deadline,
                            'status': '未提交',
                            'has_file': False,
                        })

        context = {
            'name': get_display_name(request.user),
            'course': course,
            'records': records,
        }
        return render(request, 'delayRecords.html', context)
    except Exception as e:
        logger.exception("delayRecords 异常")
        return HttpResponse(str(e))


@login_required
def homeworkRecords(request, taskID, taskTitle):
    if not is_teacher_or_admin(request.user):
        return HttpResponse("您没有权限进行该操作！")
    try:
        task = Task.objects.get(id=taskID)
        course = task.courseBelongTo
        students = course.members.filter(type='S')
        homeworks = models.Homework.objects.filter(task=task)

        submitStudents = []
        submitRecords = []
        notSubmitStudents = []

        for hw in homeworks:
            if hw.user in students:
                submitStudents.append(hw.user)
                hw_file = HomeworkFile.objects.filter(homework=hw).first()
                submitRecords.append({
                    'number': hw.user.user.username,
                    'name': hw.user.name,
                    'gender': hw.user.gender,
                    'time': hw.time,
                    'delay': hw.time.date() > task.deadline,
                    'file_name': os.path.basename(hw_file.filePath) if hw_file else '',
                    'file_id': hw_file.id if hw_file else None,
                    'has_file': hw_file is not None,
                })

        for student in students:
            if student not in submitStudents:
                notSubmitStudents.append({
                    'number': student.user.username,
                    'name': student.name,
                    'gender': student.gender,
                })

        context = {
            'name': get_display_name(request.user),
            'course': course,
            'task': task,
            'submitRecords': submitRecords,
            'notSubmitStudents': notSubmitStudents,
        }
        return render(request, 'homeworkRecords.html', context)
    except Task.DoesNotExist:
        return HttpResponse(f'{taskTitle}不存在')


@login_required
@require_POST
def resetPassword(request):
    try:
        username = request.POST.get('user')
        profile = models.UserProfile.objects.filter(user__username=username).first()
        if not profile:
            return HttpResponse(f'用户 {username} 不存在')
        user_obj = profile.user
        if profile.type == 'T':
            user_obj.set_password('szu' + username)
        else:
            user_obj.set_password('szu' + username[-6:])
        user_obj.save()
        logger.info("密码重置: %s", username)
        return HttpResponse(f'学号：{username}的用户密码重置成功！')
    except Exception as e:
        logger.exception("resetPassword 异常")
        return HttpResponse(str(e))


class TaskEditForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['title', 'content', 'display', 'deadline', 'fileType']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'content': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'display': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'deadline': forms.DateInput(format='%Y-%m-%d',
                                        attrs={'type': 'date', 'class': 'form-control'}),
            'fileType': forms.TextInput(attrs={'class': 'form-control',
                                               'placeholder': '如 .docx,.pdf 或 * 表示不限'}),
        }
        labels = {
            'title': '作业标题',
            'content': '作业正文',
            'display': '是否显示',
            'deadline': '截止日期',
            'fileType': '允许的文件类型',
        }


@login_required
def taskChange(request, taskID, taskTitle):
    if not is_teacher_or_admin(request.user):
        return HttpResponse("您没有权限进行该操作！")
    try:
        task = Task.objects.get(id=taskID)
    except Task.DoesNotExist:
        return HttpResponse(f'{taskTitle}不存在')

    if request.method == 'POST':
        form = TaskEditForm(request.POST, instance=task)
        if form.is_valid():
            form.save()
            course = task.courseBelongTo
            return redirect('teacherCourseChange', course.courseTerm, course.courseName, course.classNumber)
    else:
        form = TaskEditForm(instance=task)

    submitted_count = models.Homework.objects.filter(task=task).count()
    context = {
        'task': task,
        'form': form,
        'name': get_display_name(request.user),
        'course': task.courseBelongTo,
        'submitted_count': submitted_count,
        'original_title': task.title,
    }
    return render(request, 'taskChange.html', context)


@login_required
@require_POST
def addStudentToCourseByTeacher(request):
    if not is_teacher_or_admin(request.user):
        return HttpResponse("您没有权限修改课程信息！")

    studentName = request.POST.get("newStudentName", "")
    studentNumber = request.POST.get("newStudentNumber", "")
    studentGender = request.POST.get("newStudentGender", "")
    courseID = request.POST.get("courseID", "")

    if not studentName or not studentNumber or not studentGender:
        return HttpResponse("填入的参数有误，请重试！")
    course = models.Course.objects.filter(id=courseID).first()
    if not course:
        return HttpResponse("该课程不存在，请重试")

    profile = models.UserProfile.objects.filter(user__username=studentNumber).first()
    if not profile:
        user_obj = models.User.objects.create_user(username=studentNumber, password="szu" + studentNumber[4:])
        profile = models.UserProfile.objects.create(user=user_obj, name=studentName, gender=studentGender, type='S')
    course.members.add(profile)
    return HttpResponseRedirect(request.headers.get('Referer'))


@login_required
def downloadStudentListTemplate(request):
    if not is_teacher_or_admin(request.user):
        return HttpResponse("您没有权限下载！")

    file_path = os.path.join(FILES_ROOT, 'student_list_template.xlsx')
    fileName = os.path.basename(file_path)
    response = StreamingHttpResponse(file_iterator(file_path))
    response['Content-Type'] = 'application/octet-stream'
    response['Content-Disposition'] = 'attachment;filename=' + fileName.encode('utf-8').decode('ISO-8859-1')
    return response


# ──────────────────────────── 管理员端 ────────────────────────────

@login_required
def manager(request):
    if not request.user.is_superuser:
        return HttpResponse("警告！您不是管理员！无法进入此界面！")
    context = {'name': get_display_name(request.user)}
    return render(request, 'manager.html', context)


@login_required
def user_list(request):
    if not request.user.is_superuser:
        return HttpResponse("警告！您不是管理员！无法进入此界面！")

    context = {
        'teacherList': models.UserProfile.objects.filter(type='T'),
        'studentList': models.UserProfile.objects.filter(type='S'),
        'name': get_display_name(request.user),
    }
    return render(request, 'userList.html', context)


@login_required
def remove_user(request, username):
    if not request.user.is_superuser:
        return HttpResponse("警告！您不是管理员！无法进入此界面！")
    user_obj = models.User.objects.filter(username=username).first()
    if not user_obj:
        return HttpResponse("该用户不存在，无法删除")
    if user_obj.is_superuser:
        return HttpResponse("无法删除管理员！")

    user_obj.delete()
    logger.info("删除用户: %s", username)
    return HttpResponseRedirect(request.headers.get('Referer'))


@login_required
@require_POST
def addMemberByManager(request):
    if not request.user.is_superuser:
        return HttpResponse("您不是管理员，无法添加！")

    memberType = request.POST.get('memberType', '')
    memberName = request.POST.get('memberName', '')
    memberNumber = request.POST.get('memberNumber', '')
    memberGender = request.POST.get('memberGender', '')
    memberPassword = "szu" + memberNumber if memberType == 'teacher' else "szu" + memberNumber[4:]

    if not memberType or not memberName or not memberNumber or not memberGender:
        return HttpResponse("成员信息缺失！请重新添加！")
    if models.User.objects.filter(username=memberNumber).exists():
        return HttpResponse("该成员已存在！无法添加！")

    models.User.objects.create_user(username=memberNumber, password=memberPassword)
    member = models.User.objects.filter(username=memberNumber).first()
    models.UserProfile.objects.create(
        name=memberName,
        type='T' if memberType == 'teacher' else 'S',
        gender='M' if memberGender == 'male' else 'F',
        user=member,
    )
    return HttpResponseRedirect(request.headers.get("Referer"))


@login_required
def deleteMemberByManager(request, memberNumber):
    if not request.user.is_superuser:
        return HttpResponse("您不是管理员，无法删除！")
    user_obj = models.User.objects.filter(username=memberNumber).first()
    if not user_obj:
        return HttpResponse("该用户不存在，无法删除")
    if user_obj.is_superuser:
        return HttpResponse("无法删除管理员！")
    user_obj.delete()
    logger.info("删除用户: %s", memberNumber)
    return HttpResponseRedirect(request.headers.get('Referer'))


# ──────────────────────────── 数据导入 ────────────────────────────

@login_required
def file_upload_course(request):
    if not is_teacher_or_admin(request.user):
        return HttpResponse("您没有权限进行该操作！")
    if request.method == 'POST':
        return HttpResponse('file_upload_course post')

    context = {
        'upload_route': '/upload-files/course/',
        'datatype': 'course',
        'name': get_display_name(request.user),
        'allowed_extensions': ".xls,.xlsx,.xlsm",
    }
    return render(request, 'upload_files.html', context)


@login_required
def file_upload_view(request, type):
    upload_files = {
        'course': '上传课程文件(excel文件)',
        'task': '上传作业文件(excel文件)',
        'teacher': '上传老师文件(excel文件)',
        'student': '上传学生文件(excel文件)',
        'user': '上传用户文件(excel文件)',
    }
    file_text = upload_files.get(type, '未知数据类型，路由错误，请更新路由后重新访问')

    context = {
        'name': get_display_name(request.user),
        'datatype': type,
        'file_text': file_text,
        'allowed_extensions': ".xls,.xlsx,.xlsm",
    }
    return render(request, 'upload_files.html', context)


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def process_files(request):
    try:
        files = []
        file_index = 0
        datatype = request.POST.get('datatype', '未知')
        while f'file_{file_index}' in request.FILES:
            files.append(request.FILES[f'file_{file_index}'])
            file_index += 1

        if not files:
            return JsonResponse({
                'success': False, 'error': '未收到任何文件', 'file_count': 0,
            }, status=400)

        results = []
        for uploaded_file in files:
            result = extract_import_data(uploaded_file, datatype)
            status = result.get('success', result.get('error', '未知状态'))
            results.append({'filename': uploaded_file.name, 'status': status})

        return JsonResponse({
            'success': True, 'file_count': len(files), 'results': results,
        })
    except Exception as e:
        logger.exception("process_files 异常")
        return JsonResponse({
            'success': False, 'error': f'处理失败: {str(e)}',
        }, status=500)


@login_required
def import_data(request):
    """数据导入入口页面"""
    if not request.user.is_superuser:
        return HttpResponse("警告！您不是管理员！无法进入此界面！")
    return render(request, 'import.html')


@login_required
@require_POST
def preview_import(request):
    """解析 → 预览（不写库），将解析数据存入 session"""
    if not is_teacher_or_admin(request.user):
        return HttpResponse("您没有权限进行该操作！")

    upload_file = request.FILES.get('upload_file')
    datatype = request.POST.get('datatype', 'course')
    source = request.POST.get('source', 'admin')

    def _ctx(**extra):
        ctx = {'name': get_display_name(request.user), 'source': source}
        ctx.update(extra)
        return ctx

    if not upload_file:
        return render(request, 'import_preview.html', _ctx(error='请选择文件'))

    if datatype == 'course':
        parsed = parse_course_excel(upload_file)
        if 'error' in parsed:
            return render(request, 'import_preview.html', _ctx(error=parsed['error']))

        if source == 'teacher' and not request.user.is_superuser:
            teacher_name = request.user.profile.name
            if teacher_name not in parsed.get('teachers', []):
                return render(request, 'import_preview.html', _ctx(
                    error=f'您的姓名（{teacher_name}）不在该课程的教师名单中，无法导入他人课程。'
                         f'Excel 中的教师为：{"、".join(parsed.get("teachers", []))}'
                ))

        preview = preview_course_import(parsed)
        request.session['import_parsed_data'] = parsed
        request.session['import_datatype'] = 'course'
        request.session['import_source'] = source
        return render(request, 'import_preview.html', _ctx(preview=preview, datatype='course'))

    elif datatype == 'teacher':
        if not request.user.is_superuser:
            return render(request, 'import_preview.html', _ctx(error='仅管理员可导入教师数据'))
        parsed = parse_teacher_excel(upload_file)
        if 'error' in parsed:
            return render(request, 'import_preview.html', _ctx(error=parsed['error']))
        preview = preview_teacher_import(parsed)
        request.session['import_parsed_data'] = parsed
        request.session['import_datatype'] = 'teacher'
        request.session['import_source'] = source
        return render(request, 'import_preview.html', _ctx(preview=preview, datatype='teacher'))

    else:
        return render(request, 'import_preview.html', _ctx(error=f'不支持的导入类型：{datatype}'))


@login_required
@require_POST
def confirm_import(request):
    """确认导入：从 session 取数据写入 DB"""
    if not is_teacher_or_admin(request.user):
        return HttpResponse("您没有权限进行该操作！")

    parsed = request.session.pop('import_parsed_data', None)
    datatype = request.session.pop('import_datatype', None)
    source = request.session.pop('import_source', 'admin')

    def _ctx(**extra):
        ctx = {'name': get_display_name(request.user), 'source': source}
        ctx.update(extra)
        return ctx

    if not parsed:
        return render(request, 'import_preview.html', _ctx(error='预览数据已过期，请重新上传文件'))

    if source == 'teacher' and datatype == 'course' and not request.user.is_superuser:
        teacher_name = request.user.profile.name
        if teacher_name not in parsed.get('teachers', []):
            return render(request, 'import_preview.html', _ctx(
                error=f'安全校验失败：您的姓名（{teacher_name}）不在该课程的教师名单中'
            ))

    try:
        if datatype == 'course':
            existing = models.Course.objects.filter(
                courseTerm=parsed['courseTerm'],
                courseNumber=parsed['courseNumber'],
                classNumber=parsed['classNumber'],
            ).exists()
            course_obj = write_course_data(parsed)
            if existing:
                result_msg = (
                    f"名单更新成功！课程：{parsed['courseName']}（{parsed['courseNumber']}）"
                    f"班号 {parsed['classNumber']}，当前学生 {len(parsed['students'])} 人"
                )
            else:
                result_msg = (
                    f"导入成功！课程：{parsed['courseName']}（{parsed['courseNumber']}）"
                    f"班号 {parsed['classNumber']}，学生 {len(parsed['students'])} 人"
                )
        elif datatype == 'teacher':
            write_teacher_users(parsed['teachers'])
            result_msg = f"导入成功！共处理 {len(parsed['teachers'])} 名教师"
        else:
            result_msg = '导入完成'

        return render(request, 'import_preview.html', _ctx(success=result_msg))
    except Exception as e:
        logger.exception("confirm_import 写入失败")
        return render(request, 'import_preview.html', _ctx(error=f'写入数据库失败：{str(e)}'))


@login_required
def teacher_course_change(request, courseTerm, courseName, classNumber):
    course = models.Course.objects.filter(
        courseTerm=courseTerm, courseName=courseName, classNumber=classNumber
    ).first()
    if not course:
        return HttpResponse("课程不存在")

    students = course.members.filter(type='S')
    tasks = list(models.Task.objects.filter(courseBelongTo=course))

    task_data = []
    for task in tasks:
        submitted, not_submitted, seen = [], [], set()
        for hw in models.Homework.objects.filter(task=task):
            if hw.user.pk in seen or hw.user not in students:
                continue
            seen.add(hw.user.pk)
            has_file = HomeworkFile.objects.filter(homework=hw).exists()
            submitted.append({
                'number': hw.user.user.username,
                'name': hw.user.name,
                'gender': hw.user.gender,
                'time': hw.time,
                'delay': hw.time.date() > task.deadline,
                'has_file': has_file,
            })
        for student in students:
            if student.pk not in seen:
                not_submitted.append(student)
        task_data.append({
            'task': task,
            'submitted': submitted,
            'not_submitted': not_submitted,
            'submitted_count': len(submitted),
            'not_submitted_count': len(not_submitted),
        })

    context = {
        'task_data': task_data,
        'student_list': students,
        'student_count': students.count(),
        'name': get_display_name(request.user),
        'course': course,
    }
    return render(request, 'teacherCourseDetail.html', context)


@login_required
def getHistoryTasks(request, courseID):
    """获取可复用的历史实验列表（JSON API）——仅返回同名课程"""
    if not is_teacher_or_admin(request.user):
        return JsonResponse({'error': '无权限'}, status=403)

    current_course = get_object_or_404(models.Course, pk=courseID)

    if request.user.is_superuser:
        courses = models.Course.objects.filter(
            courseName=current_course.courseName
        ).exclude(pk=courseID)
    else:
        courses = models.Course.objects.filter(
            members__user=request.user,
            courseName=current_course.courseName
        ).exclude(pk=courseID)

    existing_titles = set(
        models.Task.objects.filter(courseBelongTo=current_course)
        .values_list('title', flat=True)
    )

    result = []
    for course in courses.distinct():
        tasks = models.Task.objects.filter(courseBelongTo=course)
        if not tasks.exists():
            continue
        task_list = []
        for t in tasks:
            task_list.append({
                'id': t.id, 'title': t.title,
                'content': t.content[:100],
                'fileType': t.fileType,
                'duplicate': t.title in existing_titles,
            })
        result.append({
            'courseID': course.id,
            'courseTerm': course.courseTerm,
            'courseName': course.courseName,
            'classNumber': course.classNumber,
            'tasks': task_list,
        })

    return JsonResponse({'courses': result})


@login_required
@require_POST
def copyTasks(request):
    """复用历史实验：将选中的实验复制到目标课程"""
    if not is_teacher_or_admin(request.user):
        return JsonResponse({'error': '无权限'}, status=403)

    data = json.loads(request.body.decode('utf-8'))
    course_id = data.get('courseID')
    task_ids = data.get('taskIDs', [])

    target_course = get_object_or_404(models.Course, pk=course_id)

    copied = []
    errors = []
    for task_id in task_ids:
        try:
            src = models.Task.objects.get(pk=task_id)
            new_title = src.title
            while models.Task.objects.filter(courseBelongTo=target_course, title=new_title).exists():
                new_title += '(副本)'
            models.Task.objects.create(
                title=new_title, content=src.content,
                courseBelongTo=target_course,
                fileType=src.fileType,
            )
            copied.append(new_title)
        except models.Task.DoesNotExist:
            errors.append(f'实验 ID={task_id} 不存在')

    return JsonResponse({'success': True, 'copied': copied, 'errors': errors})


@login_required
@require_POST
def preview_task_import(request):
    """AJAX: 接收 Excel 文件 + courseID，解析后返回预览 JSON，数据存 session。"""
    if not request.user.is_superuser:
        return JsonResponse({'error': '仅管理员可执行此操作'}, status=403)

    course_id = request.POST.get('course_id')
    upload_file = request.FILES.get('file')
    if not course_id or not upload_file:
        return JsonResponse({'error': '缺少课程或文件'}, status=400)

    course = models.Course.objects.filter(id=course_id).first()
    if not course:
        return JsonResponse({'error': '课程不存在'}, status=404)

    result = parse_task_excel(upload_file, course)
    if 'error' in result:
        return JsonResponse({'error': result['error']}, status=400)

    request.session['pending_task_import'] = {
        'course_id': int(course_id),
        'tasks': result['tasks'],
    }
    return JsonResponse({
        'tasks': result['tasks'],
        'course_name': f'{course.courseTerm} / {course.courseName}（{course.classNumber}班）',
    })


@login_required
@require_POST
def confirm_task_import(request):
    """AJAX: 从 session 读取预览数据，写入数据库。"""
    if not request.user.is_superuser:
        return JsonResponse({'error': '仅管理员可执行此操作'}, status=403)

    pending = request.session.pop('pending_task_import', None)
    if not pending:
        return JsonResponse({'error': '没有待确认的导入数据，请重新上传'}, status=400)

    course = models.Course.objects.filter(id=pending['course_id']).first()
    if not course:
        return JsonResponse({'error': '课程不存在'}, status=404)

    try:
        result = write_task_import(pending['tasks'], course)
        return JsonResponse(result)
    except Exception as e:
        logger.exception("作业导入写入失败")
        return JsonResponse({'error': f'写入失败：{str(e)}'}, status=500)


def create_student_user():
    from app01.loaduser import load_user_list
    users = load_user_list()
    for u in users:
        user_obj = User.objects.create_user(username=u[0], password='szu' + u[0][-6:])
        models.UserProfile.objects.create(
            name=u[1], gender='M' if u[2] == '男' else 'F', user_id=user_obj.id
        )
