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

    # 课程默认报告模板（全课共用一份；作业可再上传专用模板覆盖）
    report_template_path = models.CharField('课程默认报告模板路径', max_length=500, blank=True, default='')
    report_template_original_name = models.CharField('课程默认模板文件名', max_length=255, blank=True, default='')
    report_template_uploaded_at = models.DateTimeField('课程默认模板上传时间', null=True, blank=True)
    enable_report_template_download = models.BooleanField('课程默认：允许下载模板', default=False)
    enable_report_cover_autofill = models.BooleanField('课程默认：自动填封面', default=False)

    # 预检总开关：off=关闭；cover_default=默认封面预检（仅对有模板的作业生效）
    PRECHECK_MASTER_OFF = 'off'
    PRECHECK_MASTER_COVER = 'cover_default'
    PRECHECK_MASTER_CHOICES = (
        (PRECHECK_MASTER_OFF, '关闭预检'),
        (PRECHECK_MASTER_COVER, '默认开启封面预检'),
    )
    precheck_master = models.CharField(
        '预检总开关', max_length=20, choices=PRECHECK_MASTER_CHOICES, default=PRECHECK_MASTER_OFF,
    )
    PRECHECK_FAIL_BLOCK = 'block'
    PRECHECK_FAIL_WARN = 'warn'
    PRECHECK_FAIL_CHOICES = (
        (PRECHECK_FAIL_BLOCK, '硬拦截'),
        (PRECHECK_FAIL_WARN, '仅警告'),
    )
    precheck_cover_mode = models.CharField(
        '默认封面预检失败策略', max_length=10, choices=PRECHECK_FAIL_CHOICES, default=PRECHECK_FAIL_BLOCK,
    )

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

    fileType = models.CharField('允许的文件类型', max_length=50, default='*',
                                help_text='如 .docx,.pdf,.zip 或 * 表示不限')

    # 报告模板（作业级完整 .docx；与参考资料目录分离）
    template_path = models.CharField('报告模板路径', max_length=500, blank=True, default='',
                                     help_text='相对 BASE_DIR，目录为 file/.../报告模板/<作业标题>/')
    template_original_name = models.CharField('模板原始文件名', max_length=255, blank=True, default='')
    template_uploaded_at = models.DateTimeField('模板上传时间', null=True, blank=True)
    enable_template_download = models.BooleanField('允许学生下载模板', default=False)
    enable_cover_autofill = models.BooleanField('下载时自动填封面', default=False)

    # 预检：inherit=跟随课程；off=关闭；cover/framework/cover_and_framework=作业专用
    PRECHECK_INHERIT = 'inherit'
    PRECHECK_OFF = 'off'
    PRECHECK_COVER = 'cover'
    PRECHECK_FRAMEWORK = 'framework'
    PRECHECK_BOTH = 'cover_and_framework'
    PRECHECK_MODE_CHOICES = (
        (PRECHECK_INHERIT, '继承课程'),
        (PRECHECK_OFF, '关闭预检'),
        (PRECHECK_COVER, '仅封面预检'),
        (PRECHECK_FRAMEWORK, '仅框架预检'),
        (PRECHECK_BOTH, '封面+框架预检'),
    )
    precheck_mode = models.CharField(
        '预检模式', max_length=32, choices=PRECHECK_MODE_CHOICES, default=PRECHECK_INHERIT,
    )
    PRECHECK_FAIL_INHERIT = 'inherit'
    PRECHECK_FAIL_BLOCK = 'block'
    PRECHECK_FAIL_WARN = 'warn'
    PRECHECK_FAIL_CHOICES = (
        (PRECHECK_FAIL_INHERIT, '继承课程'),
        (PRECHECK_FAIL_BLOCK, '硬拦截'),
        (PRECHECK_FAIL_WARN, '仅警告'),
    )
    precheck_fail_mode = models.CharField(
        '预检失败策略', max_length=10, choices=PRECHECK_FAIL_CHOICES, default=PRECHECK_FAIL_INHERIT,
    )
    precheck_package_json = models.TextField('框架预检规则JSON', blank=True, default='')
    precheck_package_version = models.CharField('框架预检包版本', max_length=64, blank=True, default='')
    precheck_package_updated_at = models.DateTimeField('框架预检包更新时间', null=True, blank=True)

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
    submitted_at = models.DateTimeField('首次提交时间', null=True, blank=True)
    updated_at = models.DateTimeField('最后更新时间', null=True, blank=True)
    # 仅警告模式下确认后仍提交：保留警告直至下次预检通过
    precheck_warn_active = models.BooleanField('预检警告中', default=False)
    precheck_warn_text = models.TextField('预检警告内容', blank=True, default='')
    precheck_warned_at = models.DateTimeField('预检警告时间', null=True, blank=True)

    class Meta:
        verbose_name = "提交记录"

    def __str__(self):
        return f'{self.user} - {self.task}'

    @property
    def is_late(self):
        """逾期按首次提交日期相对作业截止日期判定。"""
        if not self.submitted_at or not self.task_id:
            return False
        return self.submitted_at.date() > self.task.deadline




class HomeworkGrade(models.Model):
    """定性批改结果（只存库，不写回报告文件）。"""

    GRADE_A_PLUS = 'A+'
    GRADE_A = 'A'
    GRADE_B = 'B'
    GRADE_C = 'C'
    GRADE_D = 'D'
    GRADE_F = 'F'
    LETTER_CHOICES = (
        (GRADE_A_PLUS, 'A+'),
        (GRADE_A, 'A'),
        (GRADE_B, 'B'),
        (GRADE_C, 'C'),
        (GRADE_D, 'D'),
        (GRADE_F, 'F（不合格）'),
    )
    VALID_LETTERS = {c[0] for c in LETTER_CHOICES}

    homework = models.OneToOneField(
        Homework, on_delete=models.CASCADE, related_name='grade', verbose_name='提交记录'
    )
    letter_grade = models.CharField('等级', max_length=2, choices=LETTER_CHOICES)
    score = models.PositiveSmallIntegerField(
        '参考分', null=True, blank=True,
        help_text='可选，0–100 整数；仅教师可见，不参与不合格判定',
    )
    comment = models.TextField('评语', blank=True, default='')
    graded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='grades_given', verbose_name='批改人',
    )
    graded_at = models.DateTimeField('首次批改时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    needs_regrade = models.BooleanField(
        '待重评', default=False,
        help_text='学生在不合格(F)后重新提交时置 True，教师再次保存等级后清除',
    )

    class Meta:
        verbose_name = '定性成绩'

    def __str__(self):
        return f'{self.homework_id}: {self.letter_grade}'

    @property
    def is_fail(self):
        return self.letter_grade == self.GRADE_F

    def visible_to_student(self):
        """当前规则：仅 F 对学生可见。"""
        return self.is_fail


class ImpersonationLog(models.Model):
    """超级管理员切换用户身份的审计记录。"""

    ACTION_START = 'start'
    ACTION_STOP = 'stop'
    ACTION_CHOICES = (
        (ACTION_START, '开始切换'),
        (ACTION_STOP, '结束切换'),
    )

    impersonator = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='impersonation_actions',
        verbose_name='真实操作者',
    )
    target_user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='impersonated_as',
        verbose_name='模拟身份',
    )
    action = models.CharField('动作', max_length=10, choices=ACTION_CHOICES)
    ip_address = models.GenericIPAddressField('IP', null=True, blank=True)
    created_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '身份切换审计'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.impersonator_id}->{self.target_user_id} {self.action}'


class HomeworkFile(models.Model):
    homework = models.OneToOneField(Homework, on_delete=models.CASCADE, related_name='file')
    filePath = models.CharField('文件路径', max_length=255, default='')
    originalName = models.CharField('原始文件名', max_length=200, default='')

    class Meta:
        verbose_name = "提交文件"

    @property
    def standardName(self):
        """返回标准化文件名（从 filePath 提取）"""
        import os
        return os.path.basename(self.filePath) if self.filePath else self.originalName

    @property
    def absPath(self):
        """返回绝对路径（filePath 存的是相对于 BASE_DIR 的路径）"""
        import os
        if os.path.isabs(self.filePath):
            return self.filePath
        from django.conf import settings
        return os.path.join(settings.BASE_DIR, self.filePath)

    def __str__(self):
        return f'{self.homework}: {self.originalName}'


class ReferenceMaterial(models.Model):
    """课程参考资料（存放在 file/<学期>/<课程名+班号>/参考资料/ 下）"""

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name='reference_materials', verbose_name='所属课程'
    )
    title = models.CharField('标题', max_length=200)
    description = models.TextField('说明', blank=True, default='')
    filePath = models.CharField('文件路径', max_length=500, default='')
    originalName = models.CharField('原始文件名', max_length=200, default='')
    file_size = models.BigIntegerField('文件大小(字节)', default=0)
    sort_order = models.IntegerField(
        '排序',
        default=0,
        help_text='数字越小越靠前；教师端可用上移/下移调整',
    )
    display = models.BooleanField('对学生显示', default=True)
    uploaded_by = models.ForeignKey(
        UserProfile, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='上传者'
    )
    created_at = models.DateTimeField('上传时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '参考资料'
        ordering = ['sort_order', '-created_at', 'id']

    @property
    def abs_path(self):
        import os
        from django.conf import settings
        if os.path.isabs(self.filePath):
            return self.filePath
        return os.path.join(settings.BASE_DIR, self.filePath)

    def size_display(self):
        from app01.utils import format_file_size
        return format_file_size(self.file_size)

    def __str__(self):
        return f'{self.course_id}: {self.title}'




