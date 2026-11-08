from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("assessments", "0006_remove_it_hosting")]

    operations = [
        migrations.AddField(
            model_name="userrole",
            name="job_title",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
