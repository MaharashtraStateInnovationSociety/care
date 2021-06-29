# Generated by Django 2.2.11 on 2021-06-29 16:49

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('facility', '0259_auto_20210622_0208'),
    ]

    operations = [
        migrations.AlterField(
            model_name='patientexternaltest',
            name='icmr_id',
            field=models.CharField(blank=True, max_length=255, null=True, unique=True),
        ),
        migrations.CreateModel(
            name='PatientExternalTestUploadHistory',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('external_id', models.UUIDField(db_index=True, default=uuid.uuid4, unique=True)),
                ('created_date', models.DateTimeField(auto_now_add=True, db_index=True, null=True)),
                ('modified_date', models.DateTimeField(auto_now=True, db_index=True, null=True)),
                ('deleted', models.BooleanField(db_index=True, default=False)),
                ('file_name', models.CharField(blank=True, max_length=255, null=True)),
                ('most_recent_date_of_sample_tested_in_file', models.DateTimeField(blank=True, null=True)),
                ('hash', models.CharField(blank=True, max_length=1023, null=True)),
                ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
