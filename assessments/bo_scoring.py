"""Moteur pur et versionne de scoring ISRA Business Owner."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent / "data"
CONFIG_PATH = DATA_DIR / "isra_bo_scoring_config_v1.json"


class BOScoringConfigurationError(ValueError):
    """Le referentiel BO ne correspond pas au contrat attendu."""


@lru_cache(maxsize=1)
def load_bo_config():
    with CONFIG_PATH.open(encoding="utf-8") as stream:
        config = json.load(stream)
    validate_bo_config(config)
    return config


def validate_bo_config(config):
    questions = config.get("questions", [])
    groups = config.get("groups", [])
    if config.get("model_id") != "ISRA-BO-CID" or config.get("model_version") != "1.0.0":
        raise BOScoringConfigurationError("Version de referentiel BO inattendue.")
    if len(questions) != 86 or sum(len(q["options"]) for q in questions) != 445:
        raise BOScoringConfigurationError("Le referentiel doit contenir 86 questions et 445 options.")
    if len(groups) != 21:
        raise BOScoringConfigurationError("Le referentiel doit contenir 21 groupes.")
    source_ids = [q["source_id"] for q in questions]
    option_ids = [o["id"] for q in questions for o in q["options"]]
    if len(source_ids) != len(set(source_ids)) or len(option_ids) != len(set(option_ids)):
        raise BOScoringConfigurationError("Identifiants BO dupliques.")
    for question in questions:
        if question["role"] not in {"E", "X", "W", "H"}:
            raise BOScoringConfigurationError(f"Role invalide pour {question['source_id']}.")
        for dimension, coefficient in question["coefficients"].items():
            if dimension not in {"C", "I", "D"} or not 0 <= coefficient <= 1:
                raise BOScoringConfigurationError(f"Coefficient invalide pour {question['source_id']}.")
        for option in question["options"]:
            score = option["score"]
            if score is not None and not 0 <= score <= 5:
                raise BOScoringConfigurationError(f"Note invalide pour {option['id']}.")
    totals = {}
    for group in groups:
        key = (group["role"], group["dimension"])
        totals[key] = totals.get(key, 0) + group["weight"]
    if any(abs(total - 1) > 1e-9 for total in totals.values()):
        raise BOScoringConfigurationError("Les poids de groupes ne totalisent pas 1 par role/dimension.")
    return config


def _weighted_average(rows, value_key, weight_key):
    denominator = sum(row[weight_key] for row in rows)
    if not rows or denominator == 0:
        return None
    return sum(row[value_key] * row[weight_key] for row in rows) / denominator


def score_bo(active_question_ids, answers, config=None):
    """Calcule C/I/D uniquement depuis les references explicitement actives.

    ``answers`` associe une reference metier (C01, P04...) a une liste
    d'identifiants d'options stables (C01#01, P04#06...).
    """
    config = validate_bo_config(config) if config is not None else load_bo_config()
    question_map = {q["source_id"]: q for q in config["questions"]}
    active = list(dict.fromkeys(active_question_ids))
    unknown_active = sorted(set(active) - set(question_map))
    if unknown_active:
        raise BOScoringConfigurationError(f"Questions actives inconnues : {', '.join(unknown_active)}")

    question_scores = {}
    question_details = {}
    quality = {
        "active_total": len(active),
        "active_contributive": 0,
        "numeric_contributive": 0,
        "missing_contributive": [],
        "explicit_unknown": [],
        "explicit_na": [],
        "unscorable_contributive": [],
        "ignored_hidden_with_answer": sorted(set(answers) - set(active)),
    }

    for reference in active:
        question = question_map[reference]
        if question["role"] == "H":
            continue
        quality["active_contributive"] += 1
        selected_ids = list(answers.get(reference) or [])
        if not selected_ids:
            quality["missing_contributive"].append(reference)
            continue
        options = {option["id"]: option for option in question["options"]}
        invalid = sorted(set(selected_ids) - set(options))
        if invalid:
            raise BOScoringConfigurationError(
                f"Options inconnues pour {reference} : {', '.join(invalid)}"
            )
        selected = [options[option_id] for option_id in selected_ids]
        value_types = {option["value_type"] for option in selected}
        numeric = [option["score"] for option in selected if option["score"] is not None]
        if "unknown" in value_types:
            if numeric or len(selected) > 1:
                raise BOScoringConfigurationError(f"Reponse ND combinee pour {reference}.")
            quality["explicit_unknown"].append(reference)
            continue
        if "not_applicable" in value_types:
            if numeric or len(selected) > 1:
                raise BOScoringConfigurationError(f"Reponse NA combinee pour {reference}.")
            quality["explicit_na"].append(reference)
            continue
        if not numeric:
            quality["unscorable_contributive"].append(reference)
            continue
        score = max(numeric)
        question_scores[reference] = score
        question_details[reference] = {
            "score": score,
            "selected_options": selected_ids,
            "role": question["role"],
            "label": question["label"],
        }
        quality["numeric_contributive"] += 1

    group_rows = []
    for group in config["groups"]:
        role, dimension, group_id = group["role"], group["dimension"], group["group_id"]
        contributions = []
        for reference in active:
            question = question_map[reference]
            coefficient = question["coefficients"].get(dimension, 0)
            if (
                question["role"] == role
                and question["groups"].get(dimension) == group_id
                and coefficient > 0
                and reference in question_scores
            ):
                contributions.append({
                    "reference": reference,
                    "score": question_scores[reference],
                    "coefficient": coefficient,
                })
        value = _weighted_average(contributions, "score", "coefficient")
        group_rows.append({
            "key": f"{role}/{dimension}/{group_id}",
            "role": role,
            "dimension": dimension,
            "group_id": group_id,
            "title": group["title"],
            "theoretical_weight": group["weight"],
            "value": value,
            "questions": contributions,
        })

    dimensions = {}
    for dimension in ("C", "I", "D"):
        components = {}
        for role in ("E", "X", "W"):
            valid_groups = [
                row for row in group_rows
                if row["dimension"] == dimension and row["role"] == role and row["value"] is not None
            ]
            component = _weighted_average(valid_groups, "value", "theoretical_weight")
            effective_total = sum(row["theoretical_weight"] for row in valid_groups)
            components[role] = component
            for row in valid_groups:
                row["effective_weight"] = row["theoretical_weight"] / effective_total
        enjeu, exposition, weakness = components["E"], components["X"], components["W"]
        if enjeu is None:
            score = None
        else:
            increase = 0 if exposition is None else config["adjustments"]["exposure_max_increase_fraction"] * exposition / 5
            decrease = 0 if weakness is None else config["adjustments"]["controls_max_decrease_fraction"] * (5 - weakness) / 5
            score = min(5, max(0, enjeu * (1 + increase - decrease)))
        dimensions[dimension] = {"E": enjeu, "X": exposition, "W": weakness, "S": score}

    active_groups = [row for row in group_rows if any(
        question_map[ref]["role"] == row["role"]
        and question_map[ref]["groups"].get(row["dimension"]) == row["group_id"]
        and question_map[ref]["coefficients"].get(row["dimension"], 0) > 0
        for ref in active
    )]
    quality["calculable_groups"] = sum(row["value"] is not None for row in active_groups)
    quality["active_uncalculable_groups"] = sum(row["value"] is None for row in active_groups)
    quality["coverage"] = (
        quality["numeric_contributive"] / quality["active_contributive"]
        if quality["active_contributive"] else None
    )
    return {
        "model_id": config["model_id"],
        "model_version": config["model_version"],
        "active_question_ids": active,
        "dimensions": dimensions,
        "groups": {row["key"]: row for row in group_rows if row["value"] is not None},
        "active_uncalculable_groups": [row["key"] for row in active_groups if row["value"] is None],
        "question_scores": question_scores,
        "question_details": question_details,
        "high_questions": sorted(
            [reference for reference, value in question_scores.items() if value >= 4]
        ),
        "quality": quality,
    }
