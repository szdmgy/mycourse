from django.db import migrations, models
import django.db.models.deletion


def forwards_copy_time(apps, schema_editor):
    Homework = apps.get_model('app01', 'Homework')
    for hw in Homework.objects.all().iterator():
        old = getattr(hw, 'time', None)
        if old is None:
            continue
        # During AddField stage time still exists on DB until RemoveField
        Homework.objects.filter(pk=hw.pk).update(submitted_at=old, updated_at=old)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('app01', '0004_reference_material_sort_order'),
    ]

    operations = [
        migrations.AddField(
            model_name='homework',
            name='submitted_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='首次提交时间'),
        ),
        migrations.AddField(
            model_name='homework',
            name='updated_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='最后更新时间'),
        ),
        migrations.RunPython(forwards_copy_time, noop_reverse),
        migrations.RemoveField(
            model_name='homework',
            name='time',
        ),
        migrations.CreateModel(
            name='ImpersonationLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('start', '开始切换'), ('stop', '结束切换')], max_length=10, verbose_name='动作')),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True, verbose_name='IP')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='时间')),
                ('impersonator', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='impersonation_actions', to='auth.user', verbose_name='真实操作者')),
                ('target_user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='impersonated_as', to='auth.user', verbose_name='模拟身份')),
            ],
            options={
                'verbose_name': '身份切换审计',
                'ordering': ['-created_at'],
            },
        ),
    ]
