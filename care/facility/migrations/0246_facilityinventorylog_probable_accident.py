# Generated by Django 2.2.11 on 2021-05-25 18:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('facility', '0245_auto_20210525_0130'),
    ]

    operations = [
        migrations.AddField(
            model_name='facilityinventorylog',
            name='probable_accident',
            field=models.BooleanField(default=False),
        ),
    ]
