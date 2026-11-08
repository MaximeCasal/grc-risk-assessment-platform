import json
from functools import lru_cache
from pathlib import Path


REGISTRY_PATH = Path(__file__).resolve().parent / "data" / "isra_it_application_v4.json"

EXPECTED_FAMILIES = {
    "IAM": ["B04", "B05", "B10", "B11", "B12", "B13", "B14", "B15", "B16", "B17"],
    "AUT": ["B06", "B07", "B08", "B09", "D06"],
    "DAT": ["A07", "C01", "C02", "C03", "C06", "C07", "D03"],
    "API": ["C08", "D02", "D04", "D05", "D07"],
    "TRT": ["D08", "D09", "D10", "D11"],
    "JOU": ["E01", "E02", "E03"],
    "DET": ["E04", "E05", "E06", "I04"],
    "VUL": ["A08", "F04"],
    "CHG": ["F05", "F06", "F10", "F11"],
    "REC": ["G04", "G05", "G06", "G07"],
}

EXPECTED_SCALES = {
    "B04": [0, 1, 3, 5, "ND"], "B05": [0, 2, 4, 5, "ND"],
    "B10": [0, 1, 3, 5, "ND"], "B11": [0, 2, 4, 5, "ND"],
    "B12": [0, 2, 4, 5, "NA", "ND"], "B13": [0, 1, 2, 4, 5, "ND"],
    "B14": [0, 2, 4, 5, "NA", "ND"], "B15": [0, 2, 4, 5, "NA", "ND"],
    "B16": [0, 1, 4, 5, "ND"], "B17": [0, 2, 4, 5, "NA", "ND"],
    "B06": [0, 2, 4, 5, "ND"], "B07": [0, 2, 4, 5, "ND"],
    "B08": [0, 2, 5, "NA", "ND"], "B09": [0, 2, 4, 5, "ND"],
    "D06": [0, 2, 4, 5, "NA", "ND"], "A07": [0, 1, 3, 5, "NA", "ND"],
    "C01": [0, 2, 4, 5, "ND"], "C02": [0, 2, 4, 5, "NA", "ND"],
    "C03": [0, 2, 4, 5, "NA", "ND"], "C06": [0, 2, 4, 5, "NA", "ND"],
    "C07": [0, 2, 4, 5, "NA", "ND"], "D03": [0, 2, 4, 5, "NA", "ND"],
    "C08": [0, 2, 4, 5, "NA", "ND"], "D02": [0, 2, 4, 5, "NA", "ND"],
    "D04": [0, 2, 4, 5, "NA", "ND"], "D05": [0, 2, 4, 5, "ND"],
    "D07": [0, 2, 4, 5, "NA", "ND"], "D08": [0, 2, 4, 5, "NA", "ND"],
    "D09": [0, 2, 4, 5, "NA", "ND"], "D10": [0, 2, 4, 5, "NA", "ND"],
    "D11": [0, 2, 4, 5, "NA", "ND"], "E01": [0, 2, 4, 5, "ND"],
    "E02": [0, 2, 4, 5, "ND"], "E03": [0, 2, 4, 5, "ND"],
    "E04": [0, 2, 4, 5, "ND"], "E05": [0, 2, 4, 5, "ND"],
    "E06": [0, 2, 4, 5, "ND"], "I04": [0, 2, 4, 5, "ND"],
    "A08": [0, 2, 3, 5, "ND"], "F04": [0, 2, 4, 5, "ND"],
    "F05": [0, 2, 4, 5, "ND"], "F06": [0, 2, 4, 5, "NA", "ND"],
    "F10": [0, 2, 4, 5, "NA", "ND"], "F11": [0, 2, 4, 5, "NA", "ND"],
    "G04": [0, 2, 4, 5, "ND"], "G05": [0, 2, 4, 5, "NA", "ND"],
    "G06": [0, 2, 4, 5, "NA", "ND"], "G07": [0, 2, 4, 5, "ND"],
}


def _scale(question):
    return [
        option["score"] if option["score"] is not None else option["special"] or None
        for option in question["options"]
    ]


def validate_it_app_v4_registry(registry):
    questions = registry["questions"]
    references = [question["reference"] for question in questions]
    if registry.get("questionnaire_id") != "IT_APPLICATION_V4":
        raise ValueError("Identifiant de questionnaire IT Application V4 invalide.")
    if registry.get("method_id") != "IT_APPLICATION_WEAKNESS_V4":
        raise ValueError("Identifiant de méthode IT Application V4 invalide.")
    if len(questions) != 82 or len(set(references)) != 82:
        raise ValueError("Le référentiel IT Application V4 doit contenir 82 identifiants uniques.")

    weakness = [question for question in questions if question["role"] == "W"]
    outside = [question for question in questions if question["role"] != "W"]
    if len(weakness) != 48 or len(outside) != 34:
        raise ValueError("Le référentiel doit contenir 48 questions W et 34 questions hors scoring.")

    families = {family["code"]: family for family in registry["families"]}
    if list(families) != list(EXPECTED_FAMILIES):
        raise ValueError("Les dix familles W officielles sont absentes ou désordonnées.")
    if {code: family["questions"] for code, family in families.items()} != EXPECTED_FAMILIES:
        raise ValueError("Le rattachement contractuel des questions W aux familles est invalide.")

    by_reference = {question["reference"]: question for question in questions}
    for reference, expected_scale in EXPECTED_SCALES.items():
        question = by_reference.get(reference)
        if not question or question["family"] not in EXPECTED_FAMILIES:
            raise ValueError(f"Famille W absente pour {reference}.")
        if _scale(question) != expected_scale:
            raise ValueError(f"Barème V4 altéré pour {reference}.")
        numeric = [option["score"] for option in question["options"] if option["score"] is not None]
        if any(not 0 <= score <= 5 for score in numeric):
            raise ValueError(f"Note hors échelle pour {reference}.")

    for question in outside:
        if question["family"] is not None:
            raise ValueError(f"Une question hors scoring possède une famille : {question['reference']}.")
        if any(option["score"] is not None for option in question["options"]):
            raise ValueError(f"Une question hors scoring possède une note : {question['reference']}.")
    return registry


@lru_cache(maxsize=1)
def load_it_app_v4_registry():
    with REGISTRY_PATH.open(encoding="utf-8") as stream:
        return validate_it_app_v4_registry(json.load(stream))


def score_it_application_v4(active_question_ids, answers, justifications=None, registry=None):
    registry = validate_it_app_v4_registry(registry or load_it_app_v4_registry())
    active = set(active_question_ids)
    justifications = justifications or {}
    questions = {question["reference"]: question for question in registry["questions"]}
    question_scores = {}
    family_results = {}

    for family in registry["families"]:
        contributions = []
        unknown_questions = []
        not_applicable_questions = []
        inactive_questions = []
        for reference in family["questions"]:
            if reference not in active:
                inactive_questions.append(reference)
                continue
            question = questions[reference]
            options = {option["id"]: option for option in question["options"]}
            selected = [options[value] for value in answers.get(reference, []) if value in options]
            numeric = [option["score"] for option in selected if option["score"] is not None]
            if numeric:
                if len(numeric) != 1:
                    raise ValueError(f"La question {reference} attend une seule note V4.")
                score = numeric[0]
                question_scores[reference] = score
                contributions.append({
                    "reference": reference,
                    "score": score,
                    "selected_labels": [option["label"] for option in selected],
                })
            elif any(option["special"] == "NA" for option in selected):
                if str(justifications.get(reference, "")).strip():
                    not_applicable_questions.append(reference)
                else:
                    unknown_questions.append(reference)
            else:
                unknown_questions.append(reference)

        value = (
            sum(item["score"] for item in contributions) / len(contributions)
            if contributions else None
        )
        status = "not_evaluated" if value is None else "provisional" if unknown_questions else "complete"
        family_results[family["code"]] = {
            "code": family["code"],
            "name": family["name"],
            "value": value,
            "display_value": None if value is None else round(value, 1),
            "status": status,
            "contributions": contributions,
            "unknown_questions": unknown_questions,
            "not_applicable_questions": not_applicable_questions,
            "inactive_questions": inactive_questions,
        }

    return {
        "model_id": registry["method_id"],
        "model_version": registry["method_version"],
        "questionnaire_id": registry["questionnaire_id"],
        "questionnaire_version": registry["questionnaire_version"],
        "active_question_ids": [
            question["reference"] for question in registry["questions"]
            if question["reference"] in active
        ],
        "families": family_results,
        "question_scores": question_scores,
    }
