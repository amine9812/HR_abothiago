from django.conf import settings
from django.db import models


class Role(models.TextChoices):
    ADMIN = "ADMIN", "ADMIN"
    RESPONSABLE_RH = "RESPONSABLE_RH", "RESPONSABLE RH"
    RESPONSABLE_HIERARCHIQUE = "RESPONSABLE_HIERARCHIQUE", "RESPONSABLE HIERARCHIQUE"
    EMPLOYE = "EMPLOYE", "EMPLOYE"


class UtilisateurProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=40, choices=Role.choices)
    actif = models.BooleanField(default=True)
    employe = models.OneToOneField(
        "hr.Employe",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="utilisateur_profile",
    )

    class Meta:
        verbose_name = "Utilisateur"
        verbose_name_plural = "Utilisateurs"

    def __str__(self):
        return self.user.username

    @property
    def login(self):
        return self.user.username

    @property
    def is_admin_role(self):
        return self.role == Role.ADMIN

    @property
    def is_rh(self):
        return self.role in {Role.ADMIN, Role.RESPONSABLE_RH}

    @property
    def is_manager(self):
        return self.role == Role.RESPONSABLE_HIERARCHIQUE
