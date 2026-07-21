# Generated manually for optional reference score on HomeworkGrade

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app01', '0010_homework_precheck_warn'),
    ]

    operations = [
        migrations.AddField(
            model_name='homeworkgrade',
            name='score',
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text='可选，0–100 整数；仅教师可见，不参与不合格判定',
                null=True,
                verbose_name='参考分',
            ),
        ),
    ]
