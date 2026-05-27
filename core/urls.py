from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard", views.dashboard, name="dashboard"),
    path("admin", views.admin_dashboard, name="admin_dashboard"),
]
