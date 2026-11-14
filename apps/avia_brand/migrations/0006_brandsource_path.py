"""One repository may hold several brands, each in its own folder."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("avia_brand", "0005_calendarconnection_creation_started_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="brandsource",
            name="path",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AlterField(
            model_name="brandsource",
            name="repository",
            field=models.CharField(max_length=100),
        ),
        migrations.AddConstraint(
            model_name="brandsource",
            constraint=models.UniqueConstraint(fields=("repository", "path"), name="avia_source_repository_path"),
        ),
    ]
