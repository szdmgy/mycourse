from django.contrib import admin
from app01.models import UserProfile
from app01.models import Task
from app01.models import Homework
from app01.models import Course
from django.http import HttpResponse
import csv
# Register your models here.
# admin.site.register(UserProfile)
@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user','name','gender','type','phone','email']
    list_filter = ['type']
    search_fields = ['name','phone']
# admin.site.register(Task)
@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['courseBelongTo','title','content','uploadFileType','display','deadline']
    list_filter = ['courseBelongTo']
    # search_fields = ['name','phone']
# admin.site.register(Homework)

def export_as_csv(modeladmin, request, queryset):
    """自定义导出 CSV 的 Action"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="home_work_export.csv"'

    # 定义 CSV 表头（根据模型字段调整）
    writer = csv.writer(response)
    writer.writerow(['学生姓名', '作业标题', '提交时间'])  # 替换为实际字段名

    # 遍历查询集，写入数据
    for obj in queryset:
        writer.writerow([obj.user, obj.task, obj.time])  # 替换为实际字段值

    return response
export_as_csv.short_description = "导出选中数据为 CSV"  # 动作名称显示
@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = ['user','task','time']
    list_filter = ['user','task']
    actions = [export_as_csv]  # 注册导出动作
# admin.site.register(Course)
@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['id','courseTerm','courseNumber','courseName','classNumber','teachers','status']
    list_filter = ['courseTerm','courseName']
    # search_fields = ['name','phone']