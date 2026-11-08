from django import forms
from django.contrib.auth.models import User
from django.db.models import Q
from .models import (Assignment, Campaign, QuestionnaireTemplate,
                     RiskConclusion, RiskScenario, UserRole)


class CampaignForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = ["title"]
        labels = {"title": "Nom de l’évaluation"}


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = Assignment
        fields = ["template", "respondent"]
        labels = {"template": "Questionnaire", "respondent": "Répondant"}

    def __init__(self, *args, campaign=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.campaign = campaign
        self.instance.campaign = campaign
        if campaign:
            roles = [UserRole.BO, UserRole.IT_APP]
            allowed = Q(
                questionnaire_type=QuestionnaireTemplate.IT_APP, source_version="V4"
            ) | Q(
                questionnaire_type=QuestionnaireTemplate.BO, source_version="V4"
            )
            self.fields["template"].queryset = QuestionnaireTemplate.objects.filter(allowed)
        else:
            self.fields["template"].queryset = QuestionnaireTemplate.objects.none()
            roles = []
        self.fields["respondent"].queryset = User.objects.filter(
            role_links__role__in=roles, is_active=True
        ).distinct().order_by("last_name", "first_name", "username")

    def clean(self):
        cleaned = super().clean()
        template, respondent = cleaned.get("template"), cleaned.get("respondent")
        if template and respondent:
            required_role = {
                QuestionnaireTemplate.BO: UserRole.BO,
                QuestionnaireTemplate.IT_APP: UserRole.IT_APP,
            }[template.questionnaire_type]
            if not respondent.role_links.filter(role=required_role).exists():
                self.add_error("respondent", "Cet utilisateur ne possède pas le rôle requis pour ce questionnaire.")
        return cleaned

    def save(self, commit=True):
        assignment = super().save(commit=False)
        assignment.campaign = self.campaign
        if commit:
            assignment.full_clean()
            assignment.save()
            self.save_m2m()
        return assignment


class ScenarioForm(forms.ModelForm):
    class Meta:
        model = RiskScenario
        exclude = ["campaign", "created_by"]
        widgets = {f.name: forms.Textarea(attrs={"rows": 3}) for f in RiskScenario._meta.fields if f.name in {
            "description","feared_event","weaknesses","existing_measures","justification","treatment","references"}}


class ConclusionForm(forms.ModelForm):
    class Meta:
        model = RiskConclusion
        fields = ["level", "justification"]
        widgets = {"justification": forms.Textarea(attrs={"rows": 4})}
