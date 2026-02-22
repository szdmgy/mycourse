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
from django.urls import path,re_path
from app01 import views

from django.views import static ##新增
from django.conf import settings ##新增
from app01 import importcourse


urlpatterns = [
    # 用户loading
    path('admin/', admin.site.urls),
    path('login/', views.log_in),
    path('logout/',views.log_out,name='logout'),
    path('user/', views.user),
    path('user/profile/', views.profile_edit,name='profile_edit'),
    path('user/password/', views.change_password, name='change_password'),
    # 学生端操作
    path('taskSubmit/<int:taskID>/<str:taskTitle>/',views.taskSubmit,name='taskSubmit'),
    path('studentCourse/<str:courseTerm>/<str:courseName>/<str:classNumber>/', views.studentCourse, name='studentCourse'),
    path('studentTasks/<str:courseTerm>/<str:courseName>/<str:classNumber>/', views.studentGetTaskByCoursename, name='studentGetTask'),
    path('studentCourseList/', views.studentCourseList, name='studentCourseList'),
    path('upload_file', views.post_file, name='upload_file'),
    path('download-file',views.download_file,name='download_file'),
    #管理员操作
    path('manager/', views.manager, name='manager'),
    path('upload-files/<str:type>/', views.file_upload_view, name='file_upload'),
    path('process-files/', views.process_files, name='process_files'),
    path('manager/user/', views.user_list, name='user_list'),
    path('manager/removeuser/<str:username>/', views.remove_user, name='removeUser'),

    # path('upload-files/course/', views.file_upload_course, name='file_upload_course'),

    path('manager/import/', views.import_data, name='import_data'),
    path('addMemberByManager/', views.addMemberByManager, name='addMemberByManager'),
    path('deleteMemberByManager/<str:memberNumber>/', views.deleteMemberByManager, name='deleteMemberByManager'),
    # 老师端操作
    # path('exportDelayRecords/', views.exportDelayRecords, name='exportDelayRecords'),
    path('delayRecords/<int:courseID>/',views.delayRecords,name='delayRecords'),
    path('homeworkRecords/<int:taskID>/<str:taskTitle>/',views.homeworkRecords,name='homeworkRecords'),
    path('resetPassword/',views.resetPassword,name='resetPassword'),
    path('taskChange/<int:taskID>/<str:taskTitle>',views.taskChange,name='taskChange'),
    path('teacherCourseList/', views.teacherCourseList, name='teacherCourseList'),
    path('teachercourse/<str:courseTerm>/<str:courseName>/<str:classNumber>/', views.teacher_course_change, name='teacherCourseChange'),
    path('teacherTasks/<str:courseTerm>/<str:courseName>/<str:classNumber>/', views.teacherGetTaskByCoursename, name='teacherGetTask'),
    path('download_homework_ByTeacher/',views.teacherDownloadByHomeworknameAndStudentnumber, name='download_homework_ByTeacher'),
    path('addHomework/',views.addHomework, name='addHomework'),
    path('addCourse/', views.addCourse, name='addCourse'),
    path('changeCourseMsgByTeacher/', views.changeCourseMsgByTeacher, name='changeCourseMsgByTeacher'),
    path('deleteTaskByTeacher/<str:taskId>/', views.deleteTaskByTeacher, name='deleteTaskByTeacher'),
    path('removeStudentFromCourse/<str:courseNumber>/<str:courseName>/<str:studentNumber>/', views.removeStudentFromCourse, name='removeStudentFromCourse'),
    path('removeStudent/<int:courseID>/<str:studentNumber>/', views.removeStudent, name='removeStudent'),
    path('addStudentToCourseByTeacher/', views.addStudentToCourseByTeacher, name='addStudentToCourseByTeacher'),
    path('downloadStudentListTemplate/', views.downloadStudentListTemplate, name='downloadStudentListTemplate'),
    path('deleteCourse/<str:courseNumber>/<str:courseName>/', views.deleteCourse, name='deleteCourse'),
    #静态资源导入
    re_path(r'^static/(?P<path>.*)$', static.serve,
        {'document_root': settings.STATIC_ROOT}, name='static'),
]