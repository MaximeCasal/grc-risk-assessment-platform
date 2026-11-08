from django.db import migrations, models


def close_campaigns_with_conclusions(apps, schema_editor):
    Campaign = apps.get_model("assessments", "Campaign")
    Campaign.objects.filter(conclusions__isnull=False).distinct().update(status="CLOSED")


class Migration(migrations.Migration):
    dependencies = [("assessments", "0007_userrole_job_title")]

    operations = [
        migrations.AlterField(
            model_name="campaign",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Brouillon"),
                    ("ACTIVE", "Active"),
                    ("CLOSED", "Terminée"),
                ],
                default="ACTIVE",
                max_length=12,
            ),
        ),
        migrations.RunPython(close_campaigns_with_conclusions, migrations.RunPython.noop),
    ]
