from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models


class UserRole(models.Model):
    ANALYST, BO, IT_APP = "ANALYST", "BO", "IT_APP"
    ROLES = [(ANALYST, "Cyber / Analyste GRC"), (BO, "Business Owner"),
             (IT_APP, "Responsable IT Application")]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="role_links")
    role = models.CharField(max_length=20, choices=ROLES)
    job_title = models.CharField(max_length=120, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "role"], name="unique_user_role")]


class Application(models.Model):
    code = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=100)
    domain = models.CharField(max_length=100)
    business_owner_name = models.CharField(max_length=120)
    description = models.TextField()
    functions = models.TextField()
    users = models.TextField(blank=True)
    data = models.TextField(blank=True)
    relations = models.TextField(blank=True)
    def __str__(self): return f"{self.code} — {self.name}"


class Campaign(models.Model):
    DRAFT, ACTIVE, CLOSED = "DRAFT", "ACTIVE", "CLOSED"
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="campaigns")
    title = models.CharField(max_length=150)
    status = models.CharField(max_length=12, choices=[(DRAFT,"Brouillon"),(ACTIVE,"Active"),(CLOSED,"Terminée")], default=ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    def __str__(self): return self.title


class Category(models.Model):
    questionnaire_type = models.CharField(max_length=10)
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    is_common = models.BooleanField(default=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["questionnaire_type", "slug"], name="unique_category_type_slug")]
    def __str__(self): return self.name


class QuestionnaireTemplate(models.Model):
    BO, IT_APP = "BO", "IT_APP"
    TYPES = [(BO,"Business Owner"),(IT_APP,"IT Application")]
    code = models.CharField(max_length=30, unique=True)
    title = models.CharField(max_length=160)
    questionnaire_type = models.CharField(max_length=10, choices=TYPES)
    source_version = models.CharField(max_length=30, default="V2")
    def __str__(self): return self.title


class Section(models.Model):
    template = models.ForeignKey(QuestionnaireTemplate, on_delete=models.CASCADE, related_name="sections")
    order = models.PositiveIntegerField()
    title = models.CharField(max_length=180)
    class Meta:
        ordering = ["order"]
        constraints = [models.UniqueConstraint(fields=["template", "order"], name="unique_section_order")]


class Question(models.Model):
    SINGLE, MULTIPLE, TEXT = "single", "multiple", "text"
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="questions")
    reference = models.CharField(max_length=10)
    order = models.PositiveIntegerField()
    text = models.TextField()
    help_text = models.TextField(blank=True)
    priority = models.CharField(max_length=40, blank=True)
    response_type = models.CharField(max_length=12, choices=[(SINGLE,"Choix unique"),(MULTIPLE,"Choix multiple"),(TEXT,"Texte libre")])
    required = models.BooleanField(default=True)
    metric = models.CharField(max_length=20, choices=[("impact_c","Impact confidentialité"),("impact_i","Impact intégrité"),("impact_d","Impact disponibilité"),("control","Indicateur de contrôle"),("context","Contexte")], default="context")
    categories = models.ManyToManyField(Category, related_name="questions")
    condition_question_ref = models.CharField(max_length=10, blank=True)
    condition_excluded_values = models.JSONField(default=list, blank=True)
    class Meta:
        ordering = ["section__order", "order"]
        constraints = [models.UniqueConstraint(fields=["section", "reference"], name="unique_question_ref_section")]


class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choices")
    value = models.CharField(max_length=80)
    label = models.CharField(max_length=250)
    score = models.IntegerField(null=True, blank=True)
    special = models.CharField(max_length=3, choices=[("","—"),("ND","ND"),("NA","NA")], blank=True)
    exclusive = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    class Meta: ordering = ["order", "id"]


class Assignment(models.Model):
    NOT_STARTED, IN_PROGRESS, SUBMITTED = "NOT_STARTED", "IN_PROGRESS", "SUBMITTED"
    campaign = models.ForeignKey(Campaign, null=True, blank=True, on_delete=models.CASCADE, related_name="assignments")
    template = models.ForeignKey(QuestionnaireTemplate, on_delete=models.PROTECT)
    respondent = models.ForeignKey(User, on_delete=models.PROTECT, related_name="questionnaires")
    status = models.CharField(max_length=15, choices=[(NOT_STARTED,"À commencer"),(IN_PROGRESS,"En cours"),(SUBMITTED,"Soumis")], default=NOT_STARTED)
    selected_categories = models.ManyToManyField(Category, blank=True)
    seen_question_ids = models.JSONField(default=list, blank=True)
    added_question_ids = models.JSONField(default=list, blank=True)
    last_section = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    def clean(self):
        if self.template_id and not self.campaign_id:
            raise ValidationError("Un questionnaire applicatif doit être lié à une campagne.")
    def __str__(self): return f"{self.template.code} — {self.respondent.get_full_name() or self.respondent.username}"


class Answer(models.Model):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.PROTECT)
    value = models.JSONField(default=list)
    comment = models.TextField(blank=True)
    is_final = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["assignment", "question"], name="unique_answer")]


class BOScoreSnapshot(models.Model):
    assignment = models.OneToOneField(Assignment, on_delete=models.CASCADE, related_name="bo_score_snapshot")
    model_id = models.CharField(max_length=40)
    model_version = models.CharField(max_length=20)
    active_question_ids = models.JSONField(default=list)
    result = models.JSONField(default=dict)
    calculated_at = models.DateTimeField(auto_now=True)


class ITApplicationScoreSnapshot(models.Model):
    assignment = models.OneToOneField(
        Assignment, on_delete=models.CASCADE, related_name="it_app_score_snapshot"
    )
    model_id = models.CharField(max_length=50)
    model_version = models.CharField(max_length=20)
    active_question_ids = models.JSONField(default=list)
    result = models.JSONField(default=dict)
    calculated_at = models.DateTimeField(auto_now=True)


class HelpRequest(models.Model):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="help_requests")
    question = models.ForeignKey(Question, on_delete=models.PROTECT)
    author = models.ForeignKey(User, on_delete=models.PROTECT)
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)


class RiskScenario(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="scenarios")
    reference = models.CharField(max_length=20)
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    feared_event = models.TextField(blank=True)
    weaknesses = models.TextField(blank=True)
    existing_measures = models.TextField(blank=True)
    impact = models.CharField(max_length=40, blank=True)
    likelihood = models.CharField(max_length=40, blank=True)
    inherent_risk = models.CharField(max_length=40, blank=True)
    residual_risk = models.CharField(max_length=40, blank=True)
    justification = models.TextField(blank=True)
    treatment = models.TextField(blank=True)
    references = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["campaign", "reference"], name="unique_scenario_ref")]


class RiskConclusion(models.Model):
    LEVELS = [("LOW","Faible"),("MODERATE","Modéré"),("HIGH","Important"),("CRITICAL","Critique")]
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="conclusions")
    level = models.CharField(max_length=12, choices=LEVELS)
    justification = models.TextField()
    author = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    is_validated = models.BooleanField(default=True)
