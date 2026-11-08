import json
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from assessments.models import Application, Campaign, RiskScenario, UserRole


class Command(BaseCommand):
    help = "Importe ou met à jour le registre des risques StockFlow dans sa campagne ISRA."

    def add_arguments(self, parser):
        parser.add_argument(
            "--campaign-id",
            type=int,
            help="Campagne StockFlow cible. Par défaut, la plus récente est utilisée.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        application = Application.objects.filter(code="APP-002").first()
        if not application:
            raise CommandError("L'application APP-002 — StockFlow est introuvable.")

        campaigns = Campaign.objects.filter(application=application)
        if options["campaign_id"]:
            campaign = campaigns.filter(pk=options["campaign_id"]).first()
            if not campaign:
                raise CommandError("La campagne indiquée n'appartient pas à StockFlow.")
        else:
            campaign = campaigns.order_by("-created_at", "-pk").first()
        if not campaign:
            raise CommandError("StockFlow ne possède aucune campagne ISRA.")

        author = campaign.created_by
        if not author.role_links.filter(role=UserRole.ANALYST).exists():
            author = User.objects.filter(
                role_links__role=UserRole.ANALYST, is_active=True
            ).order_by("pk").first()
        if not author:
            raise CommandError("Aucun analyste actif ne peut être associé aux scénarios.")

        data_path = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "stockflow_risk_scenarios.json"
        )
        scenarios = json.loads(data_path.read_text(encoding="utf-8"))
        created = updated = 0
        for values in scenarios:
            reference = values.pop("reference")
            _scenario, was_created = RiskScenario.objects.update_or_create(
                campaign=campaign,
                reference=reference,
                defaults={**values, "created_by": author},
            )
            created += was_created
            updated += not was_created

        self.stdout.write(
            self.style.SUCCESS(
                f"StockFlow : {created} scénario(s) créé(s), {updated} mis à jour "
                f"dans « {campaign.title} » (campagne {campaign.pk})."
            )
        )
