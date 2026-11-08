from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from assessments.models import Category, QuestionnaireTemplate
from assessments.questionnaire_import import load_bo_v4_questionnaire


class Command(BaseCommand):
    help = "Installe ou synchronise l’unique questionnaire Business Owner actif : BO V4."

    @transaction.atomic
    def handle(self, *args, **kwargs):
        if not Category.objects.filter(questionnaire_type=QuestionnaireTemplate.BO).exists():
            raise CommandError("Les catégories BO sont absentes.")
        count = load_bo_v4_questionnaire()
        self.stdout.write(self.style.SUCCESS(
            f"Questionnaire BO V4 installé ou synchronisé ({count} questions)."
        ))
