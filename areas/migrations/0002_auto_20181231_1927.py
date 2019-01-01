# Generated by Django 2.1.2 on 2018-12-31 19:27

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('areas', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='area',
            name='ccodes',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=2), blank=True, null=True, size=None),
        ),
        migrations.AlterField(
            model_name='area',
            name='description',
            field=models.CharField(max_length=2044),
        ),
    ]