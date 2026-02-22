from django.contrib import admin
from django.http import HttpResponse
import csv
from app01.models import UserProfile, Task, Homework, HomeworkFile, Course


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'name', 'gender', 'type', 'phone', 'email']
    list_filter = ['type']
    search_fields = ['name', 'phone']


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['courseBelongTo', 'title', 'maxFiles', 'slot1Name', 'slot1Type', 'display', 'deadline']
    list_filter = ['courseBelongTo']
    search_fields = ['title']


def export_as_csv(modeladmin, request, queryset):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="homework_export.csv"'
    writer = csv.writer(response)
    writer.writerow(['学生姓名', '作业标题', '提交时间'])
    for obj in queryset:
        writer.writerow([obj.user, obj.task, obj.time])
    return response

export_as_csv.short_description = "导出选中数据为 CSV"


@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = ['user', 'task', 'time']
    list_filter = ['task']
    actions = [export_as_csv]


class HomeworkFileInline(admin.TabularInline):
    model = HomeworkFile
    extra = 0


@admin.register(HomeworkFile)
class HomeworkFileAdmin(admin.ModelAdmin):
    list_display = ['homework', 'slot', 'originalName', 'filePath']
    list_filter = ['slot']


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['id', 'courseTerm', 'courseNumber', 'courseName', 'classNumber', 'teachers', 'status']
    list_filter = ['courseTerm', 'courseName']
