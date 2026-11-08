"""Import des questionnaires depuis les documents de référence.

BO V4 est reconstruit exclusivement depuis son PDF de référence et son registre
structuré versionné. Le parseur PDF historique ne concerne plus que le
questionnaire IT Application V2.
"""
import re
from pathlib import Path

from django.conf import settings
from pypdf import PdfReader

from .bo_scoring_v4 import load_bo_v4_registry
from .it_app_scoring_v4 import load_it_app_v4_registry
from .models import Category, Choice, Question, QuestionnaireTemplate, Section


BO_V4_SOURCE_FILENAME = "Orivane_Questionnaire_ISRA_BO_V4.pdf"
IT_APP_V2_SOURCE = (
    "ISRA-IT-APP-V2",
    "Questionnaire ISRA IT — Application",
    "Questionnaire_ISRA_IT_Application_V2.pdf",
)

IT_APP_V2_SECTIONS = {
    "A": (1, "Identification et architecture applicative"),
    "B": (2, "Exposition, authentification et autorisations"),
    "C": (3, "Protection des données et secrets applicatifs"),
    "D": (4, "Interfaces, API et fiabilité des traitements"),
    "E": (5, "Journalisation, détection et supervision"),
    "F": (6, "Vulnérabilités et sécurité du cycle de vie applicatif"),
    "G": (7, "Continuité de service et reprise applicative"),
    "H": (8, "Fournisseurs et assurance des contrôles applicatifs"),
    "I": (9, "Gouvernance, incidents et justificatifs applicatifs"),
}

BO_CATEGORIES = [
    ("Socle commun", "socle", True), ("Finance", "finance", False),
    ("RH", "rh", False), ("Achats", "achats", False),
    ("Commerce", "commerce", False), ("Logistique", "logistique", False),
    ("Qualité", "qualite", False), ("Administratif", "administratif", False),
    ("Juridique", "juridique", False), ("Intégrations SI", "integrations", False),
    ("Identités et accès", "identites-acces", False), ("Reporting", "reporting", False),
]
APP_CATEGORIES = [
    ("Socle commun", "socle", True),
    ("Service applicatif exploité par un éditeur", "saas", False),
    ("Solution sous maîtrise technique de l’entreprise", "maitrise", False),
]

QUESTION_RE = re.compile(r"(?m)^([A-Z]\d{2})\.\s+")
OPTION_RE = re.compile(r"^(.*?)\s+(—|[0-5]|ND|NA)\s*$")

BO_V4_SECTIONS = [
    (1, "Usage & dépendances métier", 1, 10),
    (2, "Données & confidentialité", 11, 22),
    (3, "Partage, export & conservation", 23, 31),
    (4, "Utilisateurs & habilitations", 32, 40),
    (5, "Exactitude & intégrité", 41, 62),
    (6, "Disponibilité & continuité", 63, 75),
    (7, "Exigences & obligations", 76, 81),
    (8, "Incidents & évolutions", 82, 86),
]

BO_V4_CONDITIONS = {
    "Q-015": ("Q-014", ["Aucune de ces situations", "Je ne sais pas"]),
    "Q-024": ("Q-023", ["Jamais", "Je ne sais pas"]),
    "Q-025": ("Q-023", ["Jamais", "Je ne sais pas"]),
    "Q-026": ("Q-023", ["Jamais", "Je ne sais pas"]),
    "Q-059": ("Q-058", ["Non, aucune opération financière", "Je ne sais pas"]),
    "Q-060": ("Q-058", ["Non, aucune opération financière", "Je ne sais pas"]),
    "Q-072": ("Q-071", ["Non, aucune solution de remplacement utilisable", "Je ne sais pas"]),
}


def _clean(value):
    value = re.sub(r"\s+", " ", value or "").strip()
    return value.replace("inter -applicatif", "inter-applicatif")


def _pdf_text(path):
    text = "\n".join((page.extract_text() or "") for page in PdfReader(path).pages)
    text = re.sub(r"Questionnaire ISRA (?:BO|IT)\s*•\s*Page \d+", "", text)
    return text.split("Annexe —", 1)[0].split("ANNEXE —", 1)[0]


def _question_blocks(text):
    matches = list(QUESTION_RE.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        yield match.group(1), text[match.end():end].strip()


def _title_and_remainder(block):
    end = block.find("?") + 1
    if end <= 0:
        end = block.find("\n")
    return _clean(block[:end]), block[end:]


def _it_app_category_names(remainder):
    marker = re.search(r"Catégories? et sous-catégories\s*:|Catégorie\s*:", remainder, re.I)
    if not marker:
        return ["Socle commun"]
    tail = remainder[marker.end():]
    boundary = re.search(
        r"\n(?:Si\s*:|Plusieurs réponses|Choix multiples|Enjeu métier|Contexte,|Indicateur de contrôle|Réponse / précisions|Préciser|Exemples?\s*:)",
        tail, re.I,
    )
    metadata = tail[:boundary.start()] if boundary else tail[:600]
    names = [
        name for name, _slug, _common in APP_CATEGORIES
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", metadata, re.I)
    ]
    return names or ["Socle commun"]


def _options(remainder):
    found = []
    for raw in remainder.splitlines():
        line = _clean(raw)
        if not line or "Réponse / précisions" in line or set(line) <= {".", " "}:
            continue
        match = OPTION_RE.match(line)
        if not match:
            continue
        label, token = _clean(match.group(1)), match.group(2)
        if not label or label.startswith(("Page ", "Questionnaire ")):
            continue
        score = int(token) if token.isdigit() else None
        special = token if token in {"ND", "NA"} else ""
        found.append({"label": label, "score": score, "special": special})
    return found


def _help_text(remainder, options):
    text = remainder
    if options:
        first = options[0]["label"]
        pos = text.find(first)
        if pos >= 0:
            text = text[:pos]
    text = re.sub(r"Catégories? et sous-catégories\s*:.*?(?=\n(?:Si\s*:|Plusieurs réponses|Choix multiples|Enjeu métier|Contexte,|Indicateur|Réponse / précisions|Préciser|Exemples?\s*:)|$)", "", text, flags=re.I | re.S)
    text = re.sub(r"Catégorie\s*:\s*[^\n]+", "", text, flags=re.I)
    text = re.sub(r"(?:Plusieurs réponses possibles|Choix multiples?|Enjeu métier\s*:[^•\n]+|Contexte, exposition ou dépendance \(hors note de criticité\)|Indicateur de contrôle métier \(hors note de criticité\))\s*(?:•)?", "", text, flags=re.I)
    text = re.sub(r"Réponse / précisions\s*:.*", "", text, flags=re.I | re.S)
    return _clean(text).strip(" •")


def parse_it_app_v2_questionnaire(path=None):
    path = Path(path or settings.BASE_DIR / "docs" / "sources" / IT_APP_V2_SOURCE[2])
    parsed = []
    for reference, block in _question_blocks(_pdf_text(path)):
        title, remainder = _title_and_remainder(block)
        options = _options(remainder)
        multiple = bool(re.search(r"Plusieurs réponses|Choix multiples", remainder, re.I))
        response_type = Question.MULTIPLE if multiple else (Question.SINGLE if options else Question.TEXT)
        metric = "control" if any(option["score"] is not None for option in options) else "context"
        parsed.append({
            "reference": reference, "order": int(reference[1:]), "text": title,
            "help_text": _help_text(remainder, options), "response_type": response_type,
            "required": True, "metric": metric, "categories": _it_app_category_names(remainder),
            "choices": options, "priority": "",
        })
    return parsed


def _normalize_reference_text(value):
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _validate_bo_v4_source(registry):
    """Vérifie que le PDF V4 et le registre structuré décrivent le même questionnaire."""
    path = settings.BASE_DIR / "docs" / "sources" / BO_V4_SOURCE_FILENAME
    if not path.exists():
        raise ValueError(f"Source BO V4 absente : {path}")
    text = "\n".join((page.extract_text() or "") for page in PdfReader(path).pages)
    pdf_references = set(re.findall(r"\bQ-\d{3}\b", text))
    if pdf_references != set(registry):
        raise ValueError("Les 86 identifiants du PDF BO V4 et du registre ne concordent pas.")
    normalized_text = _normalize_reference_text(text)
    missing_options = [
        option["id"]
        for question in registry.values()
        for option in question["options"]
        if _normalize_reference_text(option["label"]) not in normalized_text
    ]
    if missing_options:
        raise ValueError(
            "Modalités du registre BO V4 absentes du PDF : " + ", ".join(missing_options)
        )


def _bo_v4_priority(question):
    match = re.search(r"Priorité\s*:\s*([^|]+)", question["routing_description"])
    return _clean(match.group(1)) if match else "Non spécifiée"


def load_bo_v4_questionnaire():
    """Ajoute ou synchronise l'unique questionnaire BO actif : la V4."""
    registry = load_bo_v4_registry()
    _validate_bo_v4_source(registry)
    existing = QuestionnaireTemplate.objects.filter(code="ISRA-BO-V4").first()
    if existing:
        categories = {
            category.name: category
            for category in Category.objects.filter(questionnaire_type=QuestionnaireTemplate.BO)
        }
        for question in Question.objects.filter(section__template=existing):
            configured = registry.get(question.reference)
            if not configured:
                continue
            update_fields = []
            if question.text != configured["label"]:
                question.text = configured["label"]
                update_fields.append("text")
            configured_categories = [
                name for name, _slug, _common in BO_CATEGORIES
                if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", configured["display_scope_text"], re.I)
            ] or ["Socle commun"]
            question.categories.set([categories[name] for name in configured_categories])
            priority = _bo_v4_priority(configured)
            if question.priority != priority:
                question.priority = priority
                update_fields.append("priority")
            if update_fields:
                question.save(update_fields=update_fields)
        return Question.objects.filter(section__template=existing).count()

    categories = {
        category.name: category
        for category in Category.objects.filter(questionnaire_type=QuestionnaireTemplate.BO)
    }
    template = QuestionnaireTemplate.objects.create(
        code="ISRA-BO-V4",
        title="Questionnaire ISRA Business Owner V4 — Besoins & impacts",
        questionnaire_type=QuestionnaireTemplate.BO,
        source_version="V4",
    )
    sections = {
        order: Section.objects.create(template=template, order=order, title=title)
        for order, title, _start, _end in BO_V4_SECTIONS
    }
    questions_by_ref = {}
    for reference, configured in registry.items():
        number = int(reference[2:])
        section_order = next(
            order for order, _title, start, end in BO_V4_SECTIONS if start <= number <= end
        )
        configured_categories = [
            name for name, _slug, _common in BO_CATEGORIES
            if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", configured["display_scope_text"], re.I)
        ] or ["Socle commun"]
        question = Question.objects.create(
            section=sections[section_order],
            reference=reference,
            order=number,
            text=configured["label"],
            help_text=configured["help_text"],
            priority=_bo_v4_priority(configured),
            response_type=configured["response_type"],
            required=configured["required"],
            metric="context",
        )
        question.categories.set([categories[name] for name in configured_categories])
        multiple = question.response_type == Question.MULTIPLE
        for index, option in enumerate(configured["options"]):
            special = (
                "ND" if option["value_type"] == "unknown"
                else "NA" if option["value_type"] == "not_applicable"
                else ""
            )
            Choice.objects.create(
                question=question,
                value=option["id"],
                label=option["label"],
                score=option["score"],
                special=special,
                exclusive=multiple and (
                    bool(special) or option["label"].lower().startswith(("aucun", "aucune"))
                ),
                order=index,
            )
        questions_by_ref[reference] = question

    for reference, (parent_ref, excluded_labels) in BO_V4_CONDITIONS.items():
        question, parent = questions_by_ref[reference], questions_by_ref[parent_ref]
        question.condition_question_ref = parent_ref
        question.condition_excluded_values = list(
            parent.choices.filter(label__in=excluded_labels).values_list("value", flat=True)
        )
        question.save(update_fields=["condition_question_ref", "condition_excluded_values"])
    return len(questions_by_ref)


def load_it_app_v4_questionnaire():
    """Installe IT Application V4 sans modifier le questionnaire IT V2 historique."""
    existing = QuestionnaireTemplate.objects.filter(code="ISRA-IT-APP-V4").first()
    if existing:
        return Question.objects.filter(section__template=existing).count()

    registry = load_it_app_v4_registry()
    categories = {
        name: Category.objects.get_or_create(
            questionnaire_type=QuestionnaireTemplate.IT_APP,
            slug=slug,
            defaults={"name": name, "is_common": common},
        )[0]
        for name, slug, common in APP_CATEGORIES
    }
    template = QuestionnaireTemplate.objects.create(
        code="ISRA-IT-APP-V4",
        title="Questionnaire ISRA IT Application V4 — Faiblesses des contrôles",
        questionnaire_type=QuestionnaireTemplate.IT_APP,
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
        question.categories.set([categories[data["category"]]])
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
    return len(registry["questions"])


def load_questionnaires():
    category_rows = {
        QuestionnaireTemplate.BO: BO_CATEGORIES,
        QuestionnaireTemplate.IT_APP: APP_CATEGORIES,
    }
    categories_by_kind = {
        kind: {
            name: Category.objects.create(
                questionnaire_type=kind, name=name, slug=slug, is_common=common
            )
            for name, slug, common in rows
        }
        for kind, rows in category_rows.items()
    }
    code, title, _filename = IT_APP_V2_SOURCE
    categories = categories_by_kind[QuestionnaireTemplate.IT_APP]
    template = QuestionnaireTemplate.objects.create(
        code=code,
        title=title,
        questionnaire_type=QuestionnaireTemplate.IT_APP,
        source_version="V2",
    )
    sections = {
        prefix: Section.objects.create(template=template, order=order, title=section_title)
        for prefix, (order, section_title) in IT_APP_V2_SECTIONS.items()
    }
    questions_by_ref = {}
    for data in parse_it_app_v2_questionnaire():
        question = Question.objects.create(
            section=sections[data["reference"][0]], reference=data["reference"], order=data["order"],
            text=data["text"], help_text=data["help_text"], priority=data["priority"], response_type=data["response_type"],
            required=data["required"], metric=data["metric"],
        )
        question.categories.set([categories[name] for name in data["categories"]])
        multiple = data["response_type"] == Question.MULTIPLE
        for index, choice in enumerate(data["choices"]):
            value = choice["special"] or (
                f"s{choice['score']}_{index}" if choice["score"] is not None else f"v{index + 1}"
            )
            Choice.objects.create(
                question=question, value=value, label=choice["label"], score=choice["score"],
                special=choice["special"], exclusive=multiple and (bool(choice["special"]) or choice["label"].lower().startswith(("aucun", "aucune"))), order=index,
            )
        questions_by_ref[data["reference"]] = question
    counts = {QuestionnaireTemplate.IT_APP: len(questions_by_ref)}
    counts[QuestionnaireTemplate.BO] = load_bo_v4_questionnaire()
    counts[QuestionnaireTemplate.IT_APP] = load_it_app_v4_questionnaire()
    return counts
