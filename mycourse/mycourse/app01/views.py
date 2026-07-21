import json
from pathlib import Path
from datetime import datetime as _dt
import logging
import os
import shutil
import tempfile
import zipfile

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.http import HttpResponse, HttpResponseRedirect, StreamingHttpResponse, JsonResponse, FileResponse
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods, require_GET
from django import forms

from app01 import models
from app01.models import Task, UserProfile, HomeworkFile
from app01.upload_data import (
    extract_import_data, parse_course_excel, preview_course_import, write_course_data,
    parse_task_excel, write_task_import,
    parse_teacher_excel, preview_teacher_import, write_teacher_users,
)
from app01.api_auth import require_api_key
from app01.grades import (
    serialize_grade, upsert_grade, LETTER_CHOICES, VALID_LETTERS,
    build_grade_summary, SCORE_UNSET,
)
from app01.models import HomeworkGrade
from app01.libreoffice_preview import (
    convert_office_to_pdf,
    is_previewable_name,
)
from app01.precheck import (
    copy_precheck_to_task,
    resolve_precheck_plan,
    run_precheck_on_file,
    validate_precheck_package,
    precheck_display,
    task_has_reusable_precheck,
)
from app01.report_template import (
    TEMPLATE_MAX_MB,
    autofill_docx_bytes,
    build_cover_values,
    clear_course_template_files,
    clear_task_template_files,
    copy_template_to_task,
    course_has_template_file,
    effective_cover_autofill,
    resolve_task_template,
    save_uploaded_course_template,
    save_uploaded_template,
    student_download_filename,
    task_has_template_file,
    template_abs_path,
    task_allows_report_template,
    template_available_for_student,
)
from app01 import impersonation as impersonation_helpers
from app01.utils import (
    file_iterator,
    is_teacher_or_admin,
    get_display_name,
    safe_filename,
    can_manage_course,
    REF_MATERIAL_MAX_BYTES,
    REF_MATERIAL_MAX_MB,
    reference_material_rel_dir,
    validate_reference_material_filename,
    DOC_FORBIDDEN_MSG,
    is_legacy_doc_filename,
    validate_file_type_setting,
)
from mycourse.settings import BASE_DIR, FILES_ROOT

logger = logging.getLogger('app01')


# ──────────────────────────── API（外部调用，无 Token） ────────────────────────────

def submission_status_api(request):
    """
    学生作业提交状态查询，供考勤成绩计算等外部应用调用。
    GET 参数：course_term, course_name, class_number, task_title（均需与数据库存储完全一致）
    返回：课程、作业、每个学生的提交状态（submitted/overdue/not_submitted）及是否逾期
    """
    if request.method != 'GET':
        return JsonResponse({'code': 405, 'message': '仅支持 GET', 'data': None}, status=405)

    course_term = request.GET.get('course_term', '').strip()
    course_name = request.GET.get('course_name', '').strip()
    class_number = request.GET.get('class_number', '').strip()
    task_title = request.GET.get('task_title', '').strip()

    if not all([course_term, course_name, class_number, task_title]):
        return JsonResponse({
            'code': 400,
            'message': '缺少参数，需提供：course_term, course_name, class_number, task_title',
            'data': None,
        }, status=400)

    course = models.Course.objects.filter(
        courseTerm=course_term,
        courseName=course_name,
        classNumber=class_number,
    ).first()
    if not course:
        return JsonResponse({
            'code': 404,
            'message': f'未找到课程：{course_term} / {course_name} / {class_number}',
            'data': None,
        }, status=404)

    task = models.Task.objects.filter(
        courseBelongTo=course,
        title=task_title,
    ).first()
    if not task:
        return JsonResponse({
            'code': 404,
            'message': f'未找到作业：{task_title}',
            'data': None,
        }, status=404)

    students = course.members.filter(type='S').order_by('user__username')
    homeworks = {hw.user_id: hw for hw in models.Homework.objects.filter(task=task)}

    deadline = task.deadline
    students_data = []
    for s in students:
        hw = homeworks.get(s.id)
        if hw:
            submit_date = hw.submitted_at.date() if hw.submitted_at else None
            delay = bool(submit_date and submit_date > deadline)
            status = 'overdue' if delay else 'submitted'
            submit_time = hw.submitted_at.isoformat() if hw.submitted_at else None
            updated_time = hw.updated_at.isoformat() if hw.updated_at else None
        else:
            delay = False
            status = 'not_submitted'
            submit_time = None
            updated_time = None

        students_data.append({
            'number': s.user.username,
            'name': s.name,
            'status': status,
            'submit_time': submit_time,
            'submitted_at': submit_time,
            'updated_at': updated_time,
            'delay': delay,
        })

    return JsonResponse({
        'code': 0,
        'message': 'ok',
        'data': {
            'course': {
                'courseTerm': course.courseTerm,
                'courseNumber': course.courseNumber,
                'courseName': course.courseName,
                'classNumber': course.classNumber,
            },
            'task': {
                'title': task.title,
                'deadline': task.deadline.isoformat(),
            },
            'students': students_data,
        },
    })


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
def taskSubmit(request, taskID):
    if request.user.profile.type != 'S':
        return HttpResponse("您不是学生，无法进行该操作！")

    task = get_object_or_404(Task, pk=taskID)
    course = task.courseBelongTo

    homework = models.Homework.objects.filter(user=request.user.profile, task=task).first()

    hw_file = None
    hw_file_previewable = False
    if homework:
        hw_file = HomeworkFile.objects.filter(homework=homework).first()
        if hw_file:
            fname = hw_file.standardName or hw_file.originalName or ''
            hw_file_previewable = is_previewable_name(fname)

    fail_grade = None
    if homework:
        try:
            g = homework.grade
            fail_grade = serialize_grade(g, for_student=True)
        except HomeworkGrade.DoesNotExist:
            fail_grade = None

    if not request.session.session_key:
        request.session.save()
    context = {
        'name': get_display_name(request.user),
        'course': course,
        'task': task,
        'hw_file': hw_file,
        'hw_file_previewable': hw_file_previewable,
        'fail_grade': fail_grade,
        'f_warn_session': request.session.session_key or '',
        'template_download': template_available_for_student(task),
        'template_autofill': effective_cover_autofill(task),
        'precheck': precheck_display(task),
        'precheck_warn_active': bool(homework and homework.precheck_warn_active),
        'precheck_warn_text': (homework.precheck_warn_text if homework else '') or '',
    }
    return render(request, 'studentSubmit.html', context)


@login_required
def studentCourse(request, courseTerm, courseName, classNumber):
    student = request.user.profile
    course = models.Course.objects.filter(
        courseTerm=courseTerm, courseName=courseName, classNumber=classNumber
    ).first()
    if not course:
        return HttpResponse('课程不存在')
    if student.type == 'S' and not course.members.filter(pk=student.pk).exists():
        return HttpResponse('您不是该课程学生')

    tasks = models.Task.objects.filter(courseBelongTo=course, display=True)

    taskRecords = []
    for task in tasks:
        homework = models.Homework.objects.filter(task=task, user=student).first()
        today = timezone.now().date()
        past_deadline = today > task.deadline

        if homework:
            hw_file = HomeworkFile.objects.filter(homework=homework).first()
            is_delay = homework.is_late
            fname = ''
            if hw_file:
                fname = hw_file.standardName or hw_file.originalName or ''

            if is_delay:
                status = 'delay_submitted'
                status_text = '逾期提交'
            else:
                status = 'submitted'
                status_text = '已提交'

            grade = None
            try:
                grade = homework.grade
            except HomeworkGrade.DoesNotExist:
                grade = None
            student_grade = serialize_grade(grade, for_student=True)
            fail_visible = bool(student_grade and student_grade.get('is_fail'))
            needs_regrade = bool(fail_visible and grade and grade.needs_regrade)
            taskRecords.append({
                'title': task.title, 'id': task.id,
                'submitted_at': homework.submitted_at, 'updated_at': homework.updated_at, 'deadline': task.deadline,
                'status': status, 'status_text': status_text,
                'has_file': hw_file is not None,
                'file_id': hw_file.id if hw_file else None,
                'previewable': bool(hw_file and is_previewable_name(fname)),
                'fail_visible': fail_visible,
                'fail_need_action': bool(fail_visible and not needs_regrade),
                'grade_comment': (student_grade or {}).get('comment') or '',
                'needs_regrade': needs_regrade,
                'template_download': template_available_for_student(task),
                'precheck': precheck_display(task),
                'precheck_warn_active': bool(homework.precheck_warn_active),
                'precheck_warn_text': homework.precheck_warn_text or '',
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
                'submitted_at': '', 'updated_at': '', 'deadline': task.deadline,
                'status': status, 'status_text': status_text,
                'has_file': False,
                'file_id': None,
                'previewable': False,
                'fail_visible': False,
                'fail_need_action': False,
                'grade_comment': '',
                'needs_regrade': False,
                'template_download': template_available_for_student(task),
                'precheck': precheck_display(task),
                'precheck_warn_active': False,
                'precheck_warn_text': '',
            })

    reference_materials = models.ReferenceMaterial.objects.filter(
        course=course, display=True
    ).order_by('sort_order', '-created_at', 'id')

    if not request.session.session_key:
        request.session.save()
    context = {
        'taskRecords': taskRecords,
        'name': get_display_name(request.user),
        'course': course,
        'reference_materials': reference_materials,
        'student_username': request.user.username,
        'f_warn_session': request.session.session_key or '',
        'has_fail_grade': any(r.get('fail_visible') for r in taskRecords),
        'has_fail_need_action': any(r.get('fail_need_action') for r in taskRecords),
        'has_fail_pending_regrade': any(r.get('fail_visible') and r.get('needs_regrade') for r in taskRecords),
    }
    return render(request, 'studentTaskList.html', context)


@login_required
def studentGetTaskByCoursename(request, courseTerm, courseName, classNumber):
    return redirect('studentCourse', courseTerm=courseTerm,
                    courseName=courseName, classNumber=classNumber)


@login_required
def studentCourseList(request):
    from django.db.models import Count
    from collections import OrderedDict

    courses = (models.Course.objects.filter(members__user=request.user, status='Y')
               .annotate(task_count=Count('task'))
               .order_by('-courseTerm', 'courseName'))

    term_groups = OrderedDict()
    for c in courses:
        term_groups.setdefault(c.courseTerm, []).append(c)

    context = {
        'term_groups': term_groups,
        'total_courses': courses.count(),
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
    task = models.Task.objects.select_related('courseBelongTo').get(id=task_id)

    if is_legacy_doc_filename(file_obj.name):
        return HttpResponse(DOC_FORBIDDEN_MSG)

    if task.fileType != '*' and suffix:
        allowed = [x.strip().lower().lstrip('.') for x in task.fileType.split(',')]
        if suffix.lower() not in allowed:
            return HttpResponse(f'文件类型不允许，仅支持：{task.fileType}')

    plan = resolve_precheck_plan(task)
    force_ack = (request.POST.get('precheck_ack') or '') in ('1', 'true', 'yes')
    tmp_path = None
    precheck_result = None
    if plan.do_cover or plan.do_framework:
        if suffix.lower() != 'docx':
            return HttpResponse('本作业已开启报告预检，仅允许提交 .docx 文件')
        # 先落临时文件做预检，通过后再写入正式路径
        fd, tmp_path = tempfile.mkstemp(suffix='.docx')
        os.close(fd)
        with open(tmp_path, 'wb') as tf:
            for chunk in file_obj.chunks():
                tf.write(chunk)
        file_obj.seek(0)
        precheck_result = run_precheck_on_file(tmp_path, task, request.user.profile, request.user)
        if not precheck_result.ok:
            body = precheck_result.as_text()
            if precheck_result.fail_mode == 'warn' and not force_ack:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                return HttpResponse('PRECHECK_WARN' + chr(10) + body)
            if precheck_result.fail_mode != 'warn':
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                return HttpResponse('PRECHECK_FAIL' + chr(10) + body)
            # warn + 已确认：继续用临时文件提交
        with open(tmp_path, 'rb') as tf:
            file_bytes = tf.read()
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        tmp_path = None
    else:
        file_bytes = None

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

    now = timezone.now()
    homework, created = models.Homework.objects.get_or_create(
        user=request.user.profile,
        task=task,
        defaults={'submitted_at': now, 'updated_at': now},
    )
    if not created:
        updates = {'updated_at': now}
        if not homework.submitted_at:
            updates['submitted_at'] = now
        for k, v in updates.items():
            setattr(homework, k, v)
        homework.save(update_fields=list(updates.keys()))

    HomeworkFile.objects.update_or_create(
        homework=homework,
        defaults={'filePath': rel_path, 'originalName': file_obj.name}
    )

    with open(abs_path, 'wb') as f:
        if file_bytes is not None:
            f.write(file_bytes)
        else:
            f.write(file_obj.read())

    # F 后重交：保留不合格等级，标记待重评
    if not created:
        try:
            grade = homework.grade
        except HomeworkGrade.DoesNotExist:
            grade = None
        if grade is not None and grade.letter_grade == HomeworkGrade.GRADE_F and not grade.needs_regrade:
            grade.needs_regrade = True
            grade.save(update_fields=['needs_regrade', 'updated_at'])

    # 仅警告确认后提交：保留警告标记；预检通过或未开启预检则清除
    warn_fields = ['precheck_warn_active', 'precheck_warn_text', 'precheck_warned_at']
    if precheck_result is not None and (not precheck_result.ok) and precheck_result.fail_mode == 'warn':
        homework.precheck_warn_active = True
        homework.precheck_warn_text = (precheck_result.as_text() or '')[:4000]
        homework.precheck_warned_at = now
    else:
        homework.precheck_warn_active = False
        homework.precheck_warn_text = ''
        homework.precheck_warned_at = None
    homework.save(update_fields=warn_fields)

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


@login_required
def preview_homework_file(request, file_id):
    """
    在线预览作业附件：.pdf 直接打开；.doc/.docx 经 LibreOffice 转 PDF 后内联打开。
    权限与下载一致：本人或教师/管理员。
    """
    hw_file = get_object_or_404(HomeworkFile, pk=file_id)

    if not is_teacher_or_admin(request.user):
        if hw_file.homework.user != request.user.profile:
            return HttpResponse("无权预览此文件", status=403)

    file_path = hw_file.absPath
    if not os.path.exists(file_path):
        return HttpResponse("文件不存在", status=404)

    filename = hw_file.standardName or hw_file.originalName or os.path.basename(file_path)
    suffix = Path(filename).suffix.lower() or Path(file_path).suffix.lower()

    if not is_previewable_name(filename) and suffix not in {".doc", ".docx", ".pdf"}:
        return HttpResponse(
            f"该文件类型不支持在线预览（当前：{suffix or '未知'}）。请下载后查看。",
            status=400,
        )

    if suffix == ".pdf":
        return FileResponse(
            open(file_path, "rb"),
            as_attachment=False,
            filename=filename,
            content_type="application/pdf",
        )

    if suffix in {".doc", ".docx"}:
        try:
            pdf_path = convert_office_to_pdf(file_path, hw_file)
        except Exception as exc:
            logger.exception("预览转换异常 file_id=%s", file_id)
            return HttpResponse(f"PDF 预览生成失败：{exc}", status=500)
        if not pdf_path:
            lo = "未检测到 LibreOfficePortable/soffice，或转换失败。"
            return HttpResponse(
                f"无法生成预览。{lo} 请确认项目目录下已放置 LibreOfficePortable，或下载原文件查看。",
                status=503,
            )
        return FileResponse(
            open(pdf_path, "rb"),
            as_attachment=False,
            filename=f"{Path(filename).stem}.pdf",
            content_type="application/pdf",
        )

    return HttpResponse("不支持的预览类型", status=400)


# ──────────────────────────── 教师端 ────────────────────────────

@login_required
def teacherGetTaskByCoursename(request, courseTerm, courseName, classNumber):
    return redirect('teacherCourseChange', courseTerm=courseTerm,
                    courseName=courseName, classNumber=classNumber)


@login_required
def teacherCourseList(request):
    from django.db.models import Count
    from collections import OrderedDict

    if not is_teacher_or_admin(request.user):
        return redirect('studentCourseList')

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
    ft_err, fileType = validate_file_type_setting(fileType)
    if ft_err:
        return HttpResponse(
            "<script>alert(%s);history.back();</script>" % json.dumps(ft_err, ensure_ascii=False)
        )

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
    clear_task_template_files(task)
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
                    is_delay = homework.is_late
                    if is_delay:
                        records.append({
                            'title': task.title, 'name': student.name,
                            'number': student.user.username,
                            'submitted_at': homework.submitted_at, 'updated_at': homework.updated_at, 'deadline': task.deadline,
                            'status': '延期提交',
                            'has_file': has_file,
                        })
                else:
                    if timezone.now().date() > task.deadline:
                        records.append({
                            'title': task.title, 'name': student.name,
                            'number': student.user.username,
                            'submitted_at': '', 'updated_at': '', 'deadline': task.deadline,
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
def homeworkRecords(request, taskID):
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
                fname = os.path.basename(hw_file.filePath) if hw_file else ''
                try:
                    grade_obj = hw.grade
                except HomeworkGrade.DoesNotExist:
                    grade_obj = None
                gdata = serialize_grade(grade_obj, for_student=False)
                submitRecords.append({
                    'homework_id': hw.id,
                    'number': hw.user.user.username,
                    'name': hw.user.name,
                    'gender': hw.user.gender,
                    'submitted_at': hw.submitted_at, 'updated_at': hw.updated_at,
                    'delay': hw.is_late,
                    'file_name': fname,
                    'file_id': hw_file.id if hw_file else None,
                    'has_file': hw_file is not None,
                    'previewable': bool(hw_file and is_previewable_name(fname or hw_file.originalName)),
                    'letter_grade': (gdata or {}).get('letter_grade') or '',
                    'score': (gdata or {}).get('score'),
                    'comment': (gdata or {}).get('comment') or '',
                    'needs_regrade': bool(grade_obj and grade_obj.needs_regrade),
                    'is_fail': bool(grade_obj and grade_obj.is_fail),
                    'precheck_warn_active': bool(hw.precheck_warn_active),
                    'precheck_warn_text': hw.precheck_warn_text or '',
                })

        for student in students:
            if student not in submitStudents:
                notSubmitStudents.append({
                    'number': student.user.username,
                    'name': student.name,
                    'gender': student.gender,
                })

        summary = build_grade_summary(task, students_qs=students)
        context = {
            'name': get_display_name(request.user),
            'course': course,
            'task': task,
            'submitRecords': submitRecords,
            'notSubmitStudents': notSubmitStudents,
            'letter_choices': LETTER_CHOICES,
            'summary': summary,
        }
        return render(request, 'homeworkRecords.html', context)
    except Task.DoesNotExist:
        return HttpResponse(f'作业 id={taskID} 不存在')


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
        fields = ['title', 'content', 'display', 'deadline', 'fileType', 'precheck_mode', 'precheck_fail_mode']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'content': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'display': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'deadline': forms.DateInput(format='%Y-%m-%d',
                                        attrs={'type': 'date', 'class': 'form-control'}),
            'fileType': forms.TextInput(attrs={'class': 'form-control',
                                               'placeholder': '如 .docx,.pdf,.zip 或 * 表示不限（禁止 .doc）'}),
            'precheck_mode': forms.Select(attrs={'class': 'form-select'}),
            'precheck_fail_mode': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'title': '作业标题',
            'content': '作业正文',
            'display': '是否显示',
            'deadline': '截止日期',
            'fileType': '允许的文件类型',
            'precheck_mode': '预检模式',
            'precheck_fail_mode': '预检失败策略',
        }

    def clean_fileType(self):
        ft = self.cleaned_data.get('fileType') or '*'
        err, normalized = validate_file_type_setting(ft)
        if err:
            raise forms.ValidationError(err)
        return normalized


@login_required
def taskChange(request, taskID):
    if not is_teacher_or_admin(request.user):
        return HttpResponse("您没有权限进行该操作！")
    try:
        task = Task.objects.get(id=taskID)
    except Task.DoesNotExist:
        return HttpResponse(f'作业 id={taskID} 不存在')

    if request.method == 'POST':
        form = TaskEditForm(request.POST, instance=task)
        if form.is_valid():
            form.save()
            course = task.courseBelongTo
            return redirect('teacherCourseChange', course.courseTerm, course.courseName, course.classNumber)
        # 校验失败（如填写了 .doc）留在本页展示错误
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
        'has_template': task_has_template_file(task),
        'inherits_course_template': (not task_has_template_file(task)) and course_has_template_file(task.courseBelongTo),
        'template_allowed': task_allows_report_template(task),
        'template_max_mb': TEMPLATE_MAX_MB,
        'precheck_plan': resolve_precheck_plan(task),
        'has_precheck_package': bool((task.precheck_package_json or '').strip()),
    }
    return render(request, 'taskChange.html', context)



@login_required
@require_POST

@login_required
@require_POST
def update_course_precheck_settings(request, courseID):
    """课程预检总开关。"""
    if not is_teacher_or_admin(request.user):
        return JsonResponse({'ok': False, 'error': '无权限'}, status=403)
    course = models.Course.objects.filter(pk=courseID).first()
    if not course:
        return JsonResponse({'ok': False, 'error': '课程不存在'}, status=404)
    if not can_manage_course(request.user, course):
        return JsonResponse({'ok': False, 'error': '无权管理该课程'}, status=403)
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': '请求体须为 JSON'}, status=400)
    master = data.get('precheck_master', course.precheck_master)
    mode = data.get('precheck_cover_mode', course.precheck_cover_mode)
    if master not in ('off', 'cover_default'):
        return JsonResponse({'ok': False, 'error': 'precheck_master 无效'}, status=400)
    if mode not in ('block', 'warn'):
        return JsonResponse({'ok': False, 'error': 'precheck_cover_mode 无效'}, status=400)
    course.precheck_master = master
    course.precheck_cover_mode = mode
    course.save(update_fields=['precheck_master', 'precheck_cover_mode'])
    return JsonResponse({
        'ok': True,
        'precheck_master': course.precheck_master,
        'precheck_cover_mode': course.precheck_cover_mode,
    })


def upload_course_report_template(request, courseID):
    """上传课程默认报告模板（全课作业可继承）。"""
    if not is_teacher_or_admin(request.user):
        return JsonResponse({'ok': False, 'error': '无权限'}, status=403)
    course = models.Course.objects.filter(pk=courseID).first()
    if not course:
        return JsonResponse({'ok': False, 'error': '课程不存在'}, status=404)
    if not can_manage_course(request.user, course):
        return JsonResponse({'ok': False, 'error': '无权管理该课程'}, status=403)
    f = request.FILES.get('file')
    if not f:
        return JsonResponse({'ok': False, 'error': '请选择 .docx 文件'}, status=400)
    err, _ = save_uploaded_course_template(course, f)
    if err:
        return JsonResponse({'ok': False, 'error': err}, status=400)
    course.refresh_from_db()
    return JsonResponse({
        'ok': True,
        'original_name': course.report_template_original_name,
        'uploaded_at': course.report_template_uploaded_at.strftime('%Y-%m-%d %H:%M') if course.report_template_uploaded_at else '',
        'enable_report_template_download': course.enable_report_template_download,
        'enable_report_cover_autofill': course.enable_report_cover_autofill,
    })


@login_required
@require_POST
def delete_course_report_template(request, courseID):
    if not is_teacher_or_admin(request.user):
        return JsonResponse({'ok': False, 'error': '无权限'}, status=403)
    course = models.Course.objects.filter(pk=courseID).first()
    if not course:
        return JsonResponse({'ok': False, 'error': '课程不存在'}, status=404)
    if not can_manage_course(request.user, course):
        return JsonResponse({'ok': False, 'error': '无权管理该课程'}, status=403)
    clear_course_template_files(course)
    course.report_template_path = ''
    course.report_template_original_name = ''
    course.report_template_uploaded_at = None
    course.enable_report_template_download = False
    course.enable_report_cover_autofill = False
    course.save(update_fields=[
        'report_template_path', 'report_template_original_name', 'report_template_uploaded_at',
        'enable_report_template_download', 'enable_report_cover_autofill',
    ])
    return JsonResponse({'ok': True})


@login_required
@require_POST
def update_course_template_settings(request, courseID):
    if not is_teacher_or_admin(request.user):
        return JsonResponse({'ok': False, 'error': '无权限'}, status=403)
    course = models.Course.objects.filter(pk=courseID).first()
    if not course:
        return JsonResponse({'ok': False, 'error': '课程不存在'}, status=404)
    if not can_manage_course(request.user, course):
        return JsonResponse({'ok': False, 'error': '无权管理该课程'}, status=403)
    if not course_has_template_file(course):
        return JsonResponse({'ok': False, 'error': '请先上传课程默认模板'}, status=400)
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': '请求体须为 JSON'}, status=400)
    update_fields = []
    if 'enable_report_template_download' in data:
        course.enable_report_template_download = bool(data['enable_report_template_download'])
        update_fields.append('enable_report_template_download')
    if 'enable_report_cover_autofill' in data:
        course.enable_report_cover_autofill = bool(data['enable_report_cover_autofill'])
        update_fields.append('enable_report_cover_autofill')
    if not update_fields:
        return JsonResponse({'ok': False, 'error': '无有效字段'}, status=400)
    course.save(update_fields=update_fields)
    return JsonResponse({
        'ok': True,
        'enable_report_template_download': course.enable_report_template_download,
        'enable_report_cover_autofill': course.enable_report_cover_autofill,
    })


@login_required
@require_GET
def download_course_report_template_master(request, courseID):
    if not is_teacher_or_admin(request.user):
        return HttpResponse('无权限', status=403)
    course = models.Course.objects.filter(pk=courseID).first()
    if not course:
        return HttpResponse('课程不存在', status=404)
    if not can_manage_course(request.user, course):
        return HttpResponse('无权管理该课程', status=403)
    if not course_has_template_file(course):
        return HttpResponse('尚未上传课程默认模板', status=404)
    abs_path = template_abs_path(course.report_template_path)
    filename = course.report_template_original_name or os.path.basename(abs_path)
    return FileResponse(
        open(abs_path, 'rb'),
        as_attachment=True,
        filename=filename,
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )


def upload_task_report_template(request, taskID):
    """教师上传/替换作业报告模板（.docx）。"""
    if not is_teacher_or_admin(request.user):
        return JsonResponse({'ok': False, 'error': '无权限'}, status=403)
    task = models.Task.objects.filter(pk=taskID).select_related('courseBelongTo').first()
    if not task:
        return JsonResponse({'ok': False, 'error': '作业不存在'}, status=404)
    if not can_manage_course(request.user, task.courseBelongTo):
        return JsonResponse({'ok': False, 'error': '无权管理该课程'}, status=403)
    f = request.FILES.get('file')
    if not f:
        return JsonResponse({'ok': False, 'error': '请选择 .docx 文件'}, status=400)
    err, _orig = save_uploaded_template(task, f)
    if err:
        return JsonResponse({'ok': False, 'error': err}, status=400)
    task.refresh_from_db()
    return JsonResponse({
        'ok': True,
        'original_name': task.template_original_name,
        'uploaded_at': task.template_uploaded_at.strftime('%Y-%m-%d %H:%M') if task.template_uploaded_at else '',
        'enable_template_download': task.enable_template_download,
        'enable_cover_autofill': task.enable_cover_autofill,
    })


@login_required
@require_POST
def delete_task_report_template(request, taskID):
    """教师删除作业报告模板。"""
    if not is_teacher_or_admin(request.user):
        return JsonResponse({'ok': False, 'error': '无权限'}, status=403)
    task = models.Task.objects.filter(pk=taskID).select_related('courseBelongTo').first()
    if not task:
        return JsonResponse({'ok': False, 'error': '作业不存在'}, status=404)
    if not can_manage_course(request.user, task.courseBelongTo):
        return JsonResponse({'ok': False, 'error': '无权管理该课程'}, status=403)
    clear_task_template_files(task)
    task.template_path = ''
    task.template_original_name = ''
    task.template_uploaded_at = None
    task.enable_template_download = False
    task.enable_cover_autofill = False
    task.save(update_fields=[
        'template_path', 'template_original_name', 'template_uploaded_at',
        'enable_template_download', 'enable_cover_autofill',
    ])
    return JsonResponse({'ok': True})


@login_required
@require_POST
def update_task_template_settings(request, taskID):
    """教师更新模板开关。"""
    if not is_teacher_or_admin(request.user):
        return JsonResponse({'ok': False, 'error': '无权限'}, status=403)
    task = models.Task.objects.filter(pk=taskID).select_related('courseBelongTo').first()
    if not task:
        return JsonResponse({'ok': False, 'error': '作业不存在'}, status=404)
    if not can_manage_course(request.user, task.courseBelongTo):
        return JsonResponse({'ok': False, 'error': '无权管理该课程'}, status=403)
    if not task_allows_report_template(task):
        return JsonResponse({'ok': False, 'error': '本作业不允许 .docx，不能使用报告模板'}, status=400)
    if not task_has_template_file(task):
        return JsonResponse({'ok': False, 'error': '请先上传报告模板'}, status=400)
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': '请求体须为 JSON'}, status=400)
    update_fields = []
    if 'enable_template_download' in data:
        task.enable_template_download = bool(data['enable_template_download'])
        update_fields.append('enable_template_download')
    if 'enable_cover_autofill' in data:
        task.enable_cover_autofill = bool(data['enable_cover_autofill'])
        update_fields.append('enable_cover_autofill')
    if not update_fields:
        return JsonResponse({'ok': False, 'error': '无有效字段'}, status=400)
    task.save(update_fields=update_fields)
    return JsonResponse({
        'ok': True,
        'enable_template_download': task.enable_template_download,
        'enable_cover_autofill': task.enable_cover_autofill,
    })


@login_required
@require_GET
def download_task_report_template_master(request, taskID):
    """教师下载母版（不自动填封面）。"""
    if not is_teacher_or_admin(request.user):
        return HttpResponse('无权限', status=403)
    task = models.Task.objects.filter(pk=taskID).select_related('courseBelongTo').first()
    if not task:
        return HttpResponse('作业不存在', status=404)
    if not can_manage_course(request.user, task.courseBelongTo):
        return HttpResponse('无权管理该课程', status=403)
    if not task_has_template_file(task):
        return HttpResponse('尚未上传模板', status=404)
    abs_path = template_abs_path(task.template_path)
    filename = task.template_original_name or os.path.basename(abs_path)
    return FileResponse(
        open(abs_path, 'rb'),
        as_attachment=True,
        filename=filename,
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )


@login_required
@require_GET
def download_task_report_template_student(request, taskID):
    """学生下载报告模板（可选自动填封面）。"""
    task = models.Task.objects.filter(pk=taskID).select_related('courseBelongTo').first()
    if not task:
        return HttpResponse('作业不存在', status=404)
    course = task.courseBelongTo
    profile = getattr(request.user, 'profile', None)
    if profile is None:
        return HttpResponse('用户资料不存在', status=403)
    # 教师/超管可下载（预览效果）；学生须为本课程成员且作业开放下载
    is_staff = is_teacher_or_admin(request.user)
    if is_staff:
        if not can_manage_course(request.user, course) and not request.user.is_superuser:
            # 非本课教师：仍允许超管；普通教师需管理权限
            if not request.user.is_superuser:
                return HttpResponse('无权下载', status=403)
    else:
        if not course.members.filter(pk=profile.pk).exists():
            return HttpResponse('你不是本课程学生', status=403)
        if not template_available_for_student(task):
            return HttpResponse('本作业未开放报告模板下载', status=404)

    resolved = resolve_task_template(task)
    if not resolved:
        return HttpResponse('模板文件缺失', status=404)

    abs_path = resolved.abs_path
    do_fill = bool(resolved.enable_autofill)
    # 学生必须开放下载；教师试下载可无视 enable_download
    if not is_staff and not resolved.enable_download:
        return HttpResponse('本作业未开放报告模板下载', status=404)

    if do_fill:
        values = build_cover_values(task, profile, request.user)
        content = autofill_docx_bytes(abs_path, values)
        filename = student_download_filename(task, profile, request.user)
        from django.http import HttpResponse as _HR
        from urllib.parse import quote
        resp = _HR(
            content,
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        resp['Content-Disposition'] = "attachment; filename*=UTF-8''%s" % quote(filename)
        return resp

    filename = resolved.original_name or os.path.basename(abs_path)
    return FileResponse(
        open(abs_path, 'rb'),
        as_attachment=True,
        filename=filename,
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )


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
    if not is_teacher_or_admin(request.user):
        return redirect('studentCourseList')

    course = models.Course.objects.filter(
        courseTerm=courseTerm, courseName=courseName, classNumber=classNumber
    ).first()
    if not course:
        return HttpResponse("课程不存在")
    if not can_manage_course(request.user, course):
        return HttpResponse("您无权管理该课程", status=403)

    students = course.members.filter(type='S')
    tasks = list(models.Task.objects.filter(courseBelongTo=course))

    task_data = []
    for task in tasks:
        submitted, not_submitted, seen = [], [], set()
        for hw in models.Homework.objects.filter(task=task):
            if hw.user.pk in seen or hw.user not in students:
                continue
            seen.add(hw.user.pk)
            hw_file = HomeworkFile.objects.filter(homework=hw).first()
            fname = ''
            if hw_file:
                fname = os.path.basename(hw_file.filePath) or hw_file.originalName or ''
            submitted.append({
                'number': hw.user.user.username,
                'name': hw.user.name,
                'gender': hw.user.gender,
                'submitted_at': hw.submitted_at, 'updated_at': hw.updated_at,
                'delay': hw.is_late,
                'has_file': hw_file is not None,
                'file_id': hw_file.id if hw_file else None,
                'previewable': bool(hw_file and is_previewable_name(fname)),
                'precheck_warn_active': bool(hw.precheck_warn_active),
                'precheck_warn_text': hw.precheck_warn_text or '',
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
            'template_allowed': task_allows_report_template(task),
            'precheck': precheck_display(task),
        })

    reference_materials = models.ReferenceMaterial.objects.filter(course=course).order_by(
        'sort_order', '-created_at', 'id'
    )

    context = {
        'task_data': task_data,
        'student_list': students,
        'student_count': students.count(),
        'name': get_display_name(request.user),
        'course': course,
        'has_course_template': course_has_template_file(course),
        'template_max_mb': TEMPLATE_MAX_MB,
        'reference_materials': reference_materials,
    }
    return render(request, 'teacherCourseDetail.html', context)


def _teacher_course_redirect(course, tab=''):
    url = reverse(
        'teacherCourseChange',
        kwargs={
            'courseTerm': course.courseTerm,
            'courseName': course.courseName,
            'classNumber': course.classNumber,
        },
    )
    if tab:
        url += f'?tab={tab}'
    return redirect(url)


@login_required
@require_POST
def ref_material_save(request):
    """新增或编辑参考资料（multipart）。"""
    if not is_teacher_or_admin(request.user):
        return HttpResponse('无权限', status=403)

    course_id = request.POST.get('course_id')
    material_id = (request.POST.get('material_id') or '').strip()
    course = get_object_or_404(models.Course, pk=course_id)
    if not can_manage_course(request.user, course):
        return HttpResponse('无权限管理该课程', status=403)

    title = (request.POST.get('title') or '').strip()
    description = (request.POST.get('description') or '').strip()
    display = request.POST.get('display') == 'on'

    if not title:
        return HttpResponse('标题不能为空', status=400)

    rel_dir = reference_material_rel_dir(course)
    abs_dir = os.path.join(BASE_DIR, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    profile = getattr(request.user, 'profile', None)

    if material_id:
        mat = get_object_or_404(
            models.ReferenceMaterial, pk=material_id, course=course
        )
        file_obj = request.FILES.get('file')
        if file_obj:
            if file_obj.size > REF_MATERIAL_MAX_BYTES:
                return HttpResponse(
                    f'文件超过 {REF_MATERIAL_MAX_MB} MB 限制', status=400
                )
            ok, base, verr = validate_reference_material_filename(file_obj.name)
            if not ok:
                return HttpResponse(verr, status=400)
            if models.ReferenceMaterial.objects.filter(
                course=course, originalName__iexact=base
            ).exclude(pk=mat.pk).exists():
                return HttpResponse(
                    f'本课程已有其他资料使用文件名「{base}」，请更换文件或先删除/重命名该资料',
                    status=400,
                )
            old_path = mat.abs_path
            new_abs = os.path.join(BASE_DIR, rel_dir, base)
            if os.path.normcase(new_abs) != os.path.normcase(old_path) and os.path.lexists(new_abs):
                return HttpResponse(
                    f'参考资料目录下已存在同名文件「{base}」，无法保存', status=400
                )
            if old_path and os.path.isfile(old_path):
                try:
                    os.unlink(old_path)
                except OSError:
                    logger.warning('删除旧参考资料文件失败: %s', old_path)
            rel_path = os.path.join(rel_dir, base)
            with open(new_abs, 'wb') as out:
                for chunk in file_obj.chunks():
                    out.write(chunk)
            mat.filePath = rel_path
            mat.originalName = base
            mat.file_size = file_obj.size
        mat.title = title
        mat.description = description
        mat.display = display
        mat.save()
        return _teacher_course_redirect(course, tab='ref')

    file_obj = request.FILES.get('file')
    if not file_obj:
        return HttpResponse('请选择附件', status=400)
    if file_obj.size > REF_MATERIAL_MAX_BYTES:
        return HttpResponse(
            f'文件超过 {REF_MATERIAL_MAX_MB} MB 限制', status=400
        )

    ok, base, verr = validate_reference_material_filename(file_obj.name)
    if not ok:
        return HttpResponse(verr, status=400)
    if models.ReferenceMaterial.objects.filter(
        course=course, originalName__iexact=base
    ).exists():
        return HttpResponse(
            f'本课程已存在同名文件「{base}」，请更换文件名或删除旧条目后再上传',
            status=400,
        )
    abs_path = os.path.join(BASE_DIR, rel_dir, base)
    if os.path.lexists(abs_path):
        return HttpResponse(
            f'参考资料目录下已存在同名文件「{base}」，请删除磁盘上的该文件或换名后再上传',
            status=400,
        )

    rel_path = os.path.join(rel_dir, base)
    with open(abs_path, 'wb') as out:
        for chunk in file_obj.chunks():
            out.write(chunk)

    next_order = models.ReferenceMaterial.objects.filter(course=course).count()
    models.ReferenceMaterial.objects.create(
        course=course,
        title=title,
        description=description,
        filePath=rel_path,
        originalName=base,
        file_size=file_obj.size,
        sort_order=next_order,
        display=display,
        uploaded_by=profile,
    )
    return _teacher_course_redirect(course, tab='ref')


@login_required
@require_POST
def ref_material_delete(request):
    if not is_teacher_or_admin(request.user):
        return HttpResponse('无权限', status=403)
    material_id = request.POST.get('material_id')
    mat = get_object_or_404(models.ReferenceMaterial, pk=material_id)
    course = mat.course
    if not can_manage_course(request.user, course):
        return HttpResponse('无权限', status=403)
    path = mat.abs_path
    mat.delete()
    if path and os.path.isfile(path):
        try:
            os.unlink(path)
        except OSError:
            logger.warning('删除参考资料文件失败: %s', path)
    _renumber_ref_sort_order(course)
    return _teacher_course_redirect(course, tab='ref')


def _renumber_ref_sort_order(course):
    rows = list(
        models.ReferenceMaterial.objects.filter(course=course).order_by(
            'sort_order', '-created_at', 'id'
        )
    )
    for i, r in enumerate(rows):
        if r.sort_order != i:
            r.sort_order = i
            r.save(update_fields=['sort_order'])


@login_required
@require_POST
def ref_material_reorder(request):
    """上移/下移参考资料，按当前列表顺序交换后重新编号 sort_order 为 0..n-1。"""
    if not is_teacher_or_admin(request.user):
        return HttpResponse('无权限', status=403)
    material_id = request.POST.get('material_id')
    direction = (request.POST.get('direction') or '').strip().lower()
    if direction not in ('up', 'down'):
        return HttpResponse('参数错误', status=400)

    mat = get_object_or_404(models.ReferenceMaterial, pk=material_id)
    course = mat.course
    if not can_manage_course(request.user, course):
        return HttpResponse('无权限', status=403)

    rows = list(
        models.ReferenceMaterial.objects.filter(course=course).order_by(
            'sort_order', '-created_at', 'id'
        )
    )
    idx = next((i for i, r in enumerate(rows) if r.id == mat.id), None)
    if idx is None:
        return _teacher_course_redirect(course, tab='ref')
    j = idx - 1 if direction == 'up' else idx + 1
    if j < 0 or j >= len(rows):
        return _teacher_course_redirect(course, tab='ref')

    rows[idx], rows[j] = rows[j], rows[idx]
    for i, r in enumerate(rows):
        if r.sort_order != i:
            r.sort_order = i
            r.save(update_fields=['sort_order'])

    return _teacher_course_redirect(course, tab='ref')


@login_required
def download_ref_material(request, material_id):
    mat = get_object_or_404(models.ReferenceMaterial, pk=material_id)
    course = mat.course
    user = request.user

    if is_teacher_or_admin(user):
        if not can_manage_course(user, course):
            return HttpResponse('无权限下载', status=403)
    else:
        prof = user.profile
        if prof.type != 'S':
            return HttpResponse('无权限', status=403)
        if not mat.display:
            return HttpResponse('无权限', status=403)
        if not course.members.filter(pk=prof.pk).exists():
            return HttpResponse('无权限', status=403)

    file_path = mat.abs_path
    if not os.path.exists(file_path):
        return HttpResponse('文件不存在', status=404)

    dl_name = safe_filename(mat.originalName) or os.path.basename(file_path)
    response = StreamingHttpResponse(file_iterator(file_path))
    response['Content-Type'] = 'application/octet-stream'
    response['Content-Disposition'] = (
        'attachment;filename=' + dl_name.encode('utf-8').decode('ISO-8859-1')
    )
    return response


@login_required
def get_history_reference_materials(request, courseID):
    """同名课程的历史参考资料列表（JSON），规则对齐 getHistoryTasks。"""
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
            courseName=current_course.courseName,
        ).exclude(pk=courseID)

    existing_titles = set(
        models.ReferenceMaterial.objects.filter(course=current_course).values_list(
            'title', flat=True
        )
    )
    existing_files_lower = {
        (n or '').lower()
        for n in models.ReferenceMaterial.objects.filter(course=current_course).values_list(
            'originalName', flat=True
        )
    }

    result = []
    for course in courses.distinct():
        materials = models.ReferenceMaterial.objects.filter(course=course).order_by(
            'sort_order', '-created_at', 'id'
        )
        if not materials.exists():
            continue
        mlist = []
        for m in materials:
            fn_lower = (m.originalName or '').lower()
            dup_title = m.title in existing_titles
            dup_file = bool(fn_lower and fn_lower in existing_files_lower)
            mlist.append({
                'id': m.id,
                'title': m.title,
                'originalName': m.originalName,
                'duplicate': dup_title or dup_file,
            })
        result.append({
            'courseID': course.id,
            'courseTerm': course.courseTerm,
            'courseName': course.courseName,
            'classNumber': course.classNumber,
            'materials': mlist,
        })

    return JsonResponse({'courses': result})


@login_required
@require_POST
def copy_reference_materials(request):
    """从同名课程的其它班级/学期复制参考资料（含磁盘文件副本）。"""
    if not is_teacher_or_admin(request.user):
        return JsonResponse({'error': '无权限'}, status=403)

    data = json.loads(request.body.decode('utf-8'))
    target_id = data.get('courseID')
    material_ids = data.get('materialIDs', [])

    target_course = get_object_or_404(models.Course, pk=target_id)
    if not can_manage_course(request.user, target_course):
        return JsonResponse({'error': '无权限管理目标课程'}, status=403)

    existing_titles = set(
        models.ReferenceMaterial.objects.filter(course=target_course).values_list(
            'title', flat=True
        )
    )
    existing_files_lower = {
        (n or '').lower()
        for n in models.ReferenceMaterial.objects.filter(course=target_course).values_list(
            'originalName', flat=True
        )
    }

    copied = []
    errors = []
    profile = getattr(request.user, 'profile', None)
    rel_dir = reference_material_rel_dir(target_course)
    abs_dir = os.path.join(BASE_DIR, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    order_next = models.ReferenceMaterial.objects.filter(course=target_course).count()

    for mid in material_ids:
        try:
            src = models.ReferenceMaterial.objects.select_related('course').get(pk=mid)
        except models.ReferenceMaterial.DoesNotExist:
            errors.append(f'资料 id={mid} 不存在')
            continue

        if src.course.courseName != target_course.courseName:
            errors.append(f'「{src.title}」来源课程名不一致，已跳过')
            continue

        if not request.user.is_superuser:
            if not src.course.members.filter(user=request.user).exists():
                errors.append(f'「{src.title}」无权限从该源课程复制')
                continue

        if src.title in existing_titles:
            continue

        src_path = src.abs_path
        if not os.path.isfile(src_path):
            errors.append(f'「{src.title}」源文件缺失')
            continue

        ok, base, verr = validate_reference_material_filename(src.originalName)
        if not ok:
            errors.append(f'「{src.title}」文件名不合法：{verr}')
            continue
        if base.lower() in existing_files_lower:
            errors.append(f'「{src.title}」目标课程已有同名文件「{base}」，已跳过')
            continue
        dst_abs = os.path.join(BASE_DIR, rel_dir, base)
        if os.path.lexists(dst_abs):
            errors.append(f'「{src.title}」目标目录已存在文件「{base}」，已跳过')
            continue
        dst_rel = os.path.join(rel_dir, base)
        try:
            shutil.copy2(src_path, dst_abs)
        except OSError as e:
            errors.append(f'「{src.title}」复制失败：{e}')
            continue

        models.ReferenceMaterial.objects.create(
            course=target_course,
            title=src.title,
            description=src.description,
            filePath=dst_rel,
            originalName=base,
            file_size=src.file_size,
            sort_order=order_next,
            display=src.display,
            uploaded_by=profile,
        )
        order_next += 1
        copied.append(src.title)
        existing_titles.add(src.title)
        existing_files_lower.add(base.lower())

    return JsonResponse({'success': True, 'copied': copied, 'errors': errors})


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
                'has_template': task_has_template_file(t),
                'has_precheck': task_has_reusable_precheck(t),
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
            new_task = models.Task.objects.create(
                title=new_title, content=src.content,
                courseBelongTo=target_course,
                fileType=src.fileType,
            )
            copy_template_to_task(src, new_task)
            copy_precheck_to_task(src, new_task)
            copied.append(new_title)
        except models.Task.DoesNotExist:
            errors.append(f'实验 ID={task_id} 不存在')

    return JsonResponse({'success': True, 'copied': copied, 'errors': errors})


@login_required
@require_POST
def preview_task_import(request):
    """AJAX: 接收 Excel 文件 + courseID，解析后返回预览 JSON，数据存 session。"""
    if not is_teacher_or_admin(request.user):
        return JsonResponse({'error': '无权限执行此操作'}, status=403)

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
    if not is_teacher_or_admin(request.user):
        return JsonResponse({'error': '无权限执行此操作'}, status=403)

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


@login_required
def download_template(request, filename):
    """下载导入模板文件"""
    from django.conf import settings
    safe_names = {'课程导入模板.xlsx', '作业导入模板.xlsx'}
    if filename not in safe_names:
        return HttpResponse('模板不存在', status=404)
    filepath = os.path.join(settings.BASE_DIR, 'file', '模板', filename)
    if not os.path.exists(filepath):
        return HttpResponse('模板文件未找到，请联系管理员', status=404)
    with open(filepath, 'rb') as f:
        response = HttpResponse(f.read(), content_type='application/octet-stream')
        response['Content-Disposition'] = 'attachment;filename=' + filename.encode('utf-8').decode('ISO-8859-1')
        return response


def create_student_user():
    from app01.loaduser import load_user_list
    users = load_user_list()
    for u in users:
        user_obj = User.objects.create_user(username=u[0], password='szu' + u[0][-6:])
        models.UserProfile.objects.create(
            name=u[1], gender='M' if u[2] == '男' else 'F', user_id=user_obj.id
        )

# ===== PHASE1_API_AND_IMPERSONATION =====



def _parse_deadline(value):
    if value is None or value == "":
        return None, "deadline 不能为空"
    if isinstance(value, str):
        value = value.strip()
        try:
            return _dt.strptime(value, "%Y-%m-%d").date(), None
        except ValueError:
            return None, "deadline 格式应为 YYYY-MM-DD"
    return value, None


@require_api_key
@csrf_exempt
@require_http_methods(["GET", "PATCH", "PUT"])
def task_settings_api(request, task_id):
    """
    作业设置查询/修改（需 API Key）。
    GET：返回作业基本信息
    PATCH/PUT：可改 deadline、display、title、content、fileType
    """
    task = models.Task.objects.filter(pk=task_id).select_related("courseBelongTo").first()
    if not task:
        return JsonResponse({"code": 404, "message": f"未找到作业 id={task_id}", "data": None}, status=404)

    if request.method == "GET":
        course = task.courseBelongTo
        return JsonResponse({
            "code": 0,
            "message": "ok",
            "data": {
                "id": task.id,
                "title": task.title,
                "content": task.content,
                "display": task.display,
                "deadline": task.deadline.isoformat() if task.deadline else None,
                "fileType": task.fileType,
                "has_template": task_has_template_file(task),
                "template_original_name": task.template_original_name or None,
                "template_uploaded_at": task.template_uploaded_at.isoformat() if task.template_uploaded_at else None,
                "enable_template_download": task.enable_template_download,
                "enable_cover_autofill": task.enable_cover_autofill,
                "course": {
                    "id": course.id,
                    "courseTerm": course.courseTerm,
                    "courseName": course.courseName,
                    "classNumber": course.classNumber,
                },
            },
        })

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"code": 400, "message": "请求体须为 JSON", "data": None}, status=400)

    if not isinstance(payload, dict):
        return JsonResponse({"code": 400, "message": "请求体须为 JSON 对象", "data": None}, status=400)

    allowed = {"deadline", "display", "title", "content", "fileType", "enable_template_download", "enable_cover_autofill"}
    unknown = set(payload.keys()) - allowed
    if unknown:
        return JsonResponse({
            "code": 400,
            "message": f"不支持的字段: {', '.join(sorted(unknown))}",
            "data": None,
        }, status=400)

    update_fields = []
    if "deadline" in payload:
        d, err = _parse_deadline(payload["deadline"])
        if err:
            return JsonResponse({"code": 400, "message": err, "data": None}, status=400)
        task.deadline = d
        update_fields.append("deadline")
    if "display" in payload:
        val = payload["display"]
        if not isinstance(val, bool):
            if isinstance(val, str) and val.lower() in ("true", "1", "yes"):
                val = True
            elif isinstance(val, str) and val.lower() in ("false", "0", "no"):
                val = False
            else:
                return JsonResponse({"code": 400, "message": "display 须为布尔值", "data": None}, status=400)
        task.display = val
        update_fields.append("display")
    if "title" in payload:
        title = str(payload["title"] or "").strip()
        if not title:
            return JsonResponse({"code": 400, "message": "title 不能为空", "data": None}, status=400)
        task.title = title[:100]
        update_fields.append("title")
    if "content" in payload:
        task.content = str(payload["content"] if payload["content"] is not None else "")
        update_fields.append("content")
    if "fileType" in payload:
        ft_raw = str(payload["fileType"] or "*")[:50]
        ft_err, ft_ok = validate_file_type_setting(ft_raw)
        if ft_err:
            return JsonResponse({"code": 400, "message": ft_err, "data": None}, status=400)
        task.fileType = ft_ok
        update_fields.append("fileType")

    if "enable_template_download" in payload or "enable_cover_autofill" in payload:
        if not task_has_template_file(task):
            return JsonResponse({"code": 400, "message": "请先上传报告模板后再修改开关", "data": None}, status=400)
    if "enable_template_download" in payload:
        val = payload["enable_template_download"]
        if not isinstance(val, bool):
            return JsonResponse({"code": 400, "message": "enable_template_download 须为布尔值", "data": None}, status=400)
        task.enable_template_download = val
        update_fields.append("enable_template_download")
    if "enable_cover_autofill" in payload:
        val = payload["enable_cover_autofill"]
        if not isinstance(val, bool):
            return JsonResponse({"code": 400, "message": "enable_cover_autofill 须为布尔值", "data": None}, status=400)
        task.enable_cover_autofill = val
        update_fields.append("enable_cover_autofill")

    if not update_fields:
        return JsonResponse({"code": 400, "message": "未提供可更新字段", "data": None}, status=400)

    try:
        task.save(update_fields=update_fields)
    except Exception as e:
        logger.exception("task_settings_api save failed")
        return JsonResponse({"code": 500, "message": str(e), "data": None}, status=500)

    return JsonResponse({
        "code": 0,
        "message": "updated",
        "data": {
            "id": task.id,
            "title": task.title,
            "display": task.display,
            "deadline": task.deadline.isoformat() if task.deadline else None,
            "fileType": task.fileType,
            "updated_fields": update_fields,
        },
    })


@login_required
@require_GET
def impersonate_search(request):
    """超管搜索可切换用户（姓名/学号），可选 course_id 过滤。"""
    if not impersonation_helpers.can_start_impersonation(request):
        return JsonResponse({"code": 403, "message": "无权搜索（需超级管理员且未在模拟中）", "data": None}, status=403)

    q = (request.GET.get("q") or "").strip()
    course_id = (request.GET.get("course_id") or "").strip()
    role = (request.GET.get("role") or "").strip().upper()  # S / T / 空

    qs = User.objects.filter(is_active=True, is_superuser=False).select_related("profile")
    if course_id.isdigit():
        qs = qs.filter(profile__course_set__id=int(course_id)).distinct()
    if role in ("S", "T"):
        qs = qs.filter(profile__type=role)
    if q:
        qs = qs.filter(
            Q(username__icontains=q) | Q(profile__name__icontains=q)
        )

    users = list(qs.order_by("username")[:30])
    data = []
    for u in users:
        try:
            pname = u.profile.name
            ptype = u.profile.type
        except Exception:
            pname, ptype = u.username, "?"
        data.append({
            "id": u.id,
            "username": u.username,
            "name": pname,
            "type": ptype,
        })

    recent_ids = request.session.get(impersonation_helpers.SESSION_RECENT) or []
    recent = []
    if recent_ids:
        recent_map = {
            u.id: u for u in User.objects.filter(pk__in=recent_ids, is_superuser=False)
            .select_related("profile")
        }
        for rid in recent_ids:
            u = recent_map.get(int(rid))
            if not u:
                continue
            try:
                pname, ptype = u.profile.name, u.profile.type
            except Exception:
                pname, ptype = u.username, "?"
            recent.append({"id": u.id, "username": u.username, "name": pname, "type": ptype})

    courses = list(
        models.Course.objects.order_by("-courseTerm", "courseName", "classNumber")
        .values("id", "courseTerm", "courseName", "classNumber")[:200]
    )
    return JsonResponse({
        "code": 0,
        "message": "ok",
        "data": {"users": data, "recent": recent, "courses": courses},
    })


@login_required
@require_POST
def impersonate_start(request):
    if not impersonation_helpers.can_start_impersonation(request):
        return JsonResponse({"code": 403, "message": "无权切换身份", "data": None}, status=403)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        payload = {}
    user_id = payload.get("user_id") or request.POST.get("user_id")
    if not user_id:
        return JsonResponse({"code": 400, "message": "缺少 user_id", "data": None}, status=400)
    target = User.objects.filter(pk=user_id).first()
    if not target:
        return JsonResponse({"code": 404, "message": "用户不存在", "data": None}, status=404)
    ok, msg = impersonation_helpers.start_impersonation(request, target)
    if not ok:
        return JsonResponse({"code": 400, "message": msg, "data": None}, status=400)
    try:
        ptype = target.profile.type
    except Exception:
        ptype = 'S'
    redirect_url = '/studentCourseList/' if ptype == 'S' else '/teacherCourseList/'
    return JsonResponse({
        "code": 0,
        "message": "ok",
        "data": {
            "id": target.id,
            "username": target.username,
            "name": getattr(getattr(target, "profile", None), "name", target.username),
            "type": ptype,
            "redirect_url": redirect_url,
        },
    })


@login_required
@require_POST
def impersonate_stop(request):
    ok, msg = impersonation_helpers.stop_impersonation(request)
    if not ok:
        return JsonResponse({"code": 400, "message": msg, "data": None}, status=400)
    return JsonResponse({"code": 0, "message": "ok", "data": None})


@login_required
@require_POST
def save_homework_grades_batch(request):
    """教师批量保存定性批改。"""
    if not is_teacher_or_admin(request.user):
        return JsonResponse({'code': 403, 'message': '无权批改', 'data': None}, status=403)
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'code': 400, 'message': '请求体须为 JSON', 'data': None}, status=400)
    items = payload.get('items') or []
    if not isinstance(items, list) or not items:
        return JsonResponse({'code': 400, 'message': 'items 不能为空', 'data': None}, status=400)

    saved = []
    errors = []
    for item in items:
        if not isinstance(item, dict):
            errors.append({'homework_id': None, 'message': '条目格式错误'})
            continue
        hw_id = item.get('homework_id')
        letter = (item.get('letter_grade') or '').strip()
        if not hw_id:
            errors.append({'homework_id': hw_id, 'message': '缺少 homework_id'})
            continue
        if not letter:
            continue  # 未选等级则跳过
        homework = models.Homework.objects.filter(pk=hw_id).first()
        if not homework:
            errors.append({'homework_id': hw_id, 'message': '提交记录不存在'})
            continue
        score = item['score'] if 'score' in item else SCORE_UNSET
        try:
            grade, _ = upsert_grade(
                homework, letter, item.get('comment'), request.user, score=score,
            )
            saved.append({'homework_id': hw_id, 'grade': serialize_grade(grade, for_student=False)})
        except ValueError as e:
            errors.append({'homework_id': hw_id, 'message': str(e)})

    return JsonResponse({
        'code': 0 if not errors else (0 if saved else 400),
        'message': f'已保存 {len(saved)} 条' + (f'，失败 {len(errors)} 条' if errors else ''),
        'data': {'saved_count': len(saved), 'saved': saved, 'errors': errors},
    }, status=200 if saved or not errors else 400)


@login_required
def task_grade_summary(request, taskID):
    """作业定性成绩汇总页。"""
    if not is_teacher_or_admin(request.user):
        return HttpResponse('您没有权限进行该操作！')
    task = get_object_or_404(Task, pk=taskID)
    course = task.courseBelongTo
    summary = build_grade_summary(task)
    return render(request, 'gradeSummary.html', {
        'name': get_display_name(request.user),
        'course': course,
        'task': task,
        'summary': summary,
        'letter_choices': LETTER_CHOICES,
    })


@login_required
def task_grade_summary_export(request, taskID):
    """导出成绩汇总 Excel。"""
    if not is_teacher_or_admin(request.user):
        return HttpResponse('您没有权限进行该操作！')
    import openpyxl
    from openpyxl.styles import Font
    from io import BytesIO

    task = get_object_or_404(Task, pk=taskID)
    course = task.courseBelongTo
    summary = build_grade_summary(task)

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = '汇总'
    ws1.append(['课程', course.courseName])
    ws1.append(['班号', course.classNumber])
    ws1.append(['作业', task.title])
    ws1.append([])
    ws1.append(['应交', summary['expected']])
    ws1.append(['已提交', summary['submitted']])
    ws1.append(['已批改', summary['graded']])
    ws1.append(['未批改', summary['ungraded']])
    ws1.append(['不合格F', summary['fail_count']])
    ws1.append(['待重评', summary['needs_regrade_count']])
    ws1.append([])
    ws1.append(['等级', '人数', f'占比%(分母=应交{summary["expected"]})'])
    for d in summary['distribution']:
        ws1.append([d['letter'], d['count'], d['percent']])
    if summary.get('ungraded'):
        ws1.append(['未批改', summary['ungraded'], round(100.0 * summary['ungraded'] / summary['expected'], 1) if summary['expected'] else 0])
    if summary.get('not_submitted'):
        ws1.append(['未提交', summary['not_submitted'], round(100.0 * summary['not_submitted'] / summary['expected'], 1) if summary['expected'] else 0])

    ws2 = wb.create_sheet('明细')
    ws2.append(['学号', '姓名', '等级', '参考分', '评语', '待重评'])
    for d in summary['distribution']:
        for s in d['students']:
            score = s.get('score')
            ws2.append([
                s['number'], s['name'], s['letter_grade'],
                '' if score is None else score,
                s.get('comment') or '',
                '是' if s.get('needs_regrade') else '',
            ])
    for s in summary['ungraded_list']:
        ws2.append([s['number'], s['name'], '未批改', '', '', ''])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    filename = f'成绩汇总_{safe_filename(task.title)}.xlsx'
    resp = HttpResponse(
        bio.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    resp['Content-Disposition'] = 'attachment; filename=' + filename.encode('utf-8').decode('ISO-8859-1')
    return resp


# ===== PHASE1_GRADE_API =====

@login_required
@require_POST
def save_homework_grade(request):
    """教师定性批改保存（页面 AJAX）。"""
    if not is_teacher_or_admin(request.user):
        return JsonResponse({'code': 403, 'message': '无权批改', 'data': None}, status=403)
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        payload = {
            'homework_id': request.POST.get('homework_id'),
            'letter_grade': request.POST.get('letter_grade'),
            'comment': request.POST.get('comment'),
        }
        if 'score' in request.POST:
            payload['score'] = request.POST.get('score')
    hw_id = payload.get('homework_id')
    if not hw_id:
        return JsonResponse({'code': 400, 'message': '缺少 homework_id', 'data': None}, status=400)
    homework = models.Homework.objects.select_related('task', 'task__courseBelongTo').filter(pk=hw_id).first()
    if not homework:
        return JsonResponse({'code': 404, 'message': '提交记录不存在', 'data': None}, status=404)
    score = payload['score'] if 'score' in payload else SCORE_UNSET
    try:
        grade, created = upsert_grade(
            homework,
            payload.get('letter_grade'),
            payload.get('comment'),
            request.user,
            score=score,
        )
    except ValueError as e:
        return JsonResponse({'code': 400, 'message': str(e), 'data': None}, status=400)

    return JsonResponse({
        'code': 0,
        'message': 'ok',
        'data': serialize_grade(grade, for_student=False),
    })


def _find_homework_for_api(task, student_number=None, homework_id=None):
    if homework_id:
        return models.Homework.objects.filter(pk=homework_id, task=task).select_related('user', 'user__user').first()
    if student_number:
        return models.Homework.objects.filter(
            task=task, user__user__username=str(student_number).strip()
        ).select_related('user', 'user__user').first()
    return None


@require_api_key
@csrf_exempt
@require_http_methods(['GET'])

@require_api_key
@csrf_exempt
@require_http_methods(["POST", "DELETE"])


@require_api_key
@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
def task_precheck_api(request, task_id):
    """
    作业框架预检规则包（需 API Key）。
    GET：返回模式/规则包元数据与内容
    PUT：JSON body 写入规则包，可选 version；也可带 precheck_mode / precheck_fail_mode
    DELETE：清空规则包（不自动改模式）
    """
    task = models.Task.objects.filter(pk=task_id).select_related("courseBelongTo").first()
    if not task:
        return JsonResponse({"code": 404, "message": f"未找到作业 id={task_id}", "data": None}, status=404)

    if request.method == "GET":
        plan = resolve_precheck_plan(task)
        return JsonResponse({
            "code": 0,
            "message": "ok",
            "data": {
                "task_id": task.id,
                "precheck_mode": task.precheck_mode,
                "precheck_fail_mode": task.precheck_fail_mode,
                "package_version": task.precheck_package_version or None,
                "package_updated_at": task.precheck_package_updated_at.isoformat() if task.precheck_package_updated_at else None,
                "package": json.loads(task.precheck_package_json) if (task.precheck_package_json or "").strip() else None,
                "effective": {
                    "do_cover": plan.do_cover,
                    "do_framework": plan.do_framework,
                    "fail_mode": plan.fail_mode,
                    "skip_reason": plan.skip_reason,
                },
                "course": {
                    "precheck_master": task.courseBelongTo.precheck_master,
                    "precheck_cover_mode": task.courseBelongTo.precheck_cover_mode,
                },
            },
        })

    if request.method == "DELETE":
        task.precheck_package_json = ""
        task.precheck_package_version = ""
        task.precheck_package_updated_at = None
        task.save(update_fields=["precheck_package_json", "precheck_package_version", "precheck_package_updated_at"])
        return JsonResponse({"code": 0, "message": "ok", "data": {"cleared": True}})

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"code": 400, "message": "请求体须为 JSON", "data": None}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"code": 400, "message": "请求体须为 JSON 对象", "data": None}, status=400)

    update_fields = []
    if "precheck_mode" in payload:
        mode = str(payload["precheck_mode"] or "").strip()
        allowed_modes = {c[0] for c in models.Task.PRECHECK_MODE_CHOICES}
        if mode not in allowed_modes:
            return JsonResponse({"code": 400, "message": f"precheck_mode 无效", "data": None}, status=400)
        task.precheck_mode = mode
        update_fields.append("precheck_mode")
    if "precheck_fail_mode" in payload:
        fm = str(payload["precheck_fail_mode"] or "").strip()
        allowed_fm = {c[0] for c in models.Task.PRECHECK_FAIL_CHOICES}
        if fm not in allowed_fm:
            return JsonResponse({"code": 400, "message": "precheck_fail_mode 无效", "data": None}, status=400)
        task.precheck_fail_mode = fm
        update_fields.append("precheck_fail_mode")

    if "package" in payload:
        pkg = payload["package"]
        if pkg is None:
            task.precheck_package_json = ""
            task.precheck_package_version = ""
            task.precheck_package_updated_at = None
            update_fields.extend(["precheck_package_json", "precheck_package_version", "precheck_package_updated_at"])
        else:
            raw = json.dumps(pkg, ensure_ascii=False) if isinstance(pkg, dict) else str(pkg)
            err, parsed = validate_precheck_package(raw if isinstance(pkg, dict) else raw)
            if err:
                return JsonResponse({"code": 400, "message": err, "data": None}, status=400)
            task.precheck_package_json = json.dumps(parsed, ensure_ascii=False)
            task.precheck_package_version = str(payload.get("version") or parsed.get("version") or "")[:64]
            task.precheck_package_updated_at = timezone.now()
            update_fields.extend(["precheck_package_json", "precheck_package_version", "precheck_package_updated_at"])

    if not update_fields:
        return JsonResponse({"code": 400, "message": "无有效字段（package / precheck_mode / precheck_fail_mode）", "data": None}, status=400)
    task.save(update_fields=list(dict.fromkeys(update_fields)))
    plan = resolve_precheck_plan(task)
    return JsonResponse({
        "code": 0,
        "message": "ok",
        "data": {
            "precheck_mode": task.precheck_mode,
            "precheck_fail_mode": task.precheck_fail_mode,
            "package_version": task.precheck_package_version or None,
            "effective": {
                "do_cover": plan.do_cover,
                "do_framework": plan.do_framework,
                "fail_mode": plan.fail_mode,
                "skip_reason": plan.skip_reason,
            },
        },
    })

def task_template_api(request, task_id):
    """
    作业报告模板上传/删除（需 API Key）。
    POST multipart: file=<docx>
    DELETE: 删除模板并关闭开关
    """
    task = models.Task.objects.filter(pk=task_id).select_related("courseBelongTo").first()
    if not task:
        return JsonResponse({"code": 404, "message": f"未找到作业 id={task_id}", "data": None}, status=404)

    if request.method == "DELETE":
        clear_task_template_files(task)
        task.template_path = ""
        task.template_original_name = ""
        task.template_uploaded_at = None
        task.enable_template_download = False
        task.enable_cover_autofill = False
        task.save(update_fields=[
            "template_path", "template_original_name", "template_uploaded_at",
            "enable_template_download", "enable_cover_autofill",
        ])
        return JsonResponse({"code": 0, "message": "ok", "data": {"has_template": False}})

    f = request.FILES.get("file")
    if not f:
        return JsonResponse({"code": 400, "message": "请上传 file 字段（.docx）", "data": None}, status=400)
    err, _ = save_uploaded_template(task, f)
    if err:
        return JsonResponse({"code": 400, "message": err, "data": None}, status=400)
    task.refresh_from_db()
    return JsonResponse({
        "code": 0,
        "message": "ok",
        "data": {
            "has_template": True,
            "template_original_name": task.template_original_name,
            "template_uploaded_at": task.template_uploaded_at.isoformat() if task.template_uploaded_at else None,
            "enable_template_download": task.enable_template_download,
            "enable_cover_autofill": task.enable_cover_autofill,
        },
    })


def task_grades_api(request, task_id):
    """某作业全部定性成绩（需 API Key）。"""
    task = models.Task.objects.filter(pk=task_id).first()
    if not task:
        return JsonResponse({'code': 404, 'message': f'未找到作业 id={task_id}', 'data': None}, status=404)
    homeworks = models.Homework.objects.filter(task=task).select_related('user', 'user__user', 'grade')
    rows = []
    for hw in homeworks:
        try:
            g = hw.grade
        except HomeworkGrade.DoesNotExist:
            g = None
        rows.append({
            'homework_id': hw.id,
            'student_number': hw.user.user.username,
            'student_name': hw.user.name,
            'grade': serialize_grade(g, for_student=False),
        })
    return JsonResponse({'code': 0, 'message': 'ok', 'data': {'task_id': task.id, 'grades': rows}})


@require_api_key
@csrf_exempt
@require_http_methods(['GET', 'PUT', 'PATCH'])
def homework_grade_api(request, homework_id):
    """单条提交的定性成绩读写（需 API Key）。"""
    homework = models.Homework.objects.select_related('user', 'user__user', 'task').filter(pk=homework_id).first()
    if not homework:
        return JsonResponse({'code': 404, 'message': f'未找到提交 id={homework_id}', 'data': None}, status=404)

    if request.method == 'GET':
        try:
            g = homework.grade
        except HomeworkGrade.DoesNotExist:
            g = None
        return JsonResponse({
            'code': 0,
            'message': 'ok',
            'data': {
                'homework_id': homework.id,
                'student_number': homework.user.user.username,
                'task_id': homework.task_id,
                'grade': serialize_grade(g, for_student=False),
            },
        })

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'code': 400, 'message': '请求体须为 JSON', 'data': None}, status=400)
    if 'letter_grade' not in payload:
        return JsonResponse({'code': 400, 'message': '缺少 letter_grade', 'data': None}, status=400)
    # API 无登录用户：graded_by 置空
    score = payload['score'] if 'score' in payload else SCORE_UNSET
    try:
        grade, _ = upsert_grade(
            homework, payload.get('letter_grade'), payload.get('comment'), None, score=score,
        )
    except ValueError as e:
        return JsonResponse({'code': 400, 'message': str(e), 'data': None}, status=400)
    return JsonResponse({
        'code': 0,
        'message': 'updated',
        'data': serialize_grade(grade, for_student=False),
    })


@require_api_key
@csrf_exempt
@require_http_methods(['PUT', 'PATCH'])
def task_student_grade_api(request, task_id, student_number):
    """按作业 + 学号写入定性成绩（需 API Key）。"""
    task = models.Task.objects.filter(pk=task_id).first()
    if not task:
        return JsonResponse({'code': 404, 'message': f'未找到作业 id={task_id}', 'data': None}, status=404)
    homework = _find_homework_for_api(task, student_number=student_number)
    if not homework:
        return JsonResponse({
            'code': 404,
            'message': f'未找到该学生的提交记录：{student_number}',
            'data': None,
        }, status=404)
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'code': 400, 'message': '请求体须为 JSON', 'data': None}, status=400)
    if 'letter_grade' not in payload:
        return JsonResponse({'code': 400, 'message': '缺少 letter_grade', 'data': None}, status=400)
    score = payload['score'] if 'score' in payload else SCORE_UNSET
    try:
        grade, _ = upsert_grade(
            homework, payload.get('letter_grade'), payload.get('comment'), None, score=score,
        )
    except ValueError as e:
        return JsonResponse({'code': 400, 'message': str(e), 'data': None}, status=400)
    return JsonResponse({
        'code': 0,
        'message': 'updated',
        'data': {
            'homework_id': homework.id,
            'student_number': student_number,
            'grade': serialize_grade(grade, for_student=False),
        },
    })


@require_api_key
@csrf_exempt
@require_http_methods(['GET'])
def task_grades_summary_api(request, task_id):
    """作业定性成绩汇总（需 API Key）。"""
    task = models.Task.objects.filter(pk=task_id).first()
    if not task:
        return JsonResponse({'code': 404, 'message': f'未找到作业 id={task_id}', 'data': None}, status=404)
    summary = build_grade_summary(task)
    return JsonResponse({'code': 0, 'message': 'ok', 'data': {'task_id': task.id, 'summary': summary}})
