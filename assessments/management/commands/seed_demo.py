from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from assessments.models import (
    Answer, Application, Assignment, Campaign, Category, Choice, HelpRequest,
    Question, QuestionnaireTemplate, RiskConclusion, RiskScenario,
    Section, UserRole,
)
from assessments.questionnaire_import import load_questionnaires
from assessments.reference_data import APPLICATIONS


class Command(BaseCommand):
    help = "Initialise le référentiel Orivane et les questionnaires, dont BO V4, sans données d’évaluation."

    @transaction.atomic
    def handle(self, *args, **kwargs):
        for model in [
            Answer, HelpRequest, RiskConclusion, RiskScenario, Assignment, Campaign,
            Choice, Question, Section, QuestionnaireTemplate, Category, Application,
        ]:
            model.objects.all().delete()

        accounts = [
            ("demo_dsi", "Claire", "Moreau", "DSI", UserRole.ANALYST),
            ("demo_rssi", "Thomas", "Perrin", "RSSI", UserRole.ANALYST),
            ("demo_grc", "Julie", "Bernard", "Analyste sécurité et conformité", UserRole.ANALYST),
            ("demo_it_app", "Nicolas", "Garnier", "Responsable applications métier", UserRole.IT_APP),
            ("demo_infra", "Sophie", "Lambert", "Responsable infrastructure", UserRole.IT_APP),
            ("demo_bo", "Élodie", "Martin", "Directrice financière", UserRole.BO),
            ("demo_ops", "Karim", "Benali", "Directeur des opérations", UserRole.BO),
            ("demo_commercial", "Antoine", "Lefèvre", "Directeur commercial", UserRole.BO),
            ("demo_rh", "Camille", "Dubois", "Responsable RH", UserRole.BO),
            ("demo_qualite", "Marc", "Delmas", "Responsable qualité et traçabilité", UserRole.BO),
        ]
        account_usernames = {account[0] for account in accounts}
        User.objects.filter(username__startswith="demo_").exclude(
            username__in=account_usernames
        ).delete()

        for username, first, last, job_title, role in accounts:
            email = f"{username}@orivane.example"
            user, _created = User.objects.update_or_create(
                username=username,
                defaults={"first_name": first, "last_name": last, "email": email},
            )
            user.set_password("OrivaneDemo!2026")
            user.save(update_fields=["password"])
            UserRole.objects.filter(user=user).exclude(role=role).delete()
            UserRole.objects.update_or_create(
                user=user, role=role, defaults={"job_title": job_title}
            )

        for row in APPLICATIONS:
            Application.objects.create(
                code=row[0], name=row[1], domain=row[2], business_owner_name=row[3],
                description=row[4], functions=row[5], users=row[6], data=row[7], relations=row[8],
            )

        counts = load_questionnaires()
        self.stdout.write(self.style.SUCCESS(
            "Référentiel initialisé sans campagne, attribution, réponse ni historique. "
            f"Questionnaires importés : BO V4 {counts[QuestionnaireTemplate.BO]}, "
            f"IT Application {counts[QuestionnaireTemplate.IT_APP]}. "
            "Mot de passe commun : OrivaneDemo!2026"
        ))
