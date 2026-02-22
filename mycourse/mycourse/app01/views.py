import datetime
from tempfile import NamedTemporaryFile

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import render, redirect
from django.http import HttpResponse, HttpResponseRedirect, StreamingHttpResponse, JsonResponse
from django.contrib.auth.models import User, Group

from django.views.decorators.csrf import csrf_exempt


from app01 import models
from app01.loaduser import load_user_list
import os
from mycourse.settings import BASE_DIR, FILES_ROOT
import json
import zipfile
from django import forms
from django.views.decorators.http import require_POST, require_http_methods
from app01.upload_data import extract_import_data
from .models import Task,UserProfile
from django.utils import timezone
from django.shortcuts import get_object_or_404
from datetime import datetime, date
# Create your views here.

def log_in(request):
    print('login')
    return render(request,'login.html')

def log_out(request):
    logout(request)
    return HttpResponseRedirect('/login/')

def user(request):
    if request.method == 'GET':
        return render(request, 'login.html')
    else:
        uname = request.POST.get("uname", "")
        pwd = request.POST.get("pwd", "")
        # print(uname,pwd)
        user = authenticate(request, username=uname, password=pwd)
        if user is not None:
            # 自带的登录功能
            login(request,user)

            # 取得数据库中的学生，这里的name是真实的姓名
            if models.UserProfile.objects.filter(user=user).count() == 0 and user.is_superuser:
                models.UserProfile.objects.create(user=user, name=user.username, gender='M', type='T')
            user = models.UserProfile.objects.filter(user=user)[0]
            # 暂时把数据库中的用户添加到session中，如果后期不用就删掉
            request.session['loginUserName'] = user.name
            # 如果是缺省密码则强制修改密码
            # print(request.user.profile.type,uname,pwd)
            if is_default_password(user.type, uname, pwd):
                request.session['password_change_error'] = '你现在使用的是缺省密码，为了你的帐户安全，请立即修改密码！'
                return redirect('change_password')
            # 跳转分支
            if user.type == u'T':
                return HttpResponseRedirect('/teacherCourseList/')
            else:
                return HttpResponseRedirect('/studentCourseList/')
                # return HttpResponse('登录成功')
            # login(request, user)
            # return redirect("/")
        else:
            return HttpResponse("账户或密码不正确！")

def is_default_password(type,name,password):
    if type == 'T':
        return ('szu'+name) == password
    else:
        return ('szu'+name[-6:]) == password


@login_required
def change_password(request):
    # 初始化提示信息（从 session 中获取并清除）
    success_msg = request.session.pop('password_change_success', None)
    error_msg = request.session.pop('password_change_error', None)

    if request.method == 'POST':
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()  # 更新密码
            update_session_auth_hash(request, form.user)  # 保持会话有效
            # 设置成功提示到 session（供下次请求显示）
            request.session['password_change_success'] = '密码修改成功！'
            return redirect('change_password')  # 重定向避免重复提交
        else:
            # 表单验证失败，保存错误信息到 session（可选）
            # 实际错误会通过 form.errors 直接传递到模板
            pass
    else:
        form = PasswordChangeForm(user=request.user)

    if request.user.profile.type == 'T':
        type = 'T'
        name = f'工号：{request.user.username} 姓名：{request.user.profile.name}'
    else:
        name = f'学号：{request.user.username} 姓名：{request.user.profile.name}'
        type = 'S'
    context = {
        'type': type,
        'name': name,
        'form': form,
        'success_msg': success_msg,
        'error_msg': error_msg,
    }
    return render(request, 'change_password.html', context)

class UserProfileEditForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['name','email', 'phone']  # 需要显示的所有字段
        widgets = {
            # 姓名字段使用只读文本输入框
            'name': forms.TextInput(attrs={'readonly': 'readonly'}),

        }
        labels = {
            'name': '姓名',

            'email': '邮箱',
            'phone': '手机号',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 确保只读字段的初始值正确显示
        self.fields['name'].initial = self.instance.name



@login_required
def profile_edit(request):
    # 获取当前用户的UserProfile实例（通过一对一关系）
    profile = request.user.profile
    ok = False
    if request.method == 'POST':
        form = UserProfileEditForm(request.POST, instance=profile)
        # print(form)
        if form.is_valid():
            # 仅保存可修改的字段（name会被忽略，因为是只读的）
            # 实际只需保存email和phone，但Django会自动处理
            form.save()
            # messages.success(request, '个人信息修改成功！')
            ok = True
            # return redirect('profile_detail')  # 跳转到详情页或提示成功

    else:
        form = UserProfileEditForm(instance=profile)

    if request.user.profile.type == 'T':
        name = f'工号：{request.user.username} 姓名：{request.user.profile.name}'
    else:
        name = f'学号：{request.user.username} 姓名：{request.user.profile.name}'
    context = {
        'name':name,
        'ok':ok,
        'form': form,
        'profile': profile,  # 用于显示只读的性别和类型
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


def taskSubmit(request,taskID,taskTitle):
    if request.user.profile.type != 'S':
        return HttpResponse("您不是学生，无法进行该操作！")
    name = f'学号：{request.user.username} 姓名：{request.user.profile.name}'
    task = get_object_or_404(Task, pk=taskID)
    course = task.courseBelongTo

    filePath = 'False'
    if models.Homework.objects.filter(user=request.user.profile, task=task):
        homework = models.Homework.objects.filter(user=request.user.profile, task=task).first()
        filePath = homework.filePath.split('\\')[-1]
    return render(request, 'studentSubmit.html', {'name':name,'course': course,'task':task,'filePath':filePath})


def studentCourse(request,courseTerm, courseName,classNumber):
    if request.user.username:
        student = request.user.profile
        course = models.Course.objects.filter(courseTerm=courseTerm, courseName=courseName, classNumber=classNumber)[0]
        # 这门课中的作业列表
        tasks = models.Task.objects.filter(courseBelongTo=course)
        tasks = [task for task in tasks if task.display]
        # 作业对应的提交、未提交人数 [[提交数,未提交数],[提交数,未提交数]...]
        taskRecords = []
        for task in tasks:
            id = task.id
            if models.Homework.objects.filter(task=task, user=student).count() > 0:
                homework = models.Homework.objects.filter(task=task, user=student).first()
                submitDate = homework.time
                delay = False
                # print(f'submitDate:{submitDate} deadline:{task.deadline}')
                if homework.time.date() > task.deadline:
                    delay = True
                    submitDate = '逾期提交:' + homework.time.strftime("%Y年%m月%d日 %H:%M")

                taskRecords.append({'title':task.title,'type':task.uploadFileType,'time':submitDate,'deadline':task.deadline,'delay':delay,'id':id})
            else:
                today = timezone.now().date()
                delay = False
                submitDate = ''
                if today > task.deadline:
                    delay = True
                    submitDate = '逾期未提交'
                taskRecords.append(
                    {'title': task.title, 'type': task.uploadFileType, 'time': submitDate, 'deadline': task.deadline,
                     'delay': delay,'id':id})

        name = f'学号：{request.user.username} 姓名：{request.user.profile.name}'

        return render(request, 'studentTaskList.html', {'taskRecords': taskRecords,'name': name,'course':course})
    else:
        return HttpResponseRedirect('/login/')
# 学生端：通过课程的号码和名字找到对应的作业列表
def studentGetTaskByCoursename(request,courseTerm, courseName,classNumber):
    if request.user.username:
        course = models.Course.objects.filter(courseTerm=courseTerm, courseName=courseName,classNumber=classNumber)[0]
        tasks = models.Task.objects.filter(courseBelongTo=course)
        tasks = [task for task in tasks if task.display == True]
        judge_list = []
        for task in tasks:
            if models.Homework.objects.filter(user = request.user.profile, task = task):
                homework = models.Homework.objects.filter(user=request.user.profile, task=task).first()
                homework_name = homework.filePath.split('\\')[-1]
                judge_list.append(homework_name)
            else:
                judge_list.append('False')
        tasks = zip(tasks, judge_list)
        name = f'学号：{request.user.username} 姓名：{request.user.profile.name}'
        return render(request, 'studentTasks.html', {'task': tasks,'name':name})
    else:
        return HttpResponseRedirect('/login/')

# 老师端：作业/任务界面
def teacherGetTaskByCoursename(request,courseTerm, courseName,classNumber):
    if request.user.username:
        course = models.Course.objects.filter(courseTerm=courseTerm, courseName=courseName,classNumber=classNumber)[0]
        # 选了这门课的学生数量
        selectCourseStudentList = course.members.filter(type=u'S')
        # print(len(selectCourseStudentList))
        # for each in selectCourseStudentList:
        #     print(each)
        # 这门课中的作业列表
        tasks = models.Task.objects.filter(courseBelongTo=course)
        tasks = [task for task in tasks]
        # 作业对应的提交、未提交人数 [[提交数,未提交数],[提交数,未提交数]...]
        studentList = []
        for task in tasks:
            submitStudentDict = {}
            notSubmitStudentList = []

            # 属于这个作业的提交记录
            homeworkRecords = models.Homework.objects.filter(task=task)
            # 找出作业记录中的学生：查看谁已经提交了此次作业
            for homeworkRecord in homeworkRecords:
                if submitStudentDict.get(homeworkRecord.user.name, None) == None:
                    # {"唐" : UserProfile对象}
                    if homeworkRecord.user in selectCourseStudentList:
                        submitStudentDict[homeworkRecord.user.name] = homeworkRecord.user
            # 找出选了这个课的学生，再去掉已经提交作业的，剩下的就是没交作业的
            for selectedStudent in selectCourseStudentList:
                if submitStudentDict.get(selectedStudent.name, None) == None:
                    notSubmitStudentList.append(selectedStudent)
            submitStudentList = [submitStudent for submitStudent in submitStudentDict.values()]
            studentList.append([submitStudentList, notSubmitStudentList])

        tasks = list(zip(tasks, studentList))
        name = f'工号：{request.user.username} 姓名：{request.user.profile.name}'
        # tasks -->  [(task1, studentList1), (task2, studentList2), ...]
        # studentList --> [[提交用户列表,未提交用户列表],[提交用户列表,未提交用户列表]...]
        return render(request, 'teacherTasks.html', {'tasks': tasks, 'courseMsg':[courseTerm, courseName,classNumber],
               'selectCourseStudentList':selectCourseStudentList,'name':name,'course':course})
        # return render(request, 'teacherTasks.html', {'tasks': tasks, 'course':course,'selectCourseStudentList': selectCourseStudentList, 'name': name})
    else:
        return HttpResponseRedirect('/login/')

# 学生端：根据用户登录的名字筛选出ta所选的课程，传到前端
def studentCourseList(request):
    if request.user.username:
        courses = models.Course.objects.filter(members__user=request.user)
        taskCountList = [models.Task.objects.filter(courseBelongTo=course).count() for course in courses if course.status == u'Y']

        courseList = [course for course in courses if course.status == u'Y']
        if len(courseList) > 0:
            course = zip(courseList, taskCountList)
        else:
            course = None
        name = f'学号：{request.user.username} 姓名：{request.user.profile.name}'
        return render(request, 'studentCourseList.html', {'course': course,'name':name})

    else:
        return HttpResponseRedirect('/login/')

# 老师端：课程界面
def teacherCourseList(request):
    # 根据用户登录的名字筛选出ta所选的课程，传到前端
    if request.user.username:
        isManager = True if request.user.is_superuser else False
        if isManager:
            courses = models.Course.objects.all()
        else:
            courses = models.Course.objects.filter(members__user=request.user)
        taskCountList = [models.Task.objects.filter(courseBelongTo=course).count() for course in courses if course.status == u'Y']



        courseList = [course for course in courses if course.status == u'Y']
        if len(courseList) > 0:
            course = zip(courseList, taskCountList)
        else:
            course = None

        name = f'工号：{request.user.username} 姓名：{request.user.profile.name}'

        return render(request, 'teacherCourseList.html', {'course': course, 'isManager':isManager,'name':name})

    else:
        return HttpResponseRedirect('/login/')

# 学生端上传作业
def post_file(request):
    if request.FILES.get('file', '') != '':
        file_obj = request.FILES.get('file')
        suffix = file_obj.name.split('.')[-1]
        task_id = request.POST.get('taskId')
        file_dir = os.path.join(BASE_DIR, 'file')
        task = models.Task.objects.get(id=task_id)
        title = task.title.replace('、', '_')
        # task_dir = os.path.join(file_dir, task.courseBelongTo.courseNumber+task.courseBelongTo.courseName)
        task_dir = os.path.join(file_dir, task.courseBelongTo.courseTerm)
        task_dir = os.path.join(task_dir, task.courseBelongTo.courseName+task.courseBelongTo.classNumber)
        task_dir = os.path.join(task_dir, title)
        if not os.path.exists(task_dir):
            os.makedirs(task_dir)
        # file_name = title + '_' + request.user.profile.name + '_' + request.user.username + '.' + suffix
        file_name = title + '_' + request.user.username + '_' + request.user.profile.name + '.' + suffix
        print(file_name)
        file_path = os.path.join(task_dir, file_name)
        if not models.Homework.objects.filter(user = request.user.profile, task = task):
            models.Homework.objects.create(user=request.user.profile, task=task, filePath=file_path)
        else:
            tempHomeworkRecord = models.Homework.objects.filter(user=request.user.profile, task=task).first()
            tempHomeworkRecord.filePath = file_path
            tempHomeworkRecord.save()
        with open(file_path, 'wb') as f:
            f.write(file_obj.read())
        return HttpResponse('YES')

# 学生端下载作业
def download_file(request):
    if request.GET.get('url', '') != '':
        filename = request.GET["url"]
        taskid = request.GET["task"]
        task = models.Task.objects.filter(id=taskid)[0]
        tasktitleReplace = task.title.replace('、', '_')
        filename = filename.replace('、', '_')
        course = task.courseBelongTo
        file = os.path.join(BASE_DIR, 'file', course.courseTerm,course.courseName+course.classNumber, tasktitleReplace, filename)

        def file_iterator(file_name, chunk_size=512):
            with open(file_name, 'rb') as f:
                while True:
                    c = f.read(chunk_size)
                    if c:
                        yield c
                    else:
                        break

        response = StreamingHttpResponse(file_iterator(file))
        response['Content-Type'] = 'application/octet-stream'
        response['Content-Disposition'] = 'attachment;filename=' + filename.encode('utf-8').decode('ISO-8859-1')
        return response
    return HttpResponse('error')

# 老师下载作业
@require_POST
def teacherDownloadByHomeworknameAndStudentnumber(request):
    # json字符串
    studentNumber_taskName_JSON = request.body.decode("utf-8")
    # 转换为字典
    studentNumber_taskName_JSON = json.loads(studentNumber_taskName_JSON)
    # print(studentNumber_taskName_JSON)

    taskId = studentNumber_taskName_JSON["taskId"]
    downloadTask = models.Task.objects.filter(id=int(taskId)).first()
    filepathList = []
    for studentNumber in studentNumber_taskName_JSON["studentNumberList"]:
        filepathList.append(models.Homework.objects.filter(task=downloadTask, user__user__username=studentNumber).last().filePath)

    # 把文件转换成输出流
    def file_iterator(file_name, chunk_size=512):
        with open(file_name, 'rb') as f:
            while True:
                c = f.read(chunk_size)
                if c:
                    yield c
                else:
                    break
    # 只有一个文件时直接传输
    if len(filepathList) == 1:
        fileName = filepathList[0].split('\\')[-1]
        print("正在传输：" + fileName)
        response = StreamingHttpResponse(file_iterator(filepathList[0]))
        response['Content-Type'] = 'application/octet-stream'
        response['Content-Disposition'] = 'attachment;filename=' + fileName.encode('utf-8').decode('ISO-8859-1')
        return response
    # 多个文件时打包成zip文件
    if len(filepathList) > 1:
        if not os.path.exists("./file/temp/"):
            os.makedirs("./file/temp/")
        # 打包
        tempFile = zipfile.ZipFile("./file/temp/temp.zip", mode="w", compression=zipfile.ZIP_STORED, allowZip64=False)

        for filepath in filepathList:
            tempFile.write(filepath, filepath.split("\\")[-2] + "\\" + filepath.split("\\")[-1])
        tempFile.close()
        fileName = studentNumber_taskName_JSON["taskName"] + ".zip"
        response = StreamingHttpResponse(file_iterator("./file/temp/temp.zip"))
        response['Content-Type'] = 'application/octet-stream'
        response['Content-Disposition'] = 'attachment;filename=' + fileName.encode('utf-8').decode('ISO-8859-1')
        return response

    # response = StreamingHttpResponse(file_iterator())
    # response['Content-Type'] = 'application/octet-stream'
    # response['Content-Disposition'] = 'attachment;filename=' + filename.encode('utf-8').decode('ISO-8859-1')
    return HttpResponse("文件下载失败")

# 老师添加作业/任务
@require_POST
def addHomework(request):
    if request.user.profile.type != 'T':
        return HttpResponse("您不是老师，无法添加！")

    homewordTitle = request.POST.get('title', "")
    homewordContent = request.POST.get('content', "请完成" + homewordTitle)
    uploadFileType = request.POST.get('uploadFileType', "*").replace('，', ',').replace('。','.').replace(';',',')
    courseNumber = request.POST.get('courseNumber', "")
    courseName = request.POST.get('courseName', "")
    if courseName == "" or courseNumber == "":
        return HttpResponse("任务失败")

    if homewordTitle == "":
        return HttpResponse("作业标题不能为空")
    if models.Task.objects.filter(title=homewordTitle).count() != 0:
        return HttpResponse("作业标题已经存在")

    course = models.Course.objects.filter(courseNumber=courseNumber, courseName=courseName).first()
    models.Task.objects.create(title=homewordTitle, content=homewordContent, uploadFileType=uploadFileType, courseBelongTo=course)

    return HttpResponseRedirect(request.headers.get("Referer"))


# 老师用户添加课程
@require_POST
def addCourse(request):
    if request.user.profile.type != 'T':
        return HttpResponse("您不是老师，无法添加！")

    courseName = request.POST.get('courseName', "")
    courseNumber = request.POST.get('courseNumber', "")
    studentList = request.POST.get('studentList', "")
    print("课程名：" + courseName + "课程编号：" + courseNumber)
    print("学生名单" + studentList)

    if courseName == "" or courseNumber == "" or studentList == "":
        return HttpResponse("课程信息有错误，请重新填写")
    if models.Course.objects.filter(courseName=courseName, courseNumber=courseNumber).count() != 0:
        return HttpResponse("该课程已经存在！无法添加")
    studentList = [student for student in studentList.split(';')]
    if studentList[-1] == "":
        studentList = studentList[0:-1]

    #创建不存在的学生
    for studentStr in studentList:
        if models.User.objects.filter(username=studentStr.split(',')[0]).count() == 0:
            models.User.objects.create_user(username=studentStr.split(',')[0], password="szu" + studentStr.split(',')[0][4:])
            models.UserProfile.objects.create(name=studentStr.split(',')[1], user=models.User.objects.filter(username=studentStr.split(',')[0]).first(), type='S', gender='M' if studentStr.split(',')[2] == '男' else 'F')
    #创建课程
    models.Course.objects.create(courseName=courseName, courseNumber=courseNumber)
    # 获得刚创建的课程
    course = models.Course.objects.filter(courseName=courseName, courseNumber=courseNumber).first()
    # 添加学生
    for studentStr in studentList:
        course.members.add(models.UserProfile.objects.filter(user__username=studentStr.split(',')[0]).first())
    # 添加老师
    course.members.add(models.UserProfile.objects.filter(user=request.user).first())

    return HttpResponseRedirect(request.headers.get("Referer"))

# 老师用户删除课程
def deleteCourse(request, courseNumber, courseName):
    if request.user.profile.type != 'T':
        return HttpResponse("您不是老师，无法添加！")
    course = models.Course.objects.filter(courseName=courseName, courseNumber=courseNumber)[0]
    course.delete()
    return HttpResponseRedirect('/teacherCourseList/')

# 进入管理员界面
def manager(request):
    if not request.user.is_superuser:
        return HttpResponse("警告！您不是管理员！无法进入此界面！")

    # teacher = models.UserProfile.objects.filter(type='T')
    # student = models.UserProfile.objects.filter(type='S')
    name = f'工号：{request.user.username} 姓名：{request.user.profile.name}'

    return render(request, 'manager.html', {'name':name})
# 进入管理员界面
def user_list(request):
    if not request.user.is_superuser:
        return HttpResponse("警告！您不是管理员！无法进入此界面！")

    teacherList = models.UserProfile.objects.filter(type='T')
    studentList = models.UserProfile.objects.filter(type='S')
    name = f'工号：{request.user.username} 姓名：{request.user.profile.name}'

    return render(request, 'userList.html', {'teacherList':teacherList, 'studentList':studentList,'name':name})

def remove_user(request,username):
    if not request.user.is_superuser:
        return HttpResponse("警告！您不是管理员！无法进入此界面！")
    print("正在删除用户：" + username)
    if models.User.objects.filter(username=username).count() == 0 or models.UserProfile.objects.filter(
            user__username=username).count() == 0:
        return HttpResponse("该用户不存在，无法删除")
    if models.User.objects.filter(username=username).first().is_superuser:
        return HttpResponse("无法删除管理员！")

    models.User.objects.filter(username=username).delete()

    return HttpResponseRedirect(request.headers.get('Referer'))
# 管理员添加成员
@require_POST
def addMemberByManager(request):
    if not request.user.is_superuser:
        return HttpResponse("您不是管理员，无法添加！")

    memberType = request.POST.get('memberType', '')
    memberName = request.POST.get('memberName', '')
    memberNumber = request.POST.get('memberNumber', '')
    memberGender = request.POST.get('memberGender', '')
    memberPassword = "szu" + memberNumber if memberType == 'teacher' else "szu" + memberNumber[4:]
    print(memberPassword)
    if memberType == "" or memberName == "" or memberNumber == "" or memberGender == "" or memberPassword == "":
        return HttpResponse("成员信息缺失！请重新添加！")
    if models.User.objects.filter(username=memberNumber).count() != 0:
        return HttpResponse("该成员已存在！无法添加！")

    models.User.objects.create_user(username=memberNumber, password=memberPassword)
    member = models.User.objects.filter(username=memberNumber).first()
    models.UserProfile.objects.create(name=memberName, type='T' if memberType == 'teacher' else 'S', gender='M' if memberGender == 'male' else 'F', user=member)



    return HttpResponseRedirect(request.headers.get("Referer"))

# 管理员删除用户
def deleteMemberByManager(request, memberNumber):
    if not request.user.is_superuser:
        return HttpResponse("您不是管理员，无法删除！")
    print("正在删除用户：" + memberNumber)
    if models.User.objects.filter(username=memberNumber).count() == 0 or models.UserProfile.objects.filter(user__username=memberNumber).count() == 0:
        return HttpResponse("该用户不存在，无法删除")
    if models.User.objects.filter(username=memberNumber).first().is_superuser:
        return HttpResponse("无法删除管理员！")

    models.User.objects.filter(username=memberNumber).delete()

    return HttpResponseRedirect(request.headers.get('Referer'))

# 老师端：更新课程信息
@require_POST
def changeCourseMsgByTeacher(request):
    if request.user.profile.type != 'T':
        return HttpResponse("您不是老师，无法修改课程信息！")

    if request.POST.get("changedCourseName", None) == None or request.POST.get("changedCourseName", None) == None:
        return HttpResponseRedirect(request.headers.get('Referer'))

    courseNumber = request.POST.get("courseNumber")
    courseName = request.POST.get("courseName")
    changedCourseName = request.POST.get("changedCourseName")
    changedCourseNumber = request.POST.get("changedCourseNumber")

    if models.Course.objects.filter(courseNumber=courseNumber, courseName=courseName).count() == 0:
        return HttpResponse("该课程不存在！请重试！")
    course = models.Course.objects.filter(courseNumber=courseNumber, courseName=courseName).first()
    course.courseName = changedCourseName
    course.courseNumber = changedCourseNumber
    course.status = u'Y'
    course.save()

    return HttpResponseRedirect('/teacherCourseList/')

# 老师端：删除作业/任务
def deleteTaskByTeacher(request, taskId):
    if request.user.profile.type != 'T':
        return HttpResponse("您不是老师，无法删除该作业！")
    if models.Task.objects.filter(id = taskId).count() == 0:
        return HttpResponse("该作业不存在！无法删除该作业！")
    task = models.Task.objects.filter(id = taskId).first()
    for homework in models.Homework.objects.filter(task=task):
        homework.delete()
    task.delete()
    return HttpResponseRedirect(request.headers.get('Referer'))

# 老师端：从课程中移除学生
def removeStudentFromCourse(request, courseNumber, courseName, studentNumber):
    if request.user.profile.type != 'T':
        return HttpResponse("您不是老师，无法进行该操作！")

    if models.Course.objects.filter(courseNumber=courseNumber, courseName=courseName).count() == 0 or models.User.objects.filter(username=studentNumber).count() == 0:
        return HttpResponse("此课程或此学生不存在！")
    course = models.Course.objects.filter(courseNumber=courseNumber, courseName=courseName).first()
    student = models.UserProfile.objects.filter(user__username=studentNumber).first()
    course.members.remove(student)

    return HttpResponseRedirect(request.headers.get('Referer'))

def delayRecords(request,courseID):
    if request.user.profile.type != 'T':
        return HttpResponse("您不是老师，无法进行该操作！")
    try:
        course = models.Course.objects.filter(id=courseID).first()
        tasks = models.Task.objects.filter(courseBelongTo=course)
        tasks = [task for task in tasks]
        records = []
        # 选了这门课的学生数量
        selectCourseStudentList = course.members.filter(type=u'S')
        print('hello world')
        for task in tasks:
            for student in selectCourseStudentList:
                if models.Homework.objects.filter(task= task,user=student).count() > 0:
                    homework = models.Homework.objects.filter(task= task,user=student).first()
                    submitDate = homework.time.date()
                    if submitDate > task.deadline:
                        records.append({'title': task.title, 'name': student.name, 'time': homework.time, 'deadline': task.deadline,'status': '延期提交'})
                else:
                    today = timezone.now().date()
                    if today > task.deadline:
                        records.append({'title':task.title,'name':student.name,'time':'','deadline':task.deadline,'status':'未提交'})

        name = f'工号：{request.user.username} 姓名：{request.user.profile.name}'
        return render(request, 'delayRecords.html', {'name':name,'course':course,'records':records})
    except Exception as e:
        return HttpResponse(str(e))

def homeworkRecords(request,taskID,taskTitle):
    if request.user.profile.type != 'T':
        return HttpResponse("您不是老师，无法进行该操作！")
    try:
        task = Task.objects.get(id=taskID)
        course = task.courseBelongTo
        # 选了这门课的学生数量
        selectCourseStudentList = course.members.filter(type=u'S')
        # 属于这个作业的提交记录
        homeworkRecords = models.Homework.objects.filter(task=task)

        submitUtudents = []
        submitRecords = []
        notSubmitStudents = []
        # 找出作业记录中的学生：查看谁已经提交了此次作业
        for homeworkRecord in homeworkRecords:
            if homeworkRecord.user in selectCourseStudentList:
                submitUtudents.append(homeworkRecord.user)
                submitDate = homeworkRecord.time.date()
                submitRecords.append([homeworkRecord.user.user.username,homeworkRecord.user.name,
                   homeworkRecord.user.gender,homeworkRecord.time,submitDate > task.deadline])

        # 找出选了这个课的学生，再去掉已经提交作业的，剩下的就是没交作业的
        for selectedStudent in selectCourseStudentList:
            if selectedStudent not in submitUtudents:
                notSubmitStudents.append([selectedStudent.user.username,selectedStudent.name,selectedStudent.gender])

        name = f'工号：{request.user.username} 姓名：{request.user.profile.name}'
        return render(request, 'homeworkRecords.html', {'name':name,'course':course,'task':task,'submitRecords':submitRecords,'notSubmitStudents':notSubmitStudents})
    except Task.DoesNotExist:
        return HttpResponse(f'{taskTitle}不存在')  # 或返回错误页面





def resetPassword(request):
    try:
        print('hello')
        name = request.POST.get('user')
        print(name)
        profile = models.UserProfile.objects.filter(user__username=name).first()
        user = profile.user
        if profile.type == 'T':
            user.set_password('szu' + name)
        else:
            user.set_password('szu' + name[-6:])
        user.save()
        return HttpResponse(f'学号：{name}的用户密码重置成功！')
    except Exception as e:
        print(e)
        return HttpResponse(str(e))

# 定义表单类（仅包含可修改字段，上传类型不参与提交）
class TaskEditForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['display', 'deadline']  # 仅允许修改 display 和 deadline
        widgets = {
            'deadline': forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {
            'display': '是否显示',
            'deadline': '截止日期',
        }
def taskChange(request,taskID,taskTitle):
    if request.user.profile.type != 'T':
        return HttpResponse("您不是老师，无法进行该操作！")
        # 获取要编辑的作业实例（若不存在则返回 404）
    try:
        task = Task.objects.get(id=taskID)
    except Task.DoesNotExist:
        return HttpResponse(f'{taskTitle}不存在') # 或返回错误页面

    name = f'工号：{request.user.username} 姓名：{request.user.profile.name}'
    if request.method == 'POST':
        # 绑定实例以更新数据（仅修改 display 和 deadline）
        form = TaskEditForm(request.POST, instance=task)
        if form.is_valid():
            print('is_valid')
            form.save()  # 保存修改
            course = task.courseBelongTo
            return redirect('teacherCourseChange',course.courseTerm,course.courseName,course.classNumber)  # 跳转到作业详情页
    else:
        # 初始化表单（显示当前值）
        form = TaskEditForm(instance=task)

    context = {
        'task': task,'name':name,'course':task.courseBelongTo  # 传递任务实例到模板，用于显示上传类型等只读字段
    }
    return render(request, 'taskChange.html', context)
    # return HttpResponse(f'taskID:{taskID} taskTitle:{taskTitle}')
# 老师端：从课程中移除学生
def removeStudent(request, courseID, studentNumber):
    if request.user.profile.type != 'T':
        return HttpResponse("您不是老师，无法进行该操作！")

    if models.Course.objects.filter(id=courseID).count() == 0 or models.User.objects.filter(username=studentNumber).count() == 0:
        return HttpResponse("此课程或此学生不存在！")
    course = models.Course.objects.filter(id=courseID).first()
    student = models.UserProfile.objects.filter(user__username=studentNumber).first()
    course.members.remove(student)

    return HttpResponseRedirect(request.headers.get('Referer'))
# 老师端：为某个课程添加单个学生
@require_POST
def addStudentToCourseByTeacher(request):
    if request.user.profile.type != 'T':
        return HttpResponse("您不是老师，无法修改课程信息！")

    studentName = request.POST.get("newStudentName", "")
    studentNumber = request.POST.get("newStudentNumber", "")
    studentGender = request.POST.get("newStudentGender", "")
    courseID = request.POST.get("courseID", "")

    if studentName == "" or studentNumber == "" or studentGender == "" :
        return HttpResponse("填入的参数有误，请重试！")
    if models.Course.objects.filter(id=courseID).count() == 0:
        return HttpResponse("该课程不存在，请重试")
    course = models.Course.objects.filter(id=int(courseID)).first()
    if models.UserProfile.objects.filter(user__username=studentNumber).count() != 0:
        student = models.UserProfile.objects.filter(user__username=studentNumber).first()
    else:
        user = models.User.objects.create_user(username=studentNumber, password="szu" + studentNumber[4:])
        student = models.UserProfile.objects.create(user=user, name=studentName, gender=studentGender, type='S')
    course.members.add(student)
    return HttpResponseRedirect(request.headers.get('Referer'))

def downloadStudentListTemplate(request):
    if request.user.profile.type != 'T':
        return HttpResponse("您不是老师，无法下载！")

    # 把文件转换成输出流
    def file_iterator(file_name, chunk_size=512):
        with open(file_name, 'rb') as f:
            while True:
                c = f.read(chunk_size)
                if c:
                    yield c
                else:
                    break

    # 只有一个文件时直接传输

    fileName = os.path.join(FILES_ROOT, 'student_list_template.xlsx')
    print("正在传输：" + fileName)
    response = StreamingHttpResponse(file_iterator(fileName))
    response['Content-Type'] = 'application/octet-stream'
    response['Content-Disposition'] = 'attachment;filename=' + fileName.encode('utf-8').decode('ISO-8859-1')
    return response


def create_student_user():
    users = load_user_list()
    for user in users:
        user_obj = User.objects.create_user(username=user[0], password='szu'+user[0][-6:])
        if user[2] == '男':
            sex = u'M'
        else:
            sex = u'F'
        models.UserProfile.objects.create(name=user[1], gender=sex, user_id=user_obj.id)


def file_upload_course(request):
    # return HttpResponse("您不是老师，无法进行该操作！")
    if request.user.profile.type != 'T':
        return HttpResponse("您不是老师，无法进行该操作！")
        # 获取要编辑的作业实例（若不存在则返回 404）
    if request.method == 'POST':
        print('file_upload_course post')
        return HttpResponse('file_upload_course post')

    allowed_extensions = ".xls,.xlsx,.xlsm"
    name = f'工号：{request.user.username} 姓名：{request.user.profile.name}'
    datatype = 'course'
    upload_route = '/upload-files/course/'
    print(name)


    context = {
        'upload_route':upload_route,
        'datatype':datatype,
        'name': name,
        'allowed_extensions': allowed_extensions
    }
    return render(request, 'upload_files.html', context)

def file_upload_view(request,type):
    """
    渲染文件上传页面，动态设置允许的文件类型

    通过此视图，前端可以动态获取当前会话允许上传的文件类型
    """
    # 可以根据业务逻辑动态设置允许的文件类型
    # 示例：当前只允许Word文档
    # allowed_extensions = ".doc,.docx,.rtf"

    # 或者根据需要设置其他类型
    allowed_extensions = ".xls,.xlsx,.xlsm"
    # allowed_extensions = ".pdf,.docx,.xlsx"
    # allowed_extensions = ".jpg,.jpeg,.png,.gif"
    # 将配置信息存入会话
    # request.session['allowed_extensions'] = ','.join(allowed_extensions)

    name = f'工号：{request.user.username} 姓名：{request.user.profile.name}'
    upload_files = {
        'course':'上传课程文件(excel文件)',
        'task': '上传作业文件(excel文件)',
        'teacher': '上传老师文件(excel文件)',
        'student': '上传学生文件(excel文件)',
        'user': '上传用户文件(excel文件)'

    }
    file_text = '未知数据类型，路由错误，请更新路由后重新访问'
    if type in upload_files:
        file_text = upload_files[type]
    context = {
        'name':name,
        'datatype':type,
        'file_text':file_text,
        'allowed_extensions': allowed_extensions
    }
    return render(request, 'upload_files.html', context)


@csrf_exempt
@require_http_methods(["POST"])
def process_files(request):
    """
    处理文件上传请求

    验证文件类型是否符合当前会话设置，并处理上传的文件
    """
    try:
        # 获取所有上传的文件
        files = []
        file_index = 0
        datatype = request.POST.get('datatype', '未知')
        while f'file_{file_index}' in request.FILES:
            files.append(request.FILES[f'file_{file_index}'])
            file_index += 1

        if not files:
            return JsonResponse({
                'success': False,
                'error': '未收到任何文件',
                'file_count': 0
            }, status=400)

        results = []
        file_count = len(files)

        # 处理每个文件
        for uploaded_file in files:
            filename = uploaded_file.name
            file_ext = os.path.splitext(filename)[1].lower()

            result = extract_import_data(uploaded_file, datatype)
            # 这里放置实际的文件处理逻辑
            # 示例：保存到本地
            # if settings.DEBUG and settings.MEDIA_ROOT:
            #     save_path = os.path.join(settings.MEDIA_ROOT, filename)
            #     with open(save_path, 'wb+') as destination:
            #         for chunk in uploaded_file.chunks():
            #             destination.write(chunk)
            if 'success' in result:
                status = result['success']
            else:
                status = result['error']
            results.append({
                'filename': filename,
                'status': status
            })

        return JsonResponse({
            'success': True,
            'file_count': file_count,
            'results': results,

        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'处理失败: {str(e)}'
        }, status=500)

    # try:
    #     # 获取文件列表
    #     files = []
    #     file_index = 0
    #     datatype = request.POST.get('datatype', '未知')
    #     print(datatype)
    #     while f'file_{file_index}' in request.FILES:
    #         files.append(request.FILES[f'file_{file_index}'])
    #         file_index += 1
    #
    #     if not files:
    #         return JsonResponse({
    #             'success': False,
    #             'error': '未收到任何文件',
    #             'file_count': 0
    #         })
    #
    #     # 获取当前会话允许的文件类型
    #     # allowed_extensions = request.session.get('allowed_extensions', '').split(',')
    #
    #     # 处理结果列表
    #     results = []
    #     processed_count = 0
    #
    #     for uploaded_file in files:
    #         file_result = {
    #             'filename': uploaded_file.name,
    #             'error': None,
    #             'sheets': []
    #         }
    #
    #         # 验证文件类型
    #         file_ext = os.path.splitext(uploaded_file.name)[1].lower()
    #         # print(file_ext,allowed_extensions)
    #         # if allowed_extensions and file_ext not in allowed_extensions:
    #         #     file_result['error'] = f'不支持的文件类型: {file_ext}'
    #         #     results.append(file_result)
    #         #     continue
    #
    #         # 处理不同类型的文件
    #         try:
    #             # 对于文档文件
    #             if file_ext in ['.doc', '.docx', '.rtf']:
    #                 # Word文档处理逻辑
    #                 file_result['sheets'].append({
    #                     'name': '文档内容',
    #                     'row_count': 0  # 示例值
    #                 })
    #
    #             # 对于电子表格文件
    #             elif file_ext in ['.xls', '.xlsx', '.xlsm']:
    #                 # Excel表格处理逻辑
    #                 file_result['sheets'].append({
    #                     'name': '表1',
    #                     'row_count': 0  # 示例值
    #                 })
    #
    #             # 其他文件类型
    #             else:
    #                 file_result['sheets'].append({
    #                     'name': '文件内容',
    #                     'row_count': 0
    #                 })
    #
    #             processed_count += 1
    #             results.append(file_result)
    #
    #         except Exception as e:
    #             file_result['error'] = f'处理文件时出错: {str(e)}'
    #             results.append(file_result)
    #
    #     return JsonResponse({
    #         'success': True,
    #         'file_count': len(files),
    #         'processed_files': processed_count,
    #         'results': results
    #     })
    #
    # except Exception as e:
    #     return JsonResponse({
    #         'success': False,
    #         'error': f'服务器错误: {str(e)}',
    #         'file_count': len(files) if 'files' in locals() else 0,
    #         'processed_files': processed_count if 'processed_count' in locals() else 0
    #     })


def import_data(request):
    if not request.user.is_superuser:
        return HttpResponse("警告！您不是管理员！无法进入此界面！")

    if request.method == 'POST':
        upload_file = request.FILES.get('upload_file')
        file_format = request.POST.get('file_format')
        # print(file_format)

        # 验证文件是否存在
        if not upload_file:
            return render(request, 'import.html', {'error': '请选择文件'})

        result = extract_import_data(upload_file,file_format)
        return render(request,'import.html',result)

    return render(request, 'import.html')



def teacher_course_change(request,courseTerm, courseName,classNumber):
    if request.user.username:
        course = models.Course.objects.filter(courseTerm=courseTerm, courseName=courseName, classNumber=classNumber)[0]
        # 选了这门课的学生数量
        selectCourseStudentList = course.members.filter(type=u'S')
        # 这门课中的作业列表
        tasks = models.Task.objects.filter(courseBelongTo=course)
        tasks = [task for task in tasks]
        # 作业对应的提交、未提交人数 [[提交数,未提交数],[提交数,未提交数]...]
        studentList = []
        for task in tasks:
            # print(task)
            submitStudentDict = {}
            notSubmitStudentList = []

            # 属于这个作业的提交记录
            homeworkRecords = models.Homework.objects.filter(task=task)
            # 找出作业记录中的学生：查看谁已经提交了此次作业
            for homeworkRecord in homeworkRecords:
                if submitStudentDict.get(homeworkRecord.user.name, None) == None:
                    # {"唐" : UserProfile对象}
                    if homeworkRecord.user in selectCourseStudentList:
                        submitStudentDict[homeworkRecord.user.name] = homeworkRecord.user
            # 找出选了这个课的学生，再去掉已经提交作业的，剩下的就是没交作业的
            for selectedStudent in selectCourseStudentList:
                if submitStudentDict.get(selectedStudent.name, None) == None:
                    notSubmitStudentList.append(selectedStudent)
            submitStudentList = [submitStudent for submitStudent in submitStudentDict.values()]
            studentList.append([submitStudentList, notSubmitStudentList])

        tasks = list(zip(tasks, studentList))
        name = f'工号：{request.user.username} 姓名：{request.user.profile.name}'
        # tasks -->  [(task1, studentList1), (task2, studentList2), ...]
        # studentList --> [[提交用户列表,未提交用户列表],[提交用户列表,未提交用户列表]...]
        return render(request, 'teacherCourseChange.html', {'tasks': tasks,
                'selectCourseStudentList': selectCourseStudentList, 'name': name,'course':course})
    else:
        return HttpResponseRedirect('/login/')