from django.contrib import admin

from .models import UtilisateurProfile


@admin.register(UtilisateurProfile)
class UtilisateurProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "actif", "employe")
    list_filter = ("role", "actif")
    search_fields = ("user__username", "employe__nom", "employe__prenom")
