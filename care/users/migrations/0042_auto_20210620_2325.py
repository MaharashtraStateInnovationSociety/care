# Generated by Django 2.2.11 on 2021-06-20 17:55

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0041_auto_20210609_1356'),
    ]

    operations = [
        migrations.AlterField(
            model_name='district',
            name='state',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='districts', to='users.State'),
        ),
    ]
