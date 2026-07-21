from django.contrib import admin
from django.http import HttpResponse
import csv
from app01.models import UserProfile, Task, Homework, HomeworkFile, Course, ReferenceMaterial, ImpersonationLog, HomeworkGrade


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'name', 'gender', 'type', 'phone', 'email']
    list_filter = ['type']
    search_fields = ['name', 'phone']


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['courseBelongTo', 'title', 'fileType', 'display', 'deadline', 'enable_template_download', 'enable_cover_autofill']
    list_filter = ['courseBelongTo']
    search_fields = ['title']


def export_as_csv(modeladmin, request, queryset):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="homework_export.csv"'
    writer = csv.writer(response)
    writer.writerow(['学生姓名', '作业标题', '首次提交', '最后更新'])
    for obj in queryset:
        writer.writerow([obj.user, obj.task, obj.submitted_at, obj.updated_at])
    return response

export_as_csv.short_description = "导出选中数据为 CSV"


@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = ['user', 'task', 'submitted_at', 'updated_at']
    list_filter = ['task']
    actions = [export_as_csv]


class HomeworkFileInline(admin.TabularInline):
    model = HomeworkFile
    extra = 0


@admin.register(HomeworkFile)
class HomeworkFileAdmin(admin.ModelAdmin):
    list_display = ['homework', 'originalName', 'filePath']


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['id', 'courseTerm', 'courseNumber', 'courseName', 'classNumber', 'teachers', 'status']
    list_filter = ['courseTerm', 'courseName']


@admin.register(ReferenceMaterial)
class ReferenceMaterialAdmin(admin.ModelAdmin):
    list_display = ['id', 'course', 'title', 'sort_order', 'display', 'file_size', 'created_at']
    list_filter = ['course', 'display']
    search_fields = ['title', 'originalName']


@admin.register(ImpersonationLog)
class ImpersonationLogAdmin(admin.ModelAdmin):
    list_display = ['impersonator', 'target_user', 'action', 'ip_address', 'created_at']
    list_filter = ['action']
    readonly_fields = ['impersonator', 'target_user', 'action', 'ip_address', 'created_at']


@admin.register(HomeworkGrade)
class HomeworkGradeAdmin(admin.ModelAdmin):
    list_display = ['homework', 'letter_grade', 'score', 'needs_regrade', 'graded_by', 'updated_at']
    list_filter = ['letter_grade', 'needs_regrade']
    search_fields = ['homework__user__name', 'homework__user__user__username', 'homework__task__title']
