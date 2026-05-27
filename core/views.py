from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone

from accounts.models import Role
from hr.models import (
    Actualite,
    AffectationFormation,
    CommandeProduit,
    ComptePoints,
    ConversationRH,
    DemandeAdministrative,
    DemandeConge,
    Employe,
    PlanningShift,
    Pointage,
    Remuneration,
    ReclamationRH,
    SoldeConge,
    StatutDemande,
    TacheEquipe,
)


def home(request):
    return redirect("dashboard" if request.user.is_authenticated else "login")


@login_required
def dashboard(request):
    profile = getattr(request.user, "profile", None)
    employes_actifs = Employe.objects.filter(actif=True)
    today = timezone.localdate()
    conges = DemandeConge.objects.select_related("employe", "traitee_par")[:]
    demandes_admin = DemandeAdministrative.objects.select_related("employe", "traitee_par")[:]

    conges_en_attente = sum(1 for demande in conges if demande.statut == StatutDemande.EN_ATTENTE)
    demandes_admin_en_attente = sum(1 for demande in demandes_admin if demande.statut == StatutDemande.EN_ATTENTE)
    conges_valides = sum(1 for demande in conges if demande.statut == StatutDemande.VALIDEE)
    demandes_traitees = sum(1 for demande in demandes_admin if demande.statut != StatutDemande.EN_ATTENTE)
    total_demandes = len(conges) + len(demandes_admin)
    demandes_resolues = sum(1 for demande in conges if demande.statut != StatutDemande.EN_ATTENTE) + demandes_traitees
    taux_traitement = 100 if total_demandes == 0 else round((demandes_resolues * 100) / total_demandes)
    notifications = profile.notifications.filter(lue=False).count() if profile else 0
    is_rh = profile and profile.role in {Role.ADMIN, Role.RESPONSABLE_RH}
    is_manager = profile and profile.role == Role.RESPONSABLE_HIERARCHIQUE
    employee = profile.employe if profile else None
    team = Employe.objects.filter(responsable=employee, actif=True) if employee else Employe.objects.none()
    pointages_today = Pointage.objects.filter(date=today)
    upcoming_shifts = PlanningShift.objects.filter(date_fin__date__gte=today).exclude(statut__in=["annule", "termine"])
    open_tasks = TacheEquipe.objects.exclude(statut__in=["terminee", "annulee"])
    reclamations_ouvertes = ReclamationRH.objects.filter(statut__in=["ouverte", "en_cours"])
    employee_pending_conges = DemandeConge.objects.filter(employe=employee, statut=StatutDemande.EN_ATTENTE).count() if employee else 0
    employee_pending_admin = DemandeAdministrative.objects.filter(employe=employee, statut=StatutDemande.EN_ATTENTE).count() if employee else 0
    employee_pointage = pointages_today.filter(employe=employee).first() if employee else None
    compte = ComptePoints.objects.get_or_create(employe=employee)[0] if employee else None
    solde = SoldeConge.objects.get_or_create(employe=employee)[0] if employee else None
    score_rh = max(42, min(99, 82 + employes_actifs.count() - (conges_en_attente * 3) - (demandes_admin_en_attente * 2) - notifications))

    return render(
        request,
        "dashboard/index.html",
        {
            "page_title": "Tableau de bord",
            "role_actuel": profile.role if profile else "",
            "role_label": profile.role.replace("_", " ") if profile else "Session",
            "total_employes_actifs": employes_actifs.count(),
            "conges_en_attente": conges_en_attente,
            "demandes_admin_en_attente": demandes_admin_en_attente,
            "conges_valides": conges_valides,
            "demandes_traitees": demandes_traitees,
            "taux_traitement": taux_traitement,
            "score_rh": score_rh,
            "notifications_dashboard": notifications,
            "recent_conges": conges[:5],
            "recent_demandes_admin": demandes_admin[:5],
            "employes_preview": employes_actifs[:8],
            "is_rh_dashboard": is_rh,
            "is_manager_dashboard": is_manager,
            "solde_conge": solde,
            "compte_points": compte,
            "dernier_pointage": employee_pointage or (Pointage.objects.filter(employe=employee).first() if employee else None),
            "presences_aujourdhui": pointages_today.count(),
            "retards_aujourdhui": pointages_today.filter(statut="retard").count(),
            "formations_assignees": AffectationFormation.objects.filter(employe=employee).exclude(statut="terminee").count() if employee else 0,
            "commandes_en_attente": CommandeProduit.objects.filter(statut="en_attente").count() if is_rh else CommandeProduit.objects.filter(employe=employee, statut="en_attente").count() if employee else 0,
            "messages_non_lus": ConversationRH.objects.filter(employe=employee).count() if employee else 0,
            "actualites_recentes": Actualite.objects.filter(statut="publiee")[:3],
            "team_count": team.count(),
            "team_presences": pointages_today.filter(employe__in=team).count(),
            "team_retards": pointages_today.filter(employe__in=team, statut="retard").count(),
            "salary_summary": Remuneration.objects.filter(actif=True).count() if is_rh else 0,
            "shifts_a_venir": upcoming_shifts.count() if is_rh else upcoming_shifts.filter(Q(employe=employee) | Q(employe__isnull=True, statut="ouvert")).count() if employee else 0,
            "taches_ouvertes": open_tasks.count() if is_rh else open_tasks.filter(Q(employe=employee) | Q(departement=employee.departement, employe__isnull=True)).count() if employee else 0,
            "reclamations_a_traiter": reclamations_ouvertes.count() if is_rh else reclamations_ouvertes.filter(employe=employee).count() if employee else 0,
            "mes_demandes_en_attente": employee_pending_conges + employee_pending_admin,
            "materiel_employe": CommandeProduit.objects.filter(employe=employee, statut="livree").count() if employee else 0,
        },
    )


@login_required
def admin_dashboard(request):
    return dashboard(request)
