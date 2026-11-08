from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"), path("tableau-de-bord/", views.dashboard, name="dashboard"),
    path("applications/<int:pk>/", views.application_detail, name="application_detail"),
    path("applications/<int:application_id>/evaluations/nouvelle/", views.campaign_create, name="campaign_create"),
    path("campagnes/<int:pk>/", views.campaign_detail, name="campaign_detail"),
    path("campagnes/<int:pk>/modifier/", views.campaign_edit, name="campaign_edit"),
    path("campagnes/<int:pk>/attribuer/", views.campaign_assign, name="campaign_assign"),
    path("questionnaires/<int:pk>/", views.questionnaire, name="questionnaire"),
    path("questionnaires/<int:pk>/resultats/", views.results, name="results"),
    path("questionnaires/<int:pk>/export/", views.export_xlsx, name="export_xlsx"),
    path("questionnaires/<int:pk>/aide/<int:question_id>/", views.request_help, name="request_help"),
    path("campagnes/<int:pk>/scenarios/nouveau/", views.scenario_create, name="scenario_create"),
    path("scenarios/<int:pk>/modifier/", views.scenario_edit, name="scenario_edit"),
    path("scenarios/<int:pk>/supprimer/", views.scenario_delete, name="scenario_delete"),
    path("campagnes/<int:pk>/conclusion/", views.conclusion_create, name="conclusion_create"),
]
