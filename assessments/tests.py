from io import BytesIO
import json
import math
from pathlib import Path
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook
from .bo_scoring import score_bo
from .bo_scoring_v4 import load_bo_v4_registry, score_bo_v4
from .it_app_scoring_v4 import (EXPECTED_FAMILIES, EXPECTED_SCALES,
                                load_it_app_v4_registry, score_it_application_v4)
from .models import (Answer, Application, Assignment, BOScoreSnapshot, Campaign, Category, Choice,
                     ITApplicationScoreSnapshot, Question, QuestionnaireTemplate,
                     RiskConclusion, RiskScenario)
from .services import (applicable_questions, calculate_results, persist_bo_snapshot,
                       persist_it_app_snapshot)


class BOScoringReferenceTests(SimpleTestCase):
    def test_all_reference_scenarios(self):
        path = Path(__file__).resolve().parent / "data" / "isra_bo_scenarios_validation_v1.json"
        cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
        self.assertEqual(len(cases), 13)
        for case in cases:
            with self.subTest(case=case["name"]):
                result = score_bo(case["active_question_ids"], case["answers"])
                expected = case["expected"]
                for dimension, values in expected["dimensions"].items():
                    for key, value in values.items():
                        actual = result["dimensions"][dimension][key]
                        if value is None:
                            self.assertIsNone(actual)
                        else:
                            self.assertTrue(math.isclose(actual, value, abs_tol=1e-9))
                self.assertEqual(set(result["groups"]), set(expected["groups"]))
                for key, value in expected["groups"].items():
                    self.assertTrue(math.isclose(result["groups"][key]["value"], value, abs_tol=1e-9))
                self.assertEqual(result["question_scores"], expected["question_scores"])
                for key, value in expected["quality"].items():
                    self.assertEqual(result["quality"][key], value)


class BOScoringV4Tests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.registry = load_bo_v4_registry()

    def option(self, reference, score=None, kind=None):
        return next(
            option["id"] for option in self.registry[reference]["options"]
            if (score is None or option["score"] == score)
            and (kind is None or option["value_type"] == kind)
        )

    def test_1_protection_uses_maximum(self):
        answers = {
            "Q-012": [self.option("Q-012", score=2)],
            "Q-016": [self.option("Q-016", score=4)],
            "Q-017": [self.option("Q-017", score=5)],
        }
        result = score_bo_v4(answers, answers)
        self.assertEqual(result["indicators"]["B_C"]["value"], 5)


class ITApplicationScoringV4Tests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.registry = load_it_app_v4_registry()
        cls.questions = {question["reference"]: question for question in cls.registry["questions"]}

    def option(self, reference, score=None, special=None):
        return next(
            option["id"] for option in self.questions[reference]["options"]
            if (score is None or option["score"] == score)
            and (special is None or option["special"] == special)
        )

    def test_registry_integrity_and_exact_v4_scales(self):
        questions = self.registry["questions"]
        self.assertEqual(len(questions), 82)
        self.assertEqual(len({question["reference"] for question in questions}), 82)
        self.assertEqual(len([question for question in questions if question["role"] == "W"]), 48)
        self.assertEqual(len([question for question in questions if question["role"] != "W"]), 34)
        self.assertEqual(
            {family["code"]: family["questions"] for family in self.registry["families"]},
            EXPECTED_FAMILIES,
        )
        actual_scales = {
            reference: [
                option["score"] if option["score"] is not None else option["special"]
                for option in self.questions[reference]["options"]
            ]
            for reference in EXPECTED_SCALES
        }
        self.assertEqual(actual_scales, EXPECTED_SCALES)
        self.assertFalse(any(
            option["score"] is not None
            for question in questions if question["role"] != "W"
            for option in question["options"]
        ))

    def test_zero_and_five_are_real_scores(self):
        refs = EXPECTED_FAMILIES["API"]
        zeros = {reference: [self.option(reference, score=0)] for reference in refs}
        fives = {reference: [self.option(reference, score=5)] for reference in refs}
        self.assertEqual(score_it_application_v4(refs, zeros)["families"]["API"]["value"], 0)
        self.assertEqual(score_it_application_v4(refs, fives)["families"]["API"]["value"], 5)

    def test_api_reference_case_is_unweighted_and_provisional(self):
        refs = EXPECTED_FAMILIES["API"]
        answers = {
            "C08": [self.option("C08", score=0)],
            "D02": [self.option("D02", score=2)],
            "D04": [self.option("D04", score=4)],
            "D05": [self.option("D05", score=5)],
            "D07": [self.option("D07", special="ND")],
        }
        result = score_it_application_v4(refs, answers)
        self.assertEqual(result["families"]["API"]["value"], 2.75)
        self.assertEqual(result["families"]["API"]["display_value"], 2.8)
        self.assertEqual(result["families"]["API"]["status"], "provisional")
        self.assertTrue(all(
            family["value"] is None for code, family in result["families"].items() if code != "API"
        ))

    def test_nd_na_and_inactive_questions_are_excluded_without_penalty(self):
        refs = EXPECTED_FAMILIES["VUL"]
        answers = {
            "A08": [self.option("A08", special="ND")],
            "F04": [self.option("F04", score=4)],
        }
        result = score_it_application_v4(refs, answers)["families"]["VUL"]
        self.assertEqual(result["value"], 4)
        self.assertEqual(result["status"], "provisional")
        self.assertEqual(result["unknown_questions"], ["A08"])

        api_refs = EXPECTED_FAMILIES["API"]
        api_answers = {
            "C08": [self.option("C08", special="NA")],
            "D05": [self.option("D05", score=0)],
        }
        api = score_it_application_v4(
            api_refs, api_answers, {"C08": "Aucun dépôt de fichier n’est proposé."}
        )["families"]["API"]
        self.assertEqual(api["value"], 0)
        self.assertEqual(api["not_applicable_questions"], ["C08"])

        chg = score_it_application_v4(
            ["F05", "F06"],
            {"F05": [self.option("F05", score=2)], "F06": [self.option("F06", score=4)]},
        )["families"]["CHG"]
        self.assertEqual(chg["value"], 3)
        self.assertEqual(chg["inactive_questions"], ["F10", "F11"])

    def test_no_numeric_answer_is_not_evaluated(self):
        refs = EXPECTED_FAMILIES["JOU"]
        answers = {reference: [self.option(reference, special="ND")] for reference in refs}
        family = score_it_application_v4(refs, answers)["families"]["JOU"]
        self.assertIsNone(family["value"])
        self.assertEqual(family["status"], "not_evaluated")

    def test_family_and_non_scoring_changes_are_isolated(self):
        active = EXPECTED_FAMILIES["IAM"] + EXPECTED_FAMILIES["API"] + ["A05"]
        base = {
            "B04": [self.option("B04", score=0)],
            "D05": [self.option("D05", score=4)],
            "A05": [self.questions["A05"]["options"][0]["id"]],
        }
        changed_iam = dict(base, B04=[self.option("B04", score=5)])
        changed_context = dict(base, A05=[self.questions["A05"]["options"][1]["id"]])
        baseline = score_it_application_v4(active, base)
        iam = score_it_application_v4(active, changed_iam)
        context = score_it_application_v4(active, changed_context)
        self.assertNotEqual(baseline["families"]["IAM"]["value"], iam["families"]["IAM"]["value"])
        for code in EXPECTED_FAMILIES:
            if code != "IAM":
                self.assertEqual(baseline["families"][code]["value"], iam["families"][code]["value"])
            self.assertEqual(baseline["families"][code]["value"], context["families"][code]["value"])


class BOScoringV4AdditionalTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.registry = load_bo_v4_registry()

    def option(self, reference, score=None, kind=None):
        return next(
            option["id"] for option in self.registry[reference]["options"]
            if (score is None or option["score"] == score)
            and (kind is None or option["value_type"] == kind)
        )

    def test_2_zeroes_are_not_averaged_with_five(self):
        answers = {
            "Q-012": [self.option("Q-012", score=0)],
            "Q-014": [self.option("Q-014", score=0)],
            "Q-017": [self.option("Q-017", score=5)],
        }
        self.assertEqual(score_bo_v4(answers, answers)["indicators"]["B_C"]["value"], 5)

    def test_3_unknown_makes_known_result_provisional(self):
        answers = {
            "Q-012": [self.option("Q-012", score=4)],
            "Q-014": [self.option("Q-014", kind="unknown")],
        }
        indicator = score_bo_v4(answers, answers)["indicators"]["B_C"]
        self.assertEqual(indicator["value"], 4)
        self.assertEqual(indicator["status"], "provisional")

    def test_4_no_known_answer_is_not_evaluated(self):
        indicator = score_bo_v4(["Q-012"], {})["indicators"]["B_C"]
        self.assertIsNone(indicator["value"])
        self.assertEqual(indicator["status"], "not_evaluated")

    def test_5_volume_question_never_changes_scores(self):
        direct = {"Q-012": [self.option("Q-012", score=4)]}
        baseline = score_bo_v4(["Q-012", "Q-013"], direct)
        changed = score_bo_v4(
            ["Q-012", "Q-013"],
            {**direct, "Q-013": [self.registry["Q-013"]["options"][-3]["id"]]},
        )
        self.assertEqual(baseline["question_scores"], changed["question_scores"])

    def test_6_b_and_m_are_independent(self):
        active = ["Q-012", "Q-022"]
        first = score_bo_v4(active, {
            "Q-012": [self.option("Q-012", score=2)],
            "Q-022": [self.option("Q-022", score=4)],
        })
        second = score_bo_v4(active, {
            "Q-012": [self.option("Q-012", score=5)],
            "Q-022": [self.option("Q-022", score=4)],
        })
        self.assertEqual(first["indicators"]["M_C"]["value"], second["indicators"]["M_C"]["value"])

    def test_7_seven_day_impact_does_not_change_one_day_impact(self):
        active = ["Q-064", "Q-065"]
        result = score_bo_v4(active, {
            "Q-064": [self.option("Q-064", score=2)],
            "Q-065": [self.option("Q-065", score=5)],
        })
        self.assertEqual(result["indicators"]["M_D"]["value"], 2)
        self.assertEqual(result["indicators"]["M_D_7J"]["value"], 5)

    def test_8_q068_contributes_to_integrity_only(self):
        result = score_bo_v4(["Q-068"], {"Q-068": [self.option("Q-068", score=5)]})
        self.assertEqual(result["indicators"]["B_I"]["value"], 5)
        self.assertIsNone(result["indicators"]["B_D"]["value"])

    def test_9_hidden_question_is_neither_scored_nor_missing(self):
        result = score_bo_v4(
            ["Q-012"],
            {
                "Q-012": [self.option("Q-012", score=2)],
                "Q-014": [self.option("Q-014", score=5)],
            },
        )
        indicator = result["indicators"]["B_C"]
        self.assertEqual(indicator["value"], 2)
        self.assertEqual(indicator["coverage"]["applicable"], 1)

    def test_10_multiple_choice_uses_selected_maximum(self):
        result = score_bo_v4(["Q-012"], {"Q-012": [
            self.option("Q-012", score=2), self.option("Q-012", score=5),
        ]})
        self.assertEqual(result["indicators"]["B_C"]["value"], 5)


class IsraAcceptanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def setUp(self):
        self.bo = User.objects.get(username="demo_bo")
        self.analyst = User.objects.get(username="demo_grc")
        self.it_app = User.objects.get(username="demo_it_app")
        self.other = User.objects.create_user("outsider", password="test-password-123")
        self.application = Application.objects.get(code="APP-001")
        self.campaign = Campaign.objects.create(
            application=self.application, title="Évaluation de test", created_by=self.analyst
        )
        self.assignment = Assignment.objects.create(
            campaign=self.campaign,
            template=QuestionnaireTemplate.objects.get(questionnaire_type="BO", source_version="V4"),
            respondent=self.bo,
        )

    def test_seed_contains_no_evaluation_or_assignment_history(self):
        call_command("seed_demo", verbosity=0)
        self.assertFalse(Campaign.objects.exists())
        self.assertFalse(Assignment.objects.exists())
        self.assertFalse(Answer.objects.exists())
        self.assertEqual(QuestionnaireTemplate.objects.count(), 3)
        self.assertEqual(User.objects.filter(username__startswith="demo_").count(), 10)

    def test_complete_questionnaires_and_category_distribution(self):
        bo = QuestionnaireTemplate.objects.get(questionnaire_type="BO", source_version="V4")
        it_app = QuestionnaireTemplate.objects.get(questionnaire_type="IT_APP", source_version="V4")
        self.assertEqual(Question.objects.filter(section__template=bo).count(), 86)
        self.assertEqual(Choice.objects.filter(question__section__template=bo).count(), 445)
        self.assertEqual(Question.objects.get(section__template=bo, reference="Q-001").priority,
                         "Important mais peu s’en passer")
        self.assertTrue(Question.objects.get(
            section__template=bo, reference="Q-044"
        ).categories.filter(slug="logistique").exists())
        self.assertTrue(Question.objects.get(
            section__template=bo, reference="Q-056"
        ).categories.filter(slug="finance").exists())
        self.assertEqual(Question.objects.filter(section__template=bo, categories__is_common=True).distinct().count(), 63)
        self.assertTrue(Question.objects.get(section__template=bo, reference="Q-001").required)
        self.assertTrue(Question.objects.get(section__template=bo, reference="Q-003").required)
        self.assertEqual(Question.objects.filter(section__template=it_app).count(), 82)
        self.assertEqual(Question.objects.filter(section__template=it_app, categories__is_common=True).distinct().count(), 74)
        self.assertEqual(Question.objects.get(section__template=bo, reference="Q-011").choices.first().value, "Q-011#01")

    def test_it_application_operating_model_filter(self):
        template = QuestionnaireTemplate.objects.get(questionnaire_type="IT_APP", source_version="V4")
        assignment = Assignment.objects.create(campaign=self.campaign, template=template, respondent=self.it_app)
        self.assertEqual(len(applicable_questions(assignment)), 74)
        assignment.selected_categories.add(Category.objects.get(questionnaire_type="IT_APP", slug="saas"))
        self.assertEqual(len(applicable_questions(assignment)), 74)
        assignment.selected_categories.add(Category.objects.get(questionnaire_type="IT_APP", slug="maitrise"))
        self.assertEqual(len(applicable_questions(assignment)), 82)

    def test_bo_explicit_condition_and_category_or_logic(self):
        admin = Category.objects.get(questionnaire_type="BO", slug="administratif")
        commerce = Category.objects.get(questionnaire_type="BO", slug="commerce")
        self.assignment.selected_categories.set([admin, commerce])
        p01 = Question.objects.get(section__template=self.assignment.template, reference="Q-023")
        p02 = Question.objects.get(section__template=self.assignment.template, reference="Q-024")
        self.assertNotIn(p02, applicable_questions(self.assignment))
        exports_occur = p01.choices.get(label="Quelques fois par mois")
        Answer.objects.create(assignment=self.assignment, question=p01, value=[exports_occur.value])
        applicable = applicable_questions(self.assignment)
        self.assertIn(p02, applicable)
        self.assertEqual([q.pk for q in applicable].count(p02.pk), 1)

    def test_invisible_parent_cannot_keep_child_active(self):
        administratif = Category.objects.get(questionnaire_type="BO", slug="administratif")
        self.assignment.selected_categories.add(administratif)
        p01 = Question.objects.get(section__template=self.assignment.template, reference="Q-023")
        p02 = Question.objects.get(section__template=self.assignment.template, reference="Q-024")
        p01.categories.set([administratif])
        occurs = p01.choices.get(label="Quelques fois par mois")
        Answer.objects.create(assignment=self.assignment, question=p01, value=[occurs.value])
        self.assertIn(p02, applicable_questions(self.assignment))
        self.assignment.selected_categories.clear()
        self.assertNotIn(p01, applicable_questions(self.assignment))
        self.assertNotIn(p02, applicable_questions(self.assignment))

    def test_bo_snapshot_keeps_version_and_active_scope(self):
        c01 = Question.objects.get(section__template=self.assignment.template, reference="Q-011")
        choice = c01.choices.get(value="Q-011#01")
        Answer.objects.create(assignment=self.assignment, question=c01, value=[choice.value], is_final=True)
        snapshot = persist_bo_snapshot(self.assignment)
        self.assertEqual(snapshot.model_id, "BO_V4")
        self.assertEqual(snapshot.model_version, "4.0.0")
        self.assertEqual(snapshot.active_question_ids, [q.reference for q in applicable_questions(self.assignment)])
        self.assertTrue(BOScoreSnapshot.objects.filter(assignment=self.assignment).exists())

    def test_bo_v4_results_snapshot_and_export_are_versioned(self):
        template = QuestionnaireTemplate.objects.get(questionnaire_type="BO", source_version="V4")
        assignment = Assignment.objects.create(
            campaign=self.campaign, template=template, respondent=self.bo,
            status=Assignment.SUBMITTED, submitted_at=timezone.now(),
        )
        q012 = Question.objects.get(section__template=template, reference="Q-012")
        q022 = Question.objects.get(section__template=template, reference="Q-022")
        Answer.objects.create(
            assignment=assignment, question=q012,
            value=[q012.choices.filter(score=4).first().value], is_final=True,
        )
        Answer.objects.create(
            assignment=assignment, question=q022,
            value=[q022.choices.filter(score=3).first().value], is_final=True,
        )

        results = calculate_results(assignment)
        self.assertTrue(results["bo"]["is_v4"])
        self.assertEqual(results["bo"]["indicators"]["B_C"]["value"], 4)
        self.assertEqual(results["bo"]["indicators"]["M_C"]["value"], 3)
        snapshot = persist_bo_snapshot(assignment)
        self.assertEqual((snapshot.model_id, snapshot.model_version), ("BO_V4", "4.0.0"))

        self.client.force_login(self.analyst)
        campaign_page = self.client.get(reverse("campaign_detail", args=[self.campaign.pk]))
        self.assertContains(campaign_page, "Voir les scores")
        self.assertContains(campaign_page, "Masquer les scores")
        self.assertContains(campaign_page, 'aria-expanded="false"')
        self.assertContains(campaign_page, 'class="score-detail-row"')
        self.assertContains(campaign_page, "Besoin de protection")
        self.assertContains(campaign_page, "Impact métier")
        self.assertContains(campaign_page, "Confidentialité")
        self.assertContains(campaign_page, "Intégrité")
        self.assertContains(campaign_page, "Disponibilité")
        self.assertContains(campaign_page, "level-4")
        self.assertContains(campaign_page, "level-3")
        page = self.client.get(reverse("results", args=[assignment.pk]))
        self.assertContains(page, "Besoins de protection et impacts métier")
        self.assertContains(page, "Impact à 7 jours")
        self.assertContains(page, 'class="bm-score-scale"', count=2)
        self.assertNotContains(page, "Synthèse BO V4")
        self.assertNotContains(page, "Méthode BO_V4")
        exported = self.client.get(reverse("export_xlsx", args=[assignment.pk]))
        workbook = load_workbook(BytesIO(exported.content), data_only=True)
        calculations = list(workbook["Calculs"].values)
        bc_row = next(row for row in calculations if row[0] == "B(C)")
        self.assertEqual(bc_row[1:3], (4, "provisional"))
        self.assertEqual(bc_row[4], "Q-012")

    def test_analyst_can_create_campaign_and_assign_questionnaire(self):
        call_command("seed_demo", verbosity=0)
        app = Application.objects.get(code="APP-001")
        analyst = User.objects.get(username="demo_grc")
        bo = User.objects.get(username="demo_bo")
        template = QuestionnaireTemplate.objects.get(questionnaire_type="BO", source_version="V4")
        self.client.force_login(analyst)
        response = self.client.post(reverse("campaign_create", args=[app.pk]), {"title": "ISRA OrivERP"})
        self.assertEqual(response.status_code, 302)
        campaign = Campaign.objects.get(title="ISRA OrivERP")
        response = self.client.post(reverse("campaign_assign", args=[campaign.pk]), {"template": template.pk, "respondent": bo.pk})
        self.assertEqual(response.status_code, 302)
        assignment = Assignment.objects.get(campaign=campaign)
        self.client.force_login(bo)
        questionnaire = self.client.get(reverse("questionnaire", args=[assignment.pk]))
        self.assertEqual(questionnaire.status_code, 200)
        self.assertContains(questionnaire, "Q-010")
        self.assertContains(questionnaire, "Q-086")
        self.assertNotContains(questionnaire, "Peu s’en passer")
        self.assertNotContains(questionnaire, "Obligatoire")

    def test_category_remove_and_reactivate_preserves_answer_without_duplicates(self):
        finance = Category.objects.get(questionnaire_type="BO", slug="finance")
        achats = Category.objects.get(questionnaire_type="BO", slug="achats")
        q = Question.objects.get(section__template=self.assignment.template, reference="Q-052")
        choice = q.choices.first()
        self.assignment.selected_categories.set([finance])
        Answer.objects.create(assignment=self.assignment, question=q, value=[choice.value])
        self.assertEqual([x.id for x in applicable_questions(self.assignment)].count(q.id), 1)
        self.assignment.selected_categories.set([achats])
        self.assertIn(q, applicable_questions(self.assignment))
        self.assignment.selected_categories.clear()
        self.assertNotIn(q, applicable_questions(self.assignment))
        self.assertTrue(Answer.objects.filter(assignment=self.assignment, question=q).exists())
        self.assignment.selected_categories.set([finance])
        self.assertEqual(Answer.objects.get(assignment=self.assignment, question=q).value, [choice.value])

    def test_submit_rejects_missing_required_applicable_answers(self):
        self.client.force_login(self.bo)
        response = self.client.post(reverse("questionnaire", args=[self.assignment.pk]), {"categories_present":"1", "action":"submit"}, follow=True)
        self.assignment.refresh_from_db()
        self.assertNotEqual(self.assignment.status, Assignment.SUBMITTED)
        self.assertContains(response, "Soumission impossible")

    def test_help_request_without_answer_validates_question(self):
        applicable = applicable_questions(self.assignment)
        first = applicable[0]
        self.client.force_login(self.bo)
        response = self.client.post(
            reverse("request_help", args=[self.assignment.pk, first.pk]),
            {"comment": ""}, HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.assignment.help_requests.filter(question=first).exists())
        for question in applicable[1:]:
            self.assignment.help_requests.create(
                question=question, author=self.bo, comment="Assistance demandée pour le test."
            )
        response = self.client.post(
            reverse("questionnaire", args=[self.assignment.pk]),
            {"categories_present": "1", "action": "submit"}, follow=True,
        )
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, Assignment.SUBMITTED)
        self.assertEqual(self.assignment.answers.filter(is_final=True).count(), len(applicable))
        self.assertContains(response, "Questionnaire soumis à l’analyste GRC")

    def test_save_persists_answer_categories_and_position(self):
        self.client.force_login(self.bo)
        finance = Category.objects.get(questionnaire_type="BO", slug="finance")
        q = Question.objects.get(section__template=self.assignment.template, reference="Q-001")
        choice = q.choices.first()
        self.client.post(reverse("questionnaire", args=[self.assignment.pk]), {"categories_present":"1", "categories":[finance.id], f"q_{q.id}":choice.value, "last_section":"2", "action":"save"})
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.last_section, 2)
        self.assertTrue(self.assignment.selected_categories.filter(pk=finance.pk).exists())
        self.assertEqual(Answer.objects.get(assignment=self.assignment, question=q).value, [choice.value])

    def test_draft_confidentiality_for_analyst_and_other_respondent(self):
        for user in [self.analyst, self.other]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("questionnaire", args=[self.assignment.pk])).status_code, 403)
            self.assertEqual(self.client.get(reverse("results", args=[self.assignment.pk])).status_code, 403)

    def test_respondent_never_sees_scores_results_or_export(self):
        self.client.force_login(self.bo)
        draft = self.client.get(reverse("questionnaire", args=[self.assignment.pk]))
        self.assertEqual(draft.status_code, 200)
        self.assertNotContains(draft, "Aperçu des indicateurs ISRA métier")
        self.assertNotIn(b">Note ", draft.content)

        self.assignment.status = Assignment.SUBMITTED
        self.assignment.submitted_at = timezone.now()
        self.assignment.save(update_fields=["status", "submitted_at"])

        self.assertEqual(self.client.get(reverse("results", args=[self.assignment.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("export_xlsx", args=[self.assignment.pk])).status_code, 403)
        response = self.client.get(reverse("questionnaire", args=[self.assignment.pk]), follow=True)
        self.assertRedirects(response, reverse("dashboard"))
        self.assertContains(response, "Les résultats lui sont réservés")
        self.assertContains(response, "Transmis à l’analyste GRC")
        self.assertNotContains(response, reverse("results", args=[self.assignment.pk]))

    def test_submitted_results_and_xlsx_export(self):
        template = QuestionnaireTemplate.objects.get(questionnaire_type="IT_APP", source_version="V4")
        assignment = Assignment.objects.create(campaign=self.campaign, template=template, respondent=self.it_app)
        for q in Question.objects.filter(section__template=template):
            choice = q.choices.filter(special="ND").first() or q.choices.first()
            Answer.objects.create(assignment=assignment, question=q, value=[choice.value] if choice else ["Information"], is_final=True)
        assignment.status = Assignment.SUBMITTED
        assignment.save()
        self.client.force_login(self.analyst)
        self.assertEqual(self.client.get(reverse("results", args=[assignment.pk])).status_code, 200)
        response = self.client.get(reverse("export_xlsx", args=[assignment.pk]))
        self.assertEqual(response.status_code, 200)
        wb = load_workbook(BytesIO(response.content))
        self.assertEqual(wb.sheetnames, ["Synthèse", "Réponses", "Calculs", "Points d'attention"])

    def test_it_app_v4_snapshot_results_and_export_show_only_ten_families(self):
        template = QuestionnaireTemplate.objects.get(questionnaire_type="IT_APP", source_version="V4")
        assignment = Assignment.objects.create(
            campaign=self.campaign, template=template, respondent=self.it_app,
            status=Assignment.SUBMITTED, submitted_at=timezone.now(),
        )
        values = {"C08": 0, "D02": 2, "D04": 4, "D05": 5}
        for reference, score in values.items():
            question = Question.objects.get(section__template=template, reference=reference)
            choice = question.choices.get(score=score)
            Answer.objects.create(
                assignment=assignment, question=question, value=[choice.value], is_final=True,
            )
        d07 = Question.objects.get(section__template=template, reference="D07")
        Answer.objects.create(
            assignment=assignment, question=d07,
            value=[d07.choices.get(special="ND").value], is_final=True,
        )
        snapshot = persist_it_app_snapshot(assignment)
        self.assertEqual(
            (snapshot.model_id, snapshot.model_version),
            ("IT_APPLICATION_WEAKNESS_V4", "4.0.0"),
        )
        self.assertEqual(snapshot.result["families"]["API"]["value"], 2.75)
        self.assertTrue(ITApplicationScoreSnapshot.objects.filter(assignment=assignment).exists())

        self.client.force_login(self.analyst)
        page = self.client.get(reverse("results", args=[assignment.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'class="it-family-card"', count=10)
        self.assertContains(page, 'class="it-family-scale score-scale"')
        self.assertContains(page, 'style="--score-position: 55.000000%"')
        self.assertContains(page, "Faiblesses des contrôles par famille")
        self.assertContains(page, "2,8")
        self.assertNotContains(page, 'class="cia-grid"')

        campaign_page = self.client.get(reverse("campaign_detail", args=[self.campaign.pk]))
        self.assertContains(campaign_page, "Voir les scores")
        self.assertContains(campaign_page, "Faiblesses des contrôles par famille")
        self.assertContains(campaign_page, "API")
        self.assertContains(campaign_page, "2,8/5")
        self.assertContains(campaign_page, "level-3")

        exported = self.client.get(reverse("export_xlsx", args=[assignment.pk]))
        workbook = load_workbook(BytesIO(exported.content), data_only=True)
        calculations = list(workbook["Calculs"].values)
        api_row = next(row for row in calculations if row[0] == "API")
        self.assertEqual(api_row[2], 2.75)
        self.assertFalse(any(row and row[0] == "CIA" for row in calculations))

    def test_it_app_v2_history_remains_available_and_uses_legacy_results(self):
        template = QuestionnaireTemplate.objects.get(questionnaire_type="IT_APP", source_version="V2")
        self.assertEqual(Question.objects.filter(section__template=template).count(), 82)
        assignment = Assignment.objects.create(
            campaign=self.campaign, template=template, respondent=self.it_app,
            status=Assignment.SUBMITTED, submitted_at=timezone.now(),
        )
        question = Question.objects.filter(section__template=template, choices__score__isnull=False).first()
        choice = question.choices.filter(score__isnull=False).first()
        Answer.objects.create(
            assignment=assignment, question=question, value=[choice.value], is_final=True,
        )
        results = calculate_results(assignment)
        self.assertNotIn("it_app", results)
        self.assertTrue(results["sections"])
        self.assertFalse(ITApplicationScoreSnapshot.objects.filter(assignment=assignment).exists())

    def test_scenario_crud_and_manual_conclusion_history(self):
        self.client.force_login(self.analyst)
        response = self.client.post(reverse("scenario_create", args=[self.campaign.pk]), {"reference":"RSK-T02", "title":"Test scénario", "description":"Brouillon"})
        self.assertEqual(response.status_code, 302)
        scenario = RiskScenario.objects.get(reference="RSK-T02")
        self.client.post(reverse("scenario_edit", args=[scenario.pk]), {"reference":"RSK-T02", "title":"Scénario modifié", "description":"Brouillon"})
        scenario.refresh_from_db(); self.assertEqual(scenario.title, "Scénario modifié")
        self.client.post(reverse("conclusion_create", args=[self.campaign.pk]), {"level":"HIGH", "justification":"Décision manuelle documentée."})
        self.assertEqual(RiskConclusion.objects.filter(campaign=self.campaign).latest("created_at").level, "HIGH")
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, Campaign.CLOSED)

    def test_only_latest_closed_campaign_can_be_modified(self):
        self.client.force_login(self.analyst)
        self.client.post(
            reverse("conclusion_create", args=[self.campaign.pk]),
            {"level": "LOW", "justification": "Première campagne terminée."},
        )
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, Campaign.CLOSED)

        latest = Campaign.objects.create(
            application=self.application,
            title="Évaluation plus récente",
            created_by=self.analyst,
        )
        self.client.post(
            reverse("conclusion_create", args=[latest.pk]),
            {"level": "HIGH", "justification": "Campagne terminée la plus récente."},
        )
        latest.refresh_from_db()
        self.assertEqual(latest.status, Campaign.CLOSED)

        self.assertEqual(
            self.client.get(reverse("campaign_edit", args=[self.campaign.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("scenario_create", args=[self.campaign.pk]),
                {"reference": "OLD-01", "title": "Modification interdite"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("campaign_edit", args=[latest.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                reverse("campaign_assign", args=[latest.pk]),
                {"template": self.assignment.template_id, "respondent": self.bo.pk},
            ).status_code,
            403,
        )

        conclusion_count = latest.conclusions.count()
        response = self.client.post(
            reverse("conclusion_create", args=[latest.pk]),
            {"level": "CRITICAL", "justification": "Appréciation révisée."},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(latest.conclusions.count(), conclusion_count + 1)
        self.assertEqual(latest.conclusions.latest("created_at").level, "CRITICAL")

    def test_dashboard_shows_latest_validated_risk_on_application_card(self):
        RiskConclusion.objects.create(
            campaign=self.campaign, level="LOW", justification="Ancienne appréciation",
            author=self.analyst,
        )
        RiskConclusion.objects.create(
            campaign=self.campaign, level="CRITICAL", justification="Appréciation actuelle",
            author=self.analyst,
        )
        RiskConclusion.objects.create(
            campaign=self.campaign, level="MODERATE", justification="Brouillon non validé",
            author=self.analyst, is_validated=False,
        )
        self.client.force_login(self.analyst)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'class="risk-bubble critical"')
        self.assertContains(response, "Critique")
        self.assertContains(response, 'class="risk-bubble none"')
        self.assertNotContains(response, "Brouillon non validé")

    def test_demo_users_are_not_staff(self):
        self.assertFalse(User.objects.get(username="demo_grc").is_staff)

    def test_logout_returns_to_home_with_login_access(self):
        self.client.force_login(self.analyst)
        response = self.client.post(reverse("logout"), follow=True)
        self.assertRedirects(response, reverse("home"))
        self.assertContains(response, reverse("login"))
        self.assertContains(response, "Se connecter")
        self.assertNotContains(response, "Accéder à la démonstration")
