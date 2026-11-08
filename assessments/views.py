from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max, OuterRef, Subquery
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .forms import AssignmentForm, CampaignForm, ConclusionForm, ScenarioForm
from .models import (Answer, Application, Assignment, Campaign, Category, HelpRequest,
                     Question, QuestionnaireTemplate, RiskConclusion, RiskScenario)
from .services import (applicable_questions, build_export, calculate_results, is_analyst,
                       persist_bo_snapshot, persist_it_app_snapshot)


def home(request):
    return render(request, "assessments/home.html", {"applications": Application.objects.all()[:10]})


def _latest_closed_campaign_id(application_id):
    return (
        Campaign.objects.filter(application_id=application_id, status=Campaign.CLOSED)
        .annotate(last_conclusion_at=Max("conclusions__created_at"))
        .order_by("-last_conclusion_at", "-created_at", "-pk")
        .values_list("pk", flat=True)
        .first()
    )


def _campaign_can_be_modified(campaign):
    return campaign.status != Campaign.CLOSED or (
        campaign.pk == _latest_closed_campaign_id(campaign.application_id)
    )


def _campaign_can_receive_conclusion(campaign):
    return campaign.status == Campaign.ACTIVE or (
        campaign.status == Campaign.CLOSED
        and campaign.pk == _latest_closed_campaign_id(campaign.application_id)
    )


# Presentation-only summaries used by the analyst tables.
def _attach_assignment_summaries(assignments):
    dimensions = (("C", "Confidentialité"), ("I", "Intégrité"), ("D", "Disponibilité"))
    for assignment in assignments:
        assignment.bo_summary = None
        assignment.it_summary = None
        if assignment.status != Assignment.SUBMITTED:
            continue
        if (
            assignment.template.questionnaire_type == QuestionnaireTemplate.BO
            and assignment.template.source_version == "V4"
        ):
            indicators = calculate_results(assignment)["bo"]["indicators"]
            rows = []
            for dimension, label in dimensions:
                protection = indicators[f"B_{dimension}"]
                impact = indicators[f"M_{dimension}"]
                for item in (protection, impact):
                    item["color_level"] = (
                        "na" if item["value"] is None
                        else str(max(0, min(5, int(float(item["value"]) + 0.5))))
                    )
                rows.append({"label": label, "protection": protection, "impact": impact})
            assignment.bo_summary = {"rows": rows}
        elif (
            assignment.template.questionnaire_type == QuestionnaireTemplate.IT_APP
            and assignment.template.source_version == "V4"
        ):
            families = []
            for code, family in calculate_results(assignment)["it_app"]["families"].items():
                value = family["value"]
                family["color_level"] = (
                    "na" if value is None
                    else str(max(0, min(5, int(float(value) + 0.5))))
                )
                families.append({"code": code, **family})
            assignment.it_summary = {"families": families}
    return assignments


@login_required
def dashboard(request):
    analyst = is_analyst(request.user)
    if analyst:
        latest_conclusion = RiskConclusion.objects.filter(
            campaign__application=OuterRef("pk"), is_validated=True
        ).order_by("-created_at", "-pk")
        applications = list(
            Application.objects.prefetch_related("campaigns").annotate(
                latest_risk_level=Subquery(latest_conclusion.values("level")[:1])
            )
        )
        risk_labels = dict(RiskConclusion.LEVELS)
        for application in applications:
            application.latest_risk_label = risk_labels.get(
                application.latest_risk_level, "Non évaluée"
            )
        assignments = list(
            Assignment.objects.select_related("template", "respondent", "campaign__application")
        )
        _attach_assignment_summaries(assignments)
        return render(request, "assessments/dashboard.html", {
            "analyst": True, "applications": applications,
            "assignments": assignments,
            "help_requests": HelpRequest.objects.filter(resolved=False).select_related("assignment__template", "question", "author"),
            "templates": QuestionnaireTemplate.objects.prefetch_related("sections__questions"),
        })
    return render(request, "assessments/dashboard.html", {
        "analyst": False,
        "assignments": request.user.questionnaires.select_related("template", "campaign__application"),
    })


@login_required
def application_detail(request, pk):
    app = get_object_or_404(Application.objects.prefetch_related("campaigns__conclusions"), pk=pk)
    if not is_analyst(request.user): raise PermissionDenied
    latest = RiskConclusion.objects.filter(
        campaign__application=app, is_validated=True
    ).order_by("-created_at", "-pk").first()
    return render(request, "assessments/application_detail.html", {"app": app, "latest": latest})


@login_required
def campaign_create(request, application_id):
    if not is_analyst(request.user): raise PermissionDenied
    application = get_object_or_404(Application, pk=application_id)
    form = CampaignForm(request.POST or None, initial={"title": f"ISRA {application.name} {timezone.localdate().year}"})
    if request.method == "POST" and form.is_valid():
        campaign = form.save(commit=False)
        campaign.application = application
        campaign.created_by = request.user
        campaign.save()
        messages.success(request, "Évaluation ISRA créée. Vous pouvez maintenant attribuer les questionnaires.")
        return redirect("campaign_detail", pk=campaign.pk)
    return render(request, "assessments/form.html", {"form": form, "title": f"Nouvelle évaluation — {application.name}"})


@login_required
def campaign_edit(request, pk):
    if not is_analyst(request.user): raise PermissionDenied
    campaign = get_object_or_404(Campaign, pk=pk)
    if not _campaign_can_be_modified(campaign):
        raise PermissionDenied("Seule la dernière campagne terminée peut être modifiée.")
    form = CampaignForm(request.POST or None, instance=campaign)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Évaluation mise à jour.")
        return redirect("campaign_detail", pk=campaign.pk)
    return render(request, "assessments/form.html", {"form": form, "title": f"Modifier l’évaluation — {campaign.application.name}"})


@login_required
def campaign_detail(request, pk):
    campaign = get_object_or_404(Campaign.objects.select_related("application"), pk=pk)
    if not is_analyst(request.user): raise PermissionDenied
    assignments = list(campaign.assignments.select_related("template", "respondent", "campaign__application"))
    _attach_assignment_summaries(assignments)
    return render(request, "assessments/campaign_detail.html", {
        "campaign": campaign,
        "assignments": assignments,
        "can_modify_campaign": _campaign_can_be_modified(campaign),
        "can_assign": campaign.status == Campaign.ACTIVE,
        "can_conclude": _campaign_can_receive_conclusion(campaign),
    })


@login_required
def campaign_assign(request, pk):
    if not is_analyst(request.user): raise PermissionDenied
    campaign = get_object_or_404(Campaign, pk=pk)
    if campaign.status != Campaign.ACTIVE:
        raise PermissionDenied("Une campagne terminée ne peut plus recevoir de questionnaire.")
    form = AssignmentForm(request.POST or None, campaign=campaign)
    if request.method == "POST" and form.is_valid():
        assignment = form.save()
        messages.success(request, f"{assignment.template.title} attribué à {assignment.respondent.get_full_name() or assignment.respondent.username}.")
        return redirect("campaign_detail", pk=campaign.pk)
    return render(request, "assessments/form.html", {"form": form, "title": f"Attribuer un questionnaire — {campaign.application.name}"})


def _owner_assignment(user, pk):
    assignment = get_object_or_404(Assignment.objects.select_related("template", "respondent"), pk=pk)
    if assignment.respondent_id != user.id: raise PermissionDenied
    return assignment


@login_required
@transaction.atomic
def questionnaire(request, pk):
    assignment = _owner_assignment(request.user, pk)
    if assignment.status == Assignment.SUBMITTED:
        messages.info(request, "Ce questionnaire a déjà été soumis à l’analyste GRC. Les résultats lui sont réservés.")
        return redirect("dashboard")
    categories = Category.objects.filter(questionnaire_type=assignment.template.questionnaire_type, is_common=False)
    if request.method == "POST":
        action = request.POST.get("action", "save")
        before_ids = {q.id for q in applicable_questions(assignment)}
        if "categories_present" in request.POST:
            chosen = categories.filter(id__in=request.POST.getlist("categories"))
            assignment.selected_categories.set(chosen)
        applicable = applicable_questions(assignment)
        app_ids = {q.id for q in applicable}
        excluded_answered = assignment.answers.filter(question_id__in=before_ids - app_ids).count()
        if excluded_answered:
            messages.warning(request, f"{excluded_answered} réponse(s) sont désormais hors périmètre. Elles restent dans le brouillon et seront supprimées lors de la soumission si la catégorie n’est pas réactivée.")
        previous_seen = set(assignment.seen_question_ids)
        assignment.added_question_ids = list(dict.fromkeys(assignment.added_question_ids + [q.id for q in applicable if q.id not in previous_seen]))
        assignment.seen_question_ids = list(previous_seen | app_ids)
        assignment.last_section = max(1, int(request.POST.get("last_section", assignment.last_section)))
        for q in applicable:
            key = f"q_{q.id}"
            if key not in request.POST and q.response_type != Question.MULTIPLE: continue
            values = request.POST.getlist(key)
            if q.response_type == Question.TEXT: values = [request.POST.get(key, "").strip()]
            if q.response_type == Question.MULTIPLE:
                selected = list(q.choices.filter(value__in=values))
                exclusive = [c for c in selected if c.exclusive]
                if exclusive and len(selected) > 1:
                    messages.error(request, f"{q.reference} : l’option « {exclusive[0].label} » est exclusive.")
                    return redirect("questionnaire", pk=pk)
            Answer.objects.update_or_create(assignment=assignment, question=q, defaults={"value": values, "comment": request.POST.get(f"comment_{q.id}", ""), "is_final": False})
        assignment.status = Assignment.IN_PROGRESS
        if action == "submit":
            applicable = applicable_questions(assignment)
            answer_map = {a.question_id: a for a in assignment.answers.filter(question_id__in=[q.id for q in applicable])}
            helped_ids = set(assignment.help_requests.filter(question_id__in=[q.id for q in applicable]).values_list("question_id", flat=True))
            missing = [q.reference for q in applicable if (q.id not in answer_map or not any(str(v).strip() for v in answer_map[q.id].value)) and q.id not in helped_ids]
            unjustified_na = []
            if (
                assignment.template.questionnaire_type == QuestionnaireTemplate.IT_APP
                and assignment.template.source_version == "V4"
            ):
                for q in applicable:
                    answer = answer_map.get(q.id)
                    if not answer or answer.comment.strip():
                        continue
                    if q.choices.filter(value__in=answer.value, special="NA").exists():
                        unjustified_na.append(q.reference)
            if missing:
                messages.error(request, "Soumission impossible. Réponses requises manquantes : " + ", ".join(missing))
            elif unjustified_na:
                messages.error(request, "Soumission impossible. Une justification est requise pour les réponses Non applicable : " + ", ".join(unjustified_na))
            else:
                for q in applicable:
                    if q.id in helped_ids and (q.id not in answer_map or not any(str(v).strip() for v in answer_map[q.id].value)):
                        answer, _created = Answer.objects.get_or_create(assignment=assignment, question=q, defaults={"value": []})
                        if not answer.comment:
                            answer.comment = "Question validée par une demande d’aide, sans réponse sélectionnée."
                            answer.save(update_fields=["comment"])
                assignment.answers.exclude(question_id__in=[q.id for q in applicable]).delete()
                assignment.answers.filter(question_id__in=[q.id for q in applicable]).update(is_final=True)
                assignment.status = Assignment.SUBMITTED; assignment.submitted_at = timezone.now()
                assignment.save()
                persist_bo_snapshot(assignment)
                persist_it_app_snapshot(assignment)
                messages.success(request, "Questionnaire soumis à l’analyste GRC. Les réponses sont maintenant verrouillées.")
                return redirect("dashboard")
        assignment.save()
        messages.success(request, "Brouillon enregistré.")
        return redirect("questionnaire", pk=pk)
    applicable = applicable_questions(assignment)
    if assignment.status == Assignment.NOT_STARTED:
        assignment.seen_question_ids = [q.id for q in applicable]; assignment.save(update_fields=["seen_question_ids"])
    answer_map = {a.question_id: a for a in assignment.answers.all()}
    grouped = []
    added_ids = set(assignment.added_question_ids)
    for section in assignment.template.sections.all():
        questions = [q for q in applicable if q.section_id == section.id and q.id not in added_ids]
        if questions: grouped.append((section, questions))
    added = [q for q in applicable if q.id in added_ids]
    helped_ids = set(assignment.help_requests.values_list("question_id", flat=True))
    return render(request, "assessments/questionnaire.html", {"assignment": assignment, "categories": categories,
        "selected_ids": set(assignment.selected_categories.values_list("id", flat=True)), "grouped": grouped,
        "added": added, "answer_map": answer_map, "applicable": applicable, "helped_ids": helped_ids})


@login_required
def results(request, pk):
    if not is_analyst(request.user): raise PermissionDenied("Les résultats sont réservés à l’analyste GRC.")
    assignment = get_object_or_404(Assignment.objects.select_related("template", "respondent", "campaign__application"), pk=pk)
    if assignment.status != Assignment.SUBMITTED: raise PermissionDenied("Les brouillons sont confidentiels jusqu’à la soumission.")
    return render(request, "assessments/results.html", {"assignment": assignment, "results": calculate_results(assignment)})


@login_required
def export_xlsx(request, pk):
    if not is_analyst(request.user): raise PermissionDenied("Les exports sont réservés à l’analyste GRC.")
    assignment = get_object_or_404(Assignment, pk=pk)
    if assignment.status != Assignment.SUBMITTED: raise PermissionDenied
    response = HttpResponse(build_export(assignment), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="orivane-{assignment.pk}.xlsx"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_POST
def request_help(request, pk, question_id):
    assignment = _owner_assignment(request.user, pk)
    if assignment.status == Assignment.SUBMITTED: raise PermissionDenied
    question = get_object_or_404(Question, pk=question_id, section__template=assignment.template)
    comment = request.POST.get("comment", "").strip() or "Demande d’aide sans commentaire."
    help_request = HelpRequest.objects.filter(assignment=assignment, question=question, author=request.user).order_by("-created_at").first()
    if help_request:
        help_request.comment = comment
        help_request.resolved = False
        help_request.save(update_fields=["comment", "resolved"])
    else:
        HelpRequest.objects.create(assignment=assignment, question=question, author=request.user, comment=comment)
    if assignment.status == Assignment.NOT_STARTED:
        assignment.status = Assignment.IN_PROGRESS
        assignment.save(update_fields=["status"])
    messages.success(request, "Demande d’aide transmise à l’analyste.")
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "question_id": question.id})
    return redirect("questionnaire", pk=pk)


@login_required
def scenario_create(request, pk):
    if not is_analyst(request.user): raise PermissionDenied
    campaign = get_object_or_404(Campaign, pk=pk)
    if not _campaign_can_be_modified(campaign):
        raise PermissionDenied("Seule la dernière campagne terminée peut être modifiée.")
    form = ScenarioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False); obj.campaign = campaign; obj.created_by = request.user; obj.save()
        return redirect("campaign_detail", pk=campaign.pk)
    return render(request, "assessments/form.html", {"form": form, "title": "Scénario de risque"})


@login_required
def scenario_edit(request, pk):
    if not is_analyst(request.user): raise PermissionDenied
    scenario = get_object_or_404(RiskScenario.objects.select_related("campaign"), pk=pk)
    if not _campaign_can_be_modified(scenario.campaign):
        raise PermissionDenied("Seule la dernière campagne terminée peut être modifiée.")
    form = ScenarioForm(request.POST or None, instance=scenario)
    if request.method == "POST" and form.is_valid():
        form.save(); return redirect("campaign_detail", pk=scenario.campaign_id)
    return render(request, "assessments/form.html", {"form": form, "title": "Scénario de risque"})


@login_required
@require_POST
def scenario_delete(request, pk):
    if not is_analyst(request.user): raise PermissionDenied
    scenario = get_object_or_404(RiskScenario.objects.select_related("campaign"), pk=pk)
    if not _campaign_can_be_modified(scenario.campaign):
        raise PermissionDenied("Seule la dernière campagne terminée peut être modifiée.")
    campaign_id = scenario.campaign_id; scenario.delete()
    return redirect("campaign_detail", pk=campaign_id)


@login_required
@transaction.atomic
def conclusion_create(request, pk):
    if not is_analyst(request.user): raise PermissionDenied
    campaign = get_object_or_404(Campaign.objects.select_for_update(), pk=pk)
    if not _campaign_can_receive_conclusion(campaign):
        raise PermissionDenied("Seule la dernière campagne terminée peut recevoir une appréciation révisée.")
    form = ConclusionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False); obj.campaign = campaign; obj.author = request.user; obj.save()
        if campaign.status != Campaign.CLOSED:
            campaign.status = Campaign.CLOSED
            campaign.save(update_fields=["status"])
        messages.success(request, "Appréciation enregistrée. La campagne est maintenant terminée.")
        return redirect("application_detail", pk=campaign.application_id)
    title = "Réviser l’appréciation globale" if campaign.status == Campaign.CLOSED else "Appréciation globale manuelle"
    return render(request, "assessments/form.html", {"form": form, "title": title})
