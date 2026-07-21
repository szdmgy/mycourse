"""
URL configuration for mycourse project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, re_path
from app01 import views

from django.views import static ##新增
from django.conf import settings ##新增
from app01 import importcourse


urlpatterns = [
    # API：学生作业提交状态（供考勤成绩计算等外部调用；暂不强制鉴权，见 docs）
    path('api/v1/submission-status/', views.submission_status_api),
    path('api/v1/tasks/<int:task_id>/', views.task_settings_api),
    path('api/v1/tasks/<int:task_id>/template/', views.task_template_api),
    path('api/v1/tasks/<int:task_id>/precheck/', views.task_precheck_api),
    path('api/v1/tasks/<int:task_id>/grades/', views.task_grades_api),
    path('api/v1/tasks/<int:task_id>/grades/summary/', views.task_grades_summary_api),
    path('api/v1/tasks/<int:task_id>/grades/<str:student_number>/', views.task_student_grade_api),
    path('api/v1/homeworks/<int:homework_id>/grade/', views.homework_grade_api),
    # 超级管理员身份切换
    path('impersonate/search/', views.impersonate_search, name='impersonate_search'),
    path('impersonate/start/', views.impersonate_start, name='impersonate_start'),
    path('impersonate/stop/', views.impersonate_stop, name='impersonate_stop'),
    # 用户loading
    path('admin/', admin.site.urls),
    path('login/', views.log_in),
    path('logout/',views.log_out,name='logout'),
    path('user/', views.user),
    path('user/profile/', views.profile_edit,name='profile_edit'),
    path('user/password/', views.change_password, name='change_password'),
    # 学生端操作
    path('taskSubmit/<int:taskID>/', views.taskSubmit, name='taskSubmit'),
    path('studentCourse/<str:courseTerm>/<str:courseName>/<str:classNumber>/', views.studentCourse, name='studentCourse'),
    path('studentTasks/<str:courseTerm>/<str:courseName>/<str:classNumber>/', views.studentGetTaskByCoursename, name='studentGetTask'),
    path('studentCourseList/', views.studentCourseList, name='studentCourseList'),
    path('upload_file', views.post_file, name='upload_file'),
    path('download-file',views.download_file,name='download_file'),
    #管理员操作
    path('manager/', views.manager, name='manager'),
    path('manager/user/', views.user_list, name='user_list'),
    path('manager/removeuser/<str:username>/', views.remove_user, name='removeUser'),

    path('manager/import/', views.import_data, name='import_data'),
    path('preview-import/', views.preview_import, name='preview_import'),
    path('confirm-import/', views.confirm_import, name='confirm_import'),
    path('preview-task-import/', views.preview_task_import, name='preview_task_import'),
    path('confirm-task-import/', views.confirm_task_import, name='confirm_task_import'),
    path('addMemberByManager/', views.addMemberByManager, name='addMemberByManager'),
    path('deleteMemberByManager/<str:memberNumber>/', views.deleteMemberByManager, name='deleteMemberByManager'),
    # 老师端操作
    path('delayRecords/<int:courseID>/',views.delayRecords,name='delayRecords'),
    path('homeworkRecords/<int:taskID>/', views.homeworkRecords, name='homeworkRecords'),
    path('resetPassword/',views.resetPassword,name='resetPassword'),
    path('taskChange/<int:taskID>/', views.taskChange, name='taskChange'),
    path('course/<int:courseID>/precheck/settings/', views.update_course_precheck_settings, name='updateCoursePrecheckSettings'),
    path('course/<int:courseID>/template/upload/', views.upload_course_report_template, name='uploadCourseTemplate'),
    path('course/<int:courseID>/template/delete/', views.delete_course_report_template, name='deleteCourseTemplate'),
    path('course/<int:courseID>/template/settings/', views.update_course_template_settings, name='updateCourseTemplateSettings'),
    path('course/<int:courseID>/template/master/', views.download_course_report_template_master, name='downloadCourseTemplateMaster'),
    path('task/<int:taskID>/template/upload/', views.upload_task_report_template, name='uploadTaskTemplate'),
    path('task/<int:taskID>/template/delete/', views.delete_task_report_template, name='deleteTaskTemplate'),
    path('task/<int:taskID>/template/settings/', views.update_task_template_settings, name='updateTaskTemplateSettings'),
    path('task/<int:taskID>/template/master/', views.download_task_report_template_master, name='downloadTaskTemplateMaster'),
    path('task/<int:taskID>/template/download/', views.download_task_report_template_student, name='downloadTaskTemplate'),
    path('teacherCourseList/', views.teacherCourseList, name='teacherCourseList'),
    path('teachercourse/<str:courseTerm>/<str:courseName>/<str:classNumber>/', views.teacher_course_change, name='teacherCourseChange'),
    path('teacherTasks/<str:courseTerm>/<str:courseName>/<str:classNumber>/', views.teacherGetTaskByCoursename, name='teacherGetTask'),
    path('download_homework_ByTeacher/',views.teacherDownloadByHomeworknameAndStudentnumber, name='download_homework_ByTeacher'),
    path('addHomework/',views.addHomework, name='addHomework'),
    path('addCourse/', views.addCourse, name='addCourse'),
    path('copyTasks/', views.copyTasks, name='copyTasks'),
    path('getHistoryTasks/<int:courseID>/', views.getHistoryTasks, name='getHistoryTasks'),
    path('getHistoryRefMaterials/<int:courseID>/', views.get_history_reference_materials, name='getHistoryRefMaterials'),
    path('copyRefMaterials/', views.copy_reference_materials, name='copyRefMaterials'),
    path('ref-material/save/', views.ref_material_save, name='ref_material_save'),
    path('ref-material/delete/', views.ref_material_delete, name='ref_material_delete'),
    path('ref-material/reorder/', views.ref_material_reorder, name='ref_material_reorder'),
    path('download-ref-material/<int:material_id>/', views.download_ref_material, name='download_ref_material'),
    path('download-homework-file/<int:file_id>/', views.download_homework_file, name='download_homework_file'),
    path('preview-homework-file/<int:file_id>/', views.preview_homework_file, name='preview_homework_file'),
    path('save-homework-grade/', views.save_homework_grade, name='save_homework_grade'),
    path('save-homework-grades-batch/', views.save_homework_grades_batch, name='save_homework_grades_batch'),
    path('gradeSummary/<int:taskID>/', views.task_grade_summary, name='gradeSummary'),
    path('gradeSummary/<int:taskID>/export/', views.task_grade_summary_export, name='gradeSummaryExport'),
    path('deleteTaskByTeacher/<str:taskId>/', views.deleteTaskByTeacher, name='deleteTaskByTeacher'),
    path('removeStudent/<int:courseID>/<str:studentNumber>/', views.removeStudent, name='removeStudent'),
    path('addStudentToCourseByTeacher/', views.addStudentToCourseByTeacher, name='addStudentToCourseByTeacher'),
    path('downloadStudentListTemplate/', views.downloadStudentListTemplate, name='downloadStudentListTemplate'),
    path('deleteCourse/<str:courseNumber>/<str:courseName>/', views.deleteCourse, name='deleteCourse'),
    path('download-template/<str:filename>/', views.download_template, name='download_template'),
    #静态资源导入
    re_path(r'^static/(?P<path>.*)$', static.serve,
        {'document_root': settings.STATIC_ROOT}, name='static'),
]