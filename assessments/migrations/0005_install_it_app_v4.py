import json
from pathlib import Path

from django.db import migrations


def install_it_app_v4(apps, schema_editor):
    QuestionnaireTemplate = apps.get_model("assessments", "QuestionnaireTemplate")
    Category = apps.get_model("assessments", "Category")
    Section = apps.get_model("assessments", "Section")
    Question = apps.get_model("assessments", "Question")
    Choice = apps.get_model("assessments", "Choice")

    if QuestionnaireTemplate.objects.filter(code="ISRA-IT-APP-V4").exists():
        return
    registry_path = Path(__file__).resolve().parent.parent / "data" / "isra_it_application_v4.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    category_rows = [
        ("Socle commun", "socle", True),
        ("Service applicatif exploité par un éditeur", "saas", False),
        ("Solution sous maîtrise technique de l’entreprise", "maitrise", False),
    ]
    categories = {}
    for name, slug, common in category_rows:
        category, _created = Category.objects.get_or_create(
            questionnaire_type="IT_APP",
            slug=slug,
            defaults={"name": name, "is_common": common},
        )
        categories[name] = category

    template = QuestionnaireTemplate.objects.create(
        code="ISRA-IT-APP-V4",
        title="Questionnaire ISRA IT Application V4 — Faiblesses des contrôles",
        questionnaire_type="IT_APP",
        source_version="V4",
    )
    section_titles = {
        question["section_order"]: question["section_title"]
        for question in registry["questions"]
    }
    sections = {
        order: Section.objects.create(template=template, order=order, title=title)
        for order, title in sorted(section_titles.items())
    }
    for data in registry["questions"]:
        question = Question.objects.create(
            section=sections[data["section_order"]],
            reference=data["reference"],
            order=data["order"],
            text=data["text"],
            help_text=data["help_text"],
            response_type=data["response_type"],
            required=data["required"],
            metric="control" if data["role"] == "W" else "context",
        )
        question.categories.add(categories[data["category"]])
        for index, option in enumerate(data["options"]):
            Choice.objects.create(
                question=question,
                value=option["id"],
                label=option["label"],
                score=option["score"],
                special=option["special"],
                exclusive=option["exclusive"],
                order=index,
            )


class Migration(migrations.Migration):
    dependencies = [("assessments", "0004_itapplicationscoresnapshot")]

    operations = [migrations.RunPython(install_it_app_v4, migrations.RunPython.noop)]
