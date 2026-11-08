from collections import defaultdict
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from .bo_scoring import score_bo
from .bo_scoring_v4 import score_bo_v4
from .it_app_scoring_v4 import score_it_application_v4
from .models import (Answer, BOScoreSnapshot, ITApplicationScoreSnapshot, Question,
                     QuestionnaireTemplate)


def is_analyst(user):
    return user.is_authenticated and user.role_links.filter(role="ANALYST").exists()


def applicable_questions(assignment):
    category_ids = set(assignment.selected_categories.values_list("id", flat=True))
    questions = assignment.template.sections.prefetch_related("questions__categories", "questions__choices")
    result = []
    active_refs = set()
    answers_by_ref = {a.question.reference: a for a in assignment.answers.all()}
    for section in questions:
        for q in section.questions.all():
            qcats = list(q.categories.all())
            if not any(c.is_common or c.id in category_ids for c in qcats):
                continue
            if q.condition_question_ref:
                if q.condition_question_ref not in active_refs:
                    continue
                dependent = answers_by_ref.get(q.condition_question_ref)
                values = dependent.value if dependent else []
                if not values or any(str(v) in q.condition_excluded_values for v in values):
                    continue
            result.append(q)
            active_refs.add(q.reference)
    return result


def _section_results(assignment, applicable_questions_list, include_drafts=False, calculate_averages=True):
    applicable = {q.id: q for q in applicable_questions_list}
    sections = defaultdict(lambda: {"scores": [], "nd": 0, "na": 0, "answers": []})
    impacts = defaultdict(list)
    for answer in assignment.answers.select_related("question__section").prefetch_related("question__choices"):
        q = applicable.get(answer.question_id)
        if not q or (not include_drafts and not answer.is_final):
            continue
        selected = list(q.choices.filter(value__in=answer.value))
        specials = {c.special for c in selected if c.special}
        scores = [c.score for c in selected if c.score is not None]
        score = max(scores) if scores else None
        row = sections[q.section.title]
        row["answers"].append((q, answer, selected, score))
        row["nd"] += int("ND" in specials)
        row["na"] += int("NA" in specials)
        if score is not None:
            row["scores"].append(score)
            if q.metric.startswith("impact_"):
                impacts[q.metric].append(score)
    for row in sections.values():
        row["average"] = (
            round(sum(row["scores"]) / len(row["scores"]), 2)
            if calculate_averages and row["scores"] else None
        )
    return {"sections": dict(sections), "impacts": {k: max(v) for k, v in impacts.items() if v}}


def calculate_results(assignment, include_drafts=False):
    applicable = applicable_questions(assignment)
    is_it_app_v4 = (
        assignment.template.questionnaire_type == QuestionnaireTemplate.IT_APP
        and assignment.template.source_version == "V4"
    )
    result = _section_results(
        assignment,
        applicable,
        include_drafts=include_drafts,
        calculate_averages=not is_it_app_v4,
    )
    if assignment.template.questionnaire_type == QuestionnaireTemplate.BO:
        active_refs = [question.reference for question in applicable]
        answers = {
            answer.question.reference: answer.value
            for answer in assignment.answers.select_related("question")
            if (include_drafts or answer.is_final) and answer.question.reference in active_refs
        }
        is_v4 = assignment.template.source_version == "V4"
        result["bo"] = score_bo_v4(active_refs, answers) if is_v4 else score_bo(active_refs, answers)
        result["bo"]["is_v4"] = is_v4
        result["bo"]["active_categories"] = ["Socle commun"] + list(
            assignment.selected_categories.order_by("name").values_list("name", flat=True)
        )
        if is_v4:
            for data in result["bo"]["indicators"].values():
                data["position_percent_css"] = (
                    None if data["value"] is None else f"{data['value'] / 5 * 100:.6f}"
                )
                ratio = data["coverage"]["ratio"]
                data["coverage"]["percent"] = None if ratio is None else ratio * 100
            coverage = result["bo"]["quality"]["coverage"]
            result["bo"]["quality"]["coverage_percent"] = None if coverage is None else coverage * 100
            result["bo"]["quality"]["coverage_percent_css"] = None if coverage is None else f"{coverage * 100:.6f}"
        else:
            for data in result["bo"]["dimensions"].values():
                data["position_percent"] = None if data["S"] is None else data["S"] / 5 * 100
                data["position_percent_css"] = None if data["S"] is None else f"{data['S'] / 5 * 100:.6f}"
            coverage = result["bo"]["quality"]["coverage"]
            result["bo"]["quality"]["coverage_percent"] = None if coverage is None else coverage * 100
            result["bo"]["quality"]["coverage_percent_css"] = None if coverage is None else f"{coverage * 100:.6f}"
            for group in result["bo"]["groups"].values():
                group["position_percent_css"] = f"{group['value'] / 5 * 100:.6f}"
        questions_by_ref = {question.reference: question for question in applicable}
        answers_by_ref = {
            answer.question.reference: answer
            for answer in assignment.answers.select_related("question")
            if (include_drafts or answer.is_final) and answer.question.reference in active_refs
        }

        def presentation_item(reference):
            question = questions_by_ref[reference]
            answer = answers_by_ref.get(reference)
            choices = list(question.choices.filter(value__in=(answer.value if answer else [])))
            return {
                "question": question,
                "answer": answer,
                "choices": choices,
                "score": result["bo"]["question_scores"].get(reference),
                "categories": list(question.categories.values_list("name", flat=True)),
            }

        result["bo"]["attention_items"] = [
            presentation_item(reference) for reference in result["bo"]["high_questions"]
        ]
        result["bo"]["unknown_items"] = [
            presentation_item(reference) for reference in result["bo"]["quality"]["explicit_unknown"]
        ]
        result["impacts"] = {}
    elif is_it_app_v4:
        active_refs = [question.reference for question in applicable]
        final_answers = {
            answer.question.reference: answer
            for answer in assignment.answers.select_related("question")
            if (include_drafts or answer.is_final) and answer.question.reference in active_refs
        }
        snapshot = None
        if not include_drafts and assignment.status == assignment.SUBMITTED:
            snapshot = ITApplicationScoreSnapshot.objects.filter(assignment=assignment).first()
        it_app_result = snapshot.result if snapshot else score_it_application_v4(
            active_refs,
            {reference: answer.value for reference, answer in final_answers.items()},
            {reference: answer.comment for reference, answer in final_answers.items()},
        )
        for family in it_app_result["families"].values():
            family["position_percent_css"] = (
                None if family["value"] is None
                else f"{family['value'] / 5 * 100:.6f}"
            )
        result["it_app"] = it_app_result
        result["impacts"] = {}
    return result


def persist_bo_snapshot(assignment):
    if assignment.template.questionnaire_type != QuestionnaireTemplate.BO:
        return None
    result = calculate_results(assignment)["bo"]
    snapshot_result = {
        key: value for key, value in result.items()
        if key not in {"attention_items", "unknown_items"}
    }
    snapshot, _created = BOScoreSnapshot.objects.update_or_create(
        assignment=assignment,
        defaults={
            "model_id": result["model_id"],
            "model_version": result["model_version"],
            "active_question_ids": result["active_question_ids"],
            "result": snapshot_result,
        },
    )
    return snapshot


def persist_it_app_snapshot(assignment):
    if not (
        assignment.template.questionnaire_type == QuestionnaireTemplate.IT_APP
        and assignment.template.source_version == "V4"
    ):
        return None
    applicable = applicable_questions(assignment)
    active_refs = [question.reference for question in applicable]
    answers = {
        answer.question.reference: answer
        for answer in assignment.answers.select_related("question")
        if answer.is_final and answer.question.reference in active_refs
    }
    result = score_it_application_v4(
        active_refs,
        {reference: answer.value for reference, answer in answers.items()},
        {reference: answer.comment for reference, answer in answers.items()},
    )
    snapshot, _created = ITApplicationScoreSnapshot.objects.update_or_create(
        assignment=assignment,
        defaults={
            "model_id": result["model_id"],
            "model_version": result["model_version"],
            "active_question_ids": result["active_question_ids"],
            "result": result,
        },
    )
    return snapshot


def safe_excel(value):
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


def build_export(assignment):
    results = calculate_results(assignment)
    wb = Workbook(); summary = wb.active; summary.title = "Synthèse"
    responses = wb.create_sheet("Réponses"); calculations = wb.create_sheet("Calculs"); alerts = wb.create_sheet("Points d'attention")
    summary.append(["Questionnaire", assignment.template.title]); summary.append(["Statut", assignment.get_status_display()])
    summary.append(["Répondant", assignment.respondent.get_full_name() or assignment.respondent.username])
    responses.append(["Référence", "Section", "Question", "Réponse", "Score", "Commentaire"])
    if "bo" in results:
        bo = results["bo"]
        summary.append(["Méthode", f"{bo['model_id']} {bo['model_version']}"])
        summary.append(["Couverture contributive", bo["quality"]["coverage"]])
        if bo["is_v4"]:
            calculations.append([
                "Indicateur", "Valeur / 5", "Statut", "Couverture",
                "Questions déterminantes", "Questions manquantes",
            ])
            for code in ("B_C", "B_I", "B_D", "M_C", "M_I", "M_D", "M_D_7J"):
                data = bo["indicators"][code]
                calculations.append([
                    code.replace("_", "(" , 1).replace("_7J", ", 7 jours") + ")",
                    data["value"], data["status"], data["coverage"]["ratio"],
                    ", ".join(data["determining_questions"]),
                    ", ".join(data["missing_questions"]),
                ])
            calculations.append([])
            calculations.append(["Indicateur", "Question", "Valeur retenue", "Réponse", "Déterminante"])
            for code, data in bo["indicators"].items():
                for item in data["contributions"]:
                    calculations.append([
                        code, item["reference"], item["score"],
                        "; ".join(item["selected_labels"]), "Oui" if item["determining"] else "Non",
                    ])
        else:
            calculations.append(["Dimension", "Indice S / 5", "Enjeu E", "Exposition X", "Faiblesse W"])
            for dimension, data in bo["dimensions"].items():
                calculations.append([dimension, data["S"], data["E"], data["X"], data["W"]])
            calculations.append([])
            calculations.append(["Groupe", "Valeur", "Poids théorique", "Poids effectif", "Questions retenues"])
            for key, group in bo["groups"].items():
                calculations.append([key, group["value"], group["theoretical_weight"], group.get("effective_weight"), ", ".join(row["reference"] for row in group["questions"])])
    elif "it_app" in results:
        it_app = results["it_app"]
        summary.append(["Méthode", f"{it_app['model_id']} {it_app['model_version']}"])
        calculations.append(["Famille", "Nom", "Note brute / 5", "Statut", "Questions contributives", "Questions inconnues"])
        for code, family in it_app["families"].items():
            calculations.append([
                code, family["name"], family["value"], family["status"],
                ", ".join(item["reference"] for item in family["contributions"]),
                ", ".join(family["unknown_questions"]),
            ])
    else:
        calculations.append(["Section", "Indicateur moyen d'écart de contrôle", "ND", "NA", "Notes incluses"])
    alerts.append(["Référence", "Question", "Réponse défavorable / spéciale"])
    for section, data in results["sections"].items():
        if "bo" not in results and "it_app" not in results:
            calculations.append([section, data["average"], data["nd"], data["na"], ", ".join(map(str, data["scores"]))])
        for q, ans, selected, score in data["answers"]:
            labels = "; ".join(c.label for c in selected) if selected else "; ".join(map(str, ans.value))
            responses.append([q.reference, section, safe_excel(q.text), safe_excel(labels), score, safe_excel(ans.comment)])
            if score is not None and score >= 4 or any(c.special == "ND" for c in selected):
                alerts.append([q.reference, safe_excel(q.text), safe_excel(labels)])
    calculations.append([])
    if "bo" in results and results["bo"]["is_v4"]:
        method = "BO_V4 : maximum des notes directes applicables par indicateur B/M. Aucun mélange B/M, aucune pondération, aucun ajustement par les contrôles ou les volumes."
    elif "bo" in results:
        method = "ISRA-BO-CID historique : groupes et composantes E/X/W pondérés sur le seul périmètre actif."
    elif "it_app" in results:
        method = "IT_APPLICATION_WEAKNESS_V4 : moyenne arithmétique simple des notes W connues et applicables, calculée séparément pour chacune des dix familles. Aucun score global ou CIA."
    else:
        method = "Moyenne des notes numériques applicables par section. ND, NA et questions non notées exclus. Choix multiples : maximum, jamais somme."
    calculations.append(["Méthode", method])
    for ws in wb.worksheets:
        ws.freeze_panes = "A2"
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor="17324D")
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(max(len(str(c.value or "")) for c in col) + 2, 70)
    stream = BytesIO(); wb.save(stream); return stream.getvalue()
