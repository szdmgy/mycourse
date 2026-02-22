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
from app01.upload_data import extract_import_data
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
            'name': forms.TextInput(attrs={'readonly': 'readonly'}),
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

    # 适配 HomeworkFile 模型：获取 slot1 的文件名
    filePath = 'False'
    homework = models.Homework.objects.filter(user=request.user.profile, task=task).first()
    if homework:
        hw_file = HomeworkFile.objects.filter(homework=homework, slot=1).first()
        if hw_file:
            filePath = os.path.basename(hw_file.filePath)

    context = {
        'name': get_display_name(request.user),
        'course': course,
        'task': task,
        'filePath': filePath,
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
        if homework:
            submitDate = homework.time
            delay = homework.time.date() > task.deadline
            if delay:
                submitDate = '逾期提交:' + homework.time.strftime("%Y年%m月%d日 %H:%M")
            taskRecords.append({
                'title': task.title, 'type': task.slot1Type,
                'time': submitDate, 'deadline': task.deadline,
                'delay': delay, 'id': task.id,
            })
        else:
            today = timezone.now().date()
            delay = today > task.deadline
            submitDate = '逾期未提交' if delay else ''
            taskRecords.append({
                'title': task.title, 'type': task.slot1Type,
                'time': submitDate, 'deadline': task.deadline,
                'delay': delay, 'id': task.id,
            })

    context = {
        'taskRecords': taskRecords,
        'name': get_display_name(request.user),
        'course': course,
    }
    return render(request, 'studentTaskList.html', context)


@login_required
def studentGetTaskByCoursename(request, courseTerm, courseName, classNumber):
    course = models.Course.objects.filter(
        courseTerm=courseTerm, courseName=courseName, classNumber=classNumber
    ).first()
    tasks = [t for t in models.Task.objects.filter(courseBelongTo=course) if t.display]

    judge_list = []
    for task in tasks:
        homework = models.Homework.objects.filter(user=request.user.profile, task=task).first()
        if homework:
            hw_file = HomeworkFile.objects.filter(homework=homework, slot=1).first()
            judge_list.append(os.path.basename(hw_file.filePath) if hw_file else 'False')
        else:
            judge_list.append('False')

    context = {
        'task': zip(tasks, judge_list),
        'name': get_display_name(request.user),
    }
    return render(request, 'studentTasks.html', context)


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
    suffix = file_obj.name.split('.')[-1]
    task_id = request.POST.get('taskId')
    task = models.Task.objects.get(id=task_id)
    title = safe_filename(task.title)

    task_dir = os.path.join(
        BASE_DIR, 'file', task.courseBelongTo.courseTerm,
        task.courseBelongTo.courseName + task.courseBelongTo.classNumber, title
    )
    os.makedirs(task_dir, exist_ok=True)

    file_name = f'{title}_{request.user.username}_{request.user.profile.name}_slot1_{task.slot1Name}.{suffix}'
    file_path = os.path.join(task_dir, file_name)

    # 创建或更新 Homework 记录
    homework, _ = models.Homework.objects.get_or_create(
        user=request.user.profile, task=task
    )
    # 创建或更新 HomeworkFile slot1
    hw_file, _ = HomeworkFile.objects.update_or_create(
        homework=homework, slot=1,
        defaults={'filePath': file_path, 'originalName': file_obj.name}
    )

    with open(file_path, 'wb') as f:
        f.write(file_obj.read())

    logger.info("文件上传: %s -> %s", request.user.username, file_name)
    return HttpResponse('YES')


@login_required
def download_file(request):
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


# ──────────────────────────── 教师端 ────────────────────────────

@login_required
def teacherGetTaskByCoursename(request, courseTerm, courseName, classNumber):
    course = models.Course.objects.filter(
        courseTerm=courseTerm, courseName=courseName, classNumber=classNumber
    ).first()
    selectCourseStudentList = course.members.filter(type='S')
    tasks = list(models.Task.objects.filter(courseBelongTo=course))

    studentList = []
    for task in tasks:
        submitStudentDict = {}
        notSubmitStudentList = []

        homeworkRecords = models.Homework.objects.filter(task=task)
        for record in homeworkRecords:
            if record.user.name not in submitStudentDict and record.user in selectCourseStudentList:
                submitStudentDict[record.user.name] = record.user

        for student in selectCourseStudentList:
            if student.name not in submitStudentDict:
                notSubmitStudentList.append(student)

        submitStudentList = list(submitStudentDict.values())
        studentList.append([submitStudentList, notSubmitStudentList])

    context = {
        'tasks': list(zip(tasks, studentList)),
        'courseMsg': [courseTerm, courseName, classNumber],
        'selectCourseStudentList': selectCourseStudentList,
        'name': get_display_name(request.user),
        'course': course,
    }
    return render(request, 'teacherTasks.html', context)


@login_required
def teacherCourseList(request):
    isManager = request.user.is_superuser
    if isManager:
        courses = models.Course.objects.all()
    else:
        courses = models.Course.objects.filter(members__user=request.user)

    courseList = [c for c in courses if c.status == 'Y']
    taskCountList = [models.Task.objects.filter(courseBelongTo=c).count() for c in courseList]

    context = {
        'course': zip(courseList, taskCountList) if courseList else None,
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

    filepathList = []
    for studentNumber in data["studentNumberList"]:
        homework = models.Homework.objects.filter(
            task=downloadTask, user__user__username=studentNumber
        ).last()
        if homework:
            hw_file = HomeworkFile.objects.filter(homework=homework, slot=1).first()
            if hw_file:
                filepathList.append(hw_file.filePath)

    if not filepathList:
        return HttpResponse("文件下载失败")

    # 单文件直接下载
    if len(filepathList) == 1:
        fileName = os.path.basename(filepathList[0])
        logger.info("下载文件: %s", fileName)
        response = StreamingHttpResponse(file_iterator(filepathList[0]))
        response['Content-Type'] = 'application/octet-stream'
        response['Content-Disposition'] = 'attachment;filename=' + fileName.encode('utf-8').decode('ISO-8859-1')
        return response

    # 多文件打包 ZIP（使用临时文件避免并发冲突）
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    try:
        with zipfile.ZipFile(tmp, mode="w", compression=zipfile.ZIP_STORED) as zf:
            for filepath in filepathList:
                basename = os.path.basename(filepath)
                parent = os.path.basename(os.path.dirname(filepath))
                zf.write(filepath, os.path.join(parent, basename))
        tmp.close()

        zipName = data.get("taskName", "download") + ".zip"
        response = StreamingHttpResponse(file_iterator(tmp.name))
        response['Content-Type'] = 'application/octet-stream'
        response['Content-Disposition'] = 'attachment;filename=' + zipName.encode('utf-8').decode('ISO-8859-1')
        return response
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


@login_required
@require_POST
def addHomework(request):
    # Bug fix: 允许教师和管理员添加作业
    if not is_teacher_or_admin(request.user):
        return HttpResponse("您没有权限添加作业！")

    homeworkTitle = request.POST.get('title', "")
    homeworkContent = request.POST.get('content', "请完成" + homeworkTitle)
    # Bug fix: 使用 courseID 而非 courseNumber+courseName
    courseID = request.POST.get('courseID', "")
    if not courseID:
        # 兼容旧模板：fallback 到 courseNumber+courseName
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
    # Bug fix: 标题查重范围限定为当前课程
    if models.Task.objects.filter(courseBelongTo=course, title=homeworkTitle).exists():
        return HttpResponse("作业标题已经存在")

    models.Task.objects.create(
        title=homeworkTitle, content=homeworkContent,
        courseBelongTo=course,
    )
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
    if not is_teacher_or_admin(request.user):
        return HttpResponse("您没有权限删除课程！")
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
        selectCourseStudentList = course.members.filter(type='S')

        records = []
        for task in tasks:
            for student in selectCourseStudentList:
                homework = models.Homework.objects.filter(task=task, user=student).first()
                if homework:
                    if homework.time.date() > task.deadline:
                        records.append({
                            'title': task.title, 'name': student.name,
                            'time': homework.time, 'deadline': task.deadline,
                            'status': '延期提交',
                        })
                else:
                    if timezone.now().date() > task.deadline:
                        records.append({
                            'title': task.title, 'name': student.name,
                            'time': '', 'deadline': task.deadline,
                            'status': '未提交',
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
        selectCourseStudentList = course.members.filter(type='S')
        homeworks = models.Homework.objects.filter(task=task)

        submitStudents = []
        submitRecords = []
        notSubmitStudents = []

        for hw in homeworks:
            if hw.user in selectCourseStudentList:
                submitStudents.append(hw.user)
                submitRecords.append([
                    hw.user.user.username, hw.user.name, hw.user.gender,
                    hw.time, hw.time.date() > task.deadline,
                ])

        for student in selectCourseStudentList:
            if student not in submitStudents:
                notSubmitStudents.append([student.user.username, student.name, student.gender])

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
        fields = ['display', 'deadline']
        widgets = {
            'deadline': forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {
            'display': '是否显示',
            'deadline': '截止日期',
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

    context = {
        'task': task,
        'name': get_display_name(request.user),
        'course': task.courseBelongTo,
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
    if not request.user.is_superuser:
        return HttpResponse("警告！您不是管理员！无法进入此界面！")

    if request.method == 'POST':
        upload_file = request.FILES.get('upload_file')
        file_format = request.POST.get('file_format')
        if not upload_file:
            return render(request, 'import.html', {'error': '请选择文件'})
        result = extract_import_data(upload_file, file_format)
        return render(request, 'import.html', result)

    return render(request, 'import.html')


@login_required
def teacher_course_change(request, courseTerm, courseName, classNumber):
    course = models.Course.objects.filter(
        courseTerm=courseTerm, courseName=courseName, classNumber=classNumber
    ).first()
    selectCourseStudentList = course.members.filter(type='S')
    tasks = list(models.Task.objects.filter(courseBelongTo=course))

    studentList = []
    for task in tasks:
        submitStudentDict = {}
        notSubmitStudentList = []

        homeworkRecords = models.Homework.objects.filter(task=task)
        for record in homeworkRecords:
            if record.user.name not in submitStudentDict and record.user in selectCourseStudentList:
                submitStudentDict[record.user.name] = record.user
        for student in selectCourseStudentList:
            if student.name not in submitStudentDict:
                notSubmitStudentList.append(student)
        submitStudentList = list(submitStudentDict.values())
        studentList.append([submitStudentList, notSubmitStudentList])

    context = {
        'tasks': list(zip(tasks, studentList)),
        'selectCourseStudentList': selectCourseStudentList,
        'name': get_display_name(request.user),
        'course': course,
    }
    return render(request, 'teacherCourseChange.html', context)


def create_student_user():
    from app01.loaduser import load_user_list
    users = load_user_list()
    for u in users:
        user_obj = User.objects.create_user(username=u[0], password='szu' + u[0][-6:])
        models.UserProfile.objects.create(
            name=u[1], gender='M' if u[2] == '男' else 'F', user_id=user_obj.id
        )
