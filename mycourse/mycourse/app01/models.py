from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import RegexValidator
import re
from datetime import date
from datetime import timedelta

# 中国手机号正则（11位，1开头）
CHINA_PHONE_REGEX = re.compile(r'^1[3-9]\d{9}$')

class UserProfile(models.Model):
    # django自带用户，一对一关系
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')

    name = models.CharField('姓名', max_length=20, blank=False,default='未知')

    GENDER_CHOICES = (
        (u'M', u'男'),
        (u'F', u'女'),
    )
    gender = models.CharField('姓别', max_length=2, choices=GENDER_CHOICES, default='M')

    TYPE_CHOICES = (
        (u'T', u'老师'),
        (u'S', u'学生'),
    )
    type = models.CharField('类型', max_length=2, choices=TYPE_CHOICES, default='S')

    email = models.EmailField(
        '邮箱',
        max_length=254,  # 符合 RFC 规范的最大长度（254字符）
        unique=False,  # 唯一约束（可选，根据业务需求）
        blank=True,
        default='user@szu.edu.cn',
        error_messages={
            # 'unique': '该邮箱已被注册',
            'invalid': '邮箱格式错误'
        }
    )
    phone = models.CharField(
        '手机号',
        max_length=11,  # 中国手机号固定11位
        # unique=False,  # 唯一约束（可选，根据业务需求）
        blank=True,
        default='13000000000',
        validators=[
            RegexValidator(
                regex=CHINA_PHONE_REGEX,
                message='手机号格式错误，需为11位数字（如13812345678）'
            ),

        ],
    )

    # type = models.
    class Meta:
        verbose_name = '教学用户'

    def __str__(self):
        return self.name



class Course(models.Model):
    # 课程学期
    courseTerm = models.CharField(max_length=30, null=False, unique=False, default='2025-2026学年第一学期')
    # 课程编号
    courseNumber = models.CharField(max_length=30, null=False, unique=False, default='000000')
    # 课程名
    courseName = models.CharField(max_length=30, null=False, unique=False, default='未命名课程')
    # 班级编号
    classNumber = models.CharField(max_length=2, null=False, unique=False, default='01')
    # 课程老师
    teachers =  models.CharField(max_length=30, null=False, unique=False, default='未命名老师')
    # 课程学生
    members = models.ManyToManyField(UserProfile)
    # 开设状态选择
    OPEN_CHOICES = (
        (u'Y', u'开启'),
        (u'N', u'关闭'),
    )
    # 开设状态
    status = models.CharField('开设状态', max_length=10, choices=OPEN_CHOICES, default=u'Y')

    class Meta:
        verbose_name = "课程"

        # 方式 2：Django 3.2+ 推荐（更灵活）
        constraints = [
            models.UniqueConstraint(
                fields=['courseTerm', 'courseNumber','classNumber'],  # 联合字段
                name='unique_term_number'  # 约束名（必填）
            )
        ]

    def __str__(self):
        return self.courseTerm + self.courseName + self.classNumber



def default_deadline():
    return timezone.now() + timezone.timedelta(days=130)

class Task(models.Model):
    title = models.CharField('标题', max_length=100, null=False, unique=False, default='未命名作业')
    content = models.TextField('内容', default='请修改作业正文~')
    display = models.BooleanField('是否显示', default=True, help_text='勾选表示显示作业')
    courseBelongTo = models.ForeignKey(Course, on_delete=models.CASCADE, verbose_name='所属课程')
    deadline = models.DateField('截止日期', default=default_deadline)

    maxFiles = models.IntegerField('最大附件数', default=1,
                                   help_text='允许上传的附件数量（1~3）')
    slot1Name = models.CharField('附件1名称', max_length=50, default='实验报告')
    slot1Type = models.CharField('附件1类型', max_length=50, default='*',
                                 help_text='允许的文件类型，如 .docx,.pdf 或 * 表示不限')
    slot2Name = models.CharField('附件2名称', max_length=50, blank=True, default='')
    slot2Type = models.CharField('附件2类型', max_length=50, blank=True, default='*')
    slot3Name = models.CharField('附件3名称', max_length=50, blank=True, default='')
    slot3Type = models.CharField('附件3类型', max_length=50, blank=True, default='*')

    class Meta:
        verbose_name = "作业"
        constraints = [
            models.UniqueConstraint(
                fields=['courseBelongTo', 'title'],
                name='unique_course_title'
            )
        ]

    def __str__(self):
        return self.title


class Homework(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, default='')
    task = models.ForeignKey(Task, on_delete=models.CASCADE, default='')
    time = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "提交记录"

    def __str__(self):
        return f'{self.user} - {self.task}'


class HomeworkFile(models.Model):
    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name='files')
    slot = models.IntegerField('附件序号', help_text='对应附件 1/2/3')
    filePath = models.CharField('文件路径', max_length=255, default='')
    originalName = models.CharField('原始文件名', max_length=200, default='')

    class Meta:
        verbose_name = "提交文件"
        constraints = [
            models.UniqueConstraint(
                fields=['homework', 'slot'],
                name='unique_homework_slot'
            )
        ]

    def __str__(self):
        return f'{self.homework} slot{self.slot}: {self.originalName}'




