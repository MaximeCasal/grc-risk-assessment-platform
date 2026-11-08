"""Moteur pur du scoring ISRA Business Owner V4 (profils B et M).

Les besoins de protection et les impacts métier restent indépendants. Chaque
indicateur retient le maximum des réponses directes connues et ne transforme
jamais une absence, ND ou NA en zéro.
"""
from __future__ import annotations

from functools import lru_cache

from .bo_scoring import BOScoringConfigurationError, load_bo_config


MODEL_ID = "BO_V4"
MODEL_VERSION = "4.0.0"

INDICATOR_QUESTIONS = {
    "B_C": ("Q-012", "Q-014", "Q-016", "Q-017", "Q-018", "Q-019"),
    "B_I": (
        "Q-034", "Q-041", "Q-042", "Q-043", "Q-044", "Q-045",
        "Q-048", "Q-049", "Q-058", "Q-061", "Q-068", "Q-077",
    ),
    "B_D": ("Q-003", "Q-004", "Q-067", "Q-075", "Q-081"),
    "M_C": ("Q-022",),
    "M_I": ("Q-046", "Q-047", "Q-050", "Q-051"),
    "M_D": ("Q-064",),
    "M_D_7J": ("Q-065",),
}

INDICATOR_META = {
    "B_C": ("B", "C", "Besoin de confidentialité"),
    "B_I": ("B", "I", "Besoin d’intégrité"),
    "B_D": ("B", "D", "Besoin de disponibilité"),
    "M_C": ("M", "C", "Impact d’une divulgation"),
    "M_I": ("M", "I", "Impact d’une altération"),
    "M_D": ("M", "D", "Impact d’une indisponibilité d’un jour ouvré"),
    "M_D_7J": ("M", "D", "Impact d’une indisponibilité de sept jours"),
}


@lru_cache(maxsize=1)
def load_bo_v4_registry():
    """Construit le registre V4 depuis les 86 modalités stables versionnées.

    Le registre contient toute la structure nécessaire pour reconstruire le
    questionnaire BO V4. Seuls les rattachements B/M font autorité pour le
    scoring ; toute question absente de ``INDICATOR_QUESTIONS`` est hors score.
    """
    questions = {}
    direct_ids = {reference for refs in INDICATOR_QUESTIONS.values() for reference in refs}
    for source in load_bo_config()["questions"]:
        reference = source["id"]
        options = []
        for index, option in enumerate(source["options"], start=1):
            options.append({
                "id": f"{reference}#{index:02d}",
                "label": option["label"],
                "score": option["score"] if reference in direct_ids else None,
                "value_type": option["value_type"] if option["value_type"] in {
                    "unknown", "not_applicable"
                } else "numeric" if reference in direct_ids else "descriptive",
            })
        questions[reference] = {
            "reference": reference,
            "label": source["label"],
            "options": options,
            "multiple": source["selection_mode_hint"] == "multi",
            "response_type": (
                "text" if not options
                else "multiple" if source["selection_mode_hint"] == "multi"
                else "single"
            ),
            "required": True,
            "help_text": source.get("rationale", ""),
            "display_scope_text": source.get("display_scope_text", source.get("category_scope_text", "")),
            "routing_description": source.get("routing_description", ""),
        }

    expected = {f"Q-{number:03d}" for number in range(1, 87)}
    if set(questions) != expected or sum(len(q["options"]) for q in questions.values()) != 445:
        raise BOScoringConfigurationError("Le registre BO V4 doit contenir 86 questions et 445 modalités.")
    for indicator, references in INDICATOR_QUESTIONS.items():
        for reference in references:
            if reference not in questions:
                raise BOScoringConfigurationError(f"Question V4 absente : {reference} ({indicator}).")
            numeric = [o for o in questions[reference]["options"] if o["score"] is not None]
            if not numeric or any(not 0 <= o["score"] <= 5 for o in numeric):
                raise BOScoringConfigurationError(f"Barème V4 invalide pour {reference}.")
    return questions


def _score_indicator(code, active, answers, questions):
    family, dimension, label = INDICATOR_META[code]
    applicable = []
    missing = []
    explicit_unknown = []
    unanswered = []
    excluded_na = []
    contributions = []

    for reference in INDICATOR_QUESTIONS[code]:
        if reference not in active:
            continue
        selected_ids = list(answers.get(reference) or [])
        options = {option["id"]: option for option in questions[reference]["options"]}
        invalid = sorted(set(selected_ids) - set(options))
        if invalid:
            raise BOScoringConfigurationError(
                f"Modalités V4 inconnues pour {reference} : {', '.join(invalid)}"
            )
        selected = [options[value] for value in selected_ids]
        kinds = {option["value_type"] for option in selected}
        numeric = [option["score"] for option in selected if option["score"] is not None]

        if "not_applicable" in kinds:
            if len(selected) != 1:
                raise BOScoringConfigurationError(f"Réponse NA combinée pour {reference}.")
            excluded_na.append(reference)
            continue

        applicable.append(reference)
        if not selected_ids or "unknown" in kinds:
            if "unknown" in kinds and len(selected) != 1:
                raise BOScoringConfigurationError(f"Réponse ND combinée pour {reference}.")
            missing.append(reference)
            (explicit_unknown if "unknown" in kinds else unanswered).append(reference)
            continue
        if not numeric:
            missing.append(reference)
            continue

        score = max(numeric)
        contributions.append({
            "reference": reference,
            "score": score,
            "selected_options": selected_ids,
            "selected_labels": [option["label"] for option in selected],
        })

    value = max((item["score"] for item in contributions), default=None)
    for item in contributions:
        item["determining"] = item["score"] == value
    answered = len(contributions)
    total = len(applicable)
    return {
        "code": code,
        "family": family,
        "dimension": dimension,
        "label": label,
        "value": value,
        "status": "not_evaluated" if value is None else "provisional" if missing else "complete",
        "coverage": {
            "answered": answered,
            "applicable": total,
            "ratio": answered / total if total else None,
        },
        "contributions": contributions,
        "determining_questions": [item["reference"] for item in contributions if item["determining"]],
        "missing_questions": missing,
        "explicit_unknown": explicit_unknown,
        "unanswered_questions": unanswered,
        "excluded_na": excluded_na,
    }


def score_bo_v4(active_question_ids, answers):
    """Calcule les six indicateurs principaux et M(D, 7 jours)."""
    questions = load_bo_v4_registry()
    active = list(dict.fromkeys(active_question_ids))
    unknown = sorted(set(active) - set(questions))
    if unknown:
        raise BOScoringConfigurationError(f"Questions V4 actives inconnues : {', '.join(unknown)}")

    indicators = {
        code: _score_indicator(code, set(active), answers, questions)
        for code in INDICATOR_QUESTIONS
    }
    direct_active = {ref for refs in INDICATOR_QUESTIONS.values() for ref in refs} & set(active)
    numeric_questions = {
        item["reference"]
        for indicator in indicators.values()
        for item in indicator["contributions"]
    }
    missing_questions = sorted({
        ref for indicator in indicators.values() for ref in indicator["missing_questions"]
    })
    na_questions = sorted({ref for indicator in indicators.values() for ref in indicator["excluded_na"]})
    explicit_unknown = sorted({
        ref for indicator in indicators.values() for ref in indicator["explicit_unknown"]
    })
    unanswered = sorted({
        ref for indicator in indicators.values() for ref in indicator["unanswered_questions"]
    })
    denominator = len(direct_active - set(na_questions))
    return {
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "active_question_ids": active,
        "indicators": indicators,
        "profiles": {
            "B": {dimension: indicators[f"B_{dimension}"] for dimension in ("C", "I", "D")},
            "M": {dimension: indicators[f"M_{dimension}"] for dimension in ("C", "I", "D")},
        },
        "complementary": indicators["M_D_7J"],
        "question_scores": {
            item["reference"]: item["score"]
            for indicator in indicators.values()
            for item in indicator["contributions"]
        },
        "high_questions": sorted({
            item["reference"]
            for indicator in indicators.values()
            for item in indicator["contributions"]
            if item["score"] >= 4
        }),
        "quality": {
            "active_total": len(active),
            "active_direct": len(direct_active),
            "answered_direct": len(numeric_questions),
            "missing_direct": missing_questions,
            "explicit_unknown": explicit_unknown,
            "unanswered_direct": unanswered,
            "explicit_na": na_questions,
            "coverage": len(numeric_questions) / denominator if denominator else None,
        },
    }
