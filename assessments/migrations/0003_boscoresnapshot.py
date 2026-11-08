import json
from pathlib import Path

from django.db import migrations, models
import django.db.models.deletion


def map_bo_choice_ids(apps, schema_editor):
    QuestionnaireTemplate = apps.get_model("assessments", "QuestionnaireTemplate")
    Question = apps.get_model("assessments", "Question")
    Choice = apps.get_model("assessments", "Choice")
    Answer = apps.get_model("assessments", "Answer")
    template = QuestionnaireTemplate.objects.filter(questionnaire_type="BO").first()
    if not template:
        return
    config_path = Path(__file__).resolve().parents[1] / "data" / "isra_bo_scoring_config_v1.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    configured = {q["source_id"]: q for q in config["questions"]}
    for question in Question.objects.filter(section__template=template):
        reference = configured.get(question.reference)
        if reference is None:
            raise RuntimeError(f"Question BO absente du referentiel : {question.reference}")
        existing = list(Choice.objects.filter(question=question))
        by_label = {}
        for choice in existing:
            by_label.setdefault(choice.label, []).append(choice)
        keep_ids = set()
        value_map = {}
        for option in reference["options"]:
            matches = [choice for choice in by_label.get(option["label"], []) if choice.id not in keep_ids]
            if len(matches) == 1:
                choice = matches[0]
            elif len(existing) == len(reference["options"]):
                choice = existing[option["source_choice_position"] - 1]
                expected_special = "ND" if option["value_type"] == "unknown" else "NA" if option["value_type"] == "not_applicable" else ""
                if choice.id in keep_ids or choice.score != option["score"] or choice.special != expected_special:
                    raise RuntimeError(f"Mapping BO ambigu pour {question.reference} / {option['label']}")
            else:
                raise RuntimeError(f"Mapping BO ambigu pour {question.reference} / {option['label']}")
            keep_ids.add(choice.id)
            value_map[choice.value] = option["id"]
            choice.value = option["id"]
            choice.label = option["label"]
            choice.score = option["score"]
            choice.special = "ND" if option["value_type"] == "unknown" else "NA" if option["value_type"] == "not_applicable" else ""
            choice.order = option["source_choice_position"] - 1
            choice.save(update_fields=["value", "label", "score", "special", "order"])
        extras = [choice for choice in existing if choice.id not in keep_ids]
        if reference["options"]:
            for answer in Answer.objects.filter(question=question):
                unknown = [value for value in answer.value if value not in value_map]
                if unknown:
                    raise RuntimeError(f"Reponse BO impossible a migrer pour {question.reference}: {unknown}")
                answer.value = [value_map[value] for value in answer.value]
                answer.save(update_fields=["value"])
        for dependent in Question.objects.filter(
            section__template=template, condition_question_ref=question.reference
        ):
            dependent.condition_excluded_values = [
                value_map.get(value, value) for value in dependent.condition_excluded_values
            ]
            dependent.save(update_fields=["condition_excluded_values"])
        Choice.objects.filter(id__in=[choice.id for choice in extras]).delete()


class Migration(migrations.Migration):
    dependencies = [("assessments", "0002_question_priority")]

    operations = [
        migrations.CreateModel(
            name="BOScoreSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("model_id", models.CharField(max_length=40)),
                ("model_version", models.CharField(max_length=20)),
                ("active_question_ids", models.JSONField(default=list)),
                ("result", models.JSONField(default=dict)),
                ("calculated_at", models.DateTimeField(auto_now=True)),
                ("assignment", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="bo_score_snapshot", to="assessments.assignment")),
            ],
        ),
        migrations.RunPython(map_bo_choice_ids, migrations.RunPython.noop),
    ]
