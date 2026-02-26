from django.urls import path
from .views import dashboard, export_csv, settings_view, duplicate_last, entry_edit, entry_delete
from . import views



urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("settings/", settings_view, name="settings"),
    path("export.csv", export_csv, name="export_csv"),
    path("duplicate/", duplicate_last, name="duplicate_last"),
    path("entries/<int:pk>/edit/", entry_edit, name="entry_edit"),
    path("entries/<int:pk>/delete/", entry_delete, name="entry_delete"),
    path("analytics/", views.analytics, name="analytics"),
]