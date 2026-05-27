from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db.models import Q
from django.db.models import Avg, Count, Max, Min
from django.http import FileResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Role

from .forms import (
    DemandeAdministrativeForm,
    DemandeCongeForm,
    DepartementForm,
    EmployeForm,
    ActualiteForm,
    AffectationFormationForm,
    AjustementPointsManuelForm,
    CommandeProduitForm,
    ConversationRHForm,
    FormationForm,
    GestionPosteForm,
    MessageRHForm,
    PlanningBulkForm,
    PlanningShiftForm,
    ProduitForm,
    ReclamationRHForm,
    RemunerationForm,
    TacheEquipeForm,
    TraitementReclamationForm,
    PosteForm,
    ServiceForm,
)
from .models import (
    Actualite,
    AffectationFormation,
    AffectationMateriel,
    CommandeProduit,
    ComptePoints,
    ConversationRH,
    DemandeAdministrative,
    DemandeConge,
    Departement,
    Document,
    Employe,
    Formation,
    HistoriqueAction,
    MessageRH,
    Notification,
    PlanningShift,
    Poste,
    Produit,
    ReclamationRH,
    Remuneration,
    SoldeConge,
    TacheEquipe,
    TransactionPoints,
    Pointage,
    Service,
    StatutDemande,
    TypeConge,
)
from .permissions import can_manage_hr, can_view_employees, has_any_role, role_required
from .services import (
    appliquer_transaction_points,
    approuver_commande,
    audit,
    audit_profile,
    build_hierarchy_tree,
    deduire_solde_conge,
    livrer_commande,
    notify,
    notify_employee,
    notify_rh_and_admin,
    pointer_entree,
    pointer_sortie,
    refuser_ou_annuler_commande,
)


DOCUMENT_EXTENSION_VALIDATOR = FileExtensionValidator(
    allowed_extensions=["pdf", "doc", "docx", "jpg", "jpeg", "png"]
)
PHOTO_EXTENSION_VALIDATOR = FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])
MAX_UPLOAD_SIZE = 5 * 1024 * 1024


def profile(request):
    return getattr(request.user, "profile", None)


def direct_report_filter(manager):
    return Q(pk=manager.pk) | Q(responsable=manager)


def validate_uploaded_file(uploaded_file, validator):
    # TRAITEMENT DOCUMENT — controle taille maximale et extension autorisee.
    if uploaded_file.size > MAX_UPLOAD_SIZE:
        raise ValidationError("La taille du fichier ne doit pas depasser 5 Mo.")
    validator(uploaded_file)


@login_required
def employes_list(request):
    if not can_view_employees(request.user):
        messages.error(request, "Vous n'etes pas autorise a acceder aux employes.")
        return redirect("dashboard")
    search = request.GET.get("search", "").strip()
    employes = accessible_employees(profile(request)).select_related("departement", "service", "poste", "responsable")
    if search:
        employes = employes.filter(
            Q(nom__icontains=search)
            | Q(prenom__icontains=search)
            | Q(email__icontains=search)
            | Q(matricule__icontains=search)
            | Q(departement__libelle__icontains=search)
            | Q(poste__libelle__icontains=search)
        )
    return render(request, "employes/list.html", {"page_title": "Employes", "employes": employes, "search": search})


@login_required
def hierarchy_tree(request):
    departement_id = request.GET.get("departement") or None
    search = request.GET.get("search", "").strip()
    show_all = request.GET.get("afficher") == "tous"
    tree = build_hierarchy_tree(departement_id=departement_id, search=search, show_all=show_all)
    return render(
        request,
        "employes/hierarchy.html",
        {
            "page_title": "Arbre hierarchique",
            "tree": tree,
            "departements": Departement.objects.all(),
            "departement_filtre": departement_id,
            "search": search,
            "show_all": show_all,
        },
    )


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
def position_management(request):
    # TRAITEMENT PERMISSION — seuls ADMIN et RESPONSABLE_RH gerent les postes.
    employes = Employe.objects.filter(actif=True).select_related("departement", "service", "poste", "responsable")
    search = request.GET.get("search", "").strip()
    if search:
        employes = employes.filter(Q(nom__icontains=search) | Q(prenom__icontains=search) | Q(matricule__icontains=search) | Q(email__icontains=search))
    if request.GET.get("departement"):
        employes = employes.filter(departement_id=request.GET["departement"])
    if request.GET.get("poste"):
        employes = employes.filter(poste_id=request.GET["poste"])
    if request.GET.get("manager"):
        employes = employes.filter(responsable_id=request.GET["manager"])
    return render(request, "employes/positions.html", {"page_title": "Gestion des postes", "employes": employes[:80], "departements": Departement.objects.all(), "postes": Poste.objects.all(), "search": search})


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
def position_edit(request, pk):
    employe = get_object_or_404(Employe, pk=pk)
    user_profile = profile(request)
    if user_profile and employe.pk == user_profile.employe_id and user_profile.role != Role.ADMIN:
        messages.error(request, "Un responsable RH ne peut pas modifier sa propre affectation.")
        return redirect("position_management")
    if request.method == "POST":
        form = GestionPosteForm(request.POST, instance=employe)
        if form.is_valid():
            before = f"{employe.poste} / {employe.departement} / {employe.responsable}"
            saved = form.save()
            audit(request, "CHANGEMENT_POSTE", f"{saved.nom_complet}: {before} -> {saved.poste} / {saved.departement} / {saved.responsable}", "Employe", saved.pk)
            notify_employee(saved, "Votre affectation de poste a ete mise a jour.", "/employes/arbre")
            messages.success(request, "Affectation mise a jour.")
            return redirect("position_management")
    else:
        form = GestionPosteForm(instance=employe)
    return render(request, "employes/position_form.html", {"page_title": "Modifier l'affectation", "form": form, "employe": employe})


@login_required
def employe_detail(request, pk):
    if not can_view_employees(request.user):
        messages.error(request, "Vous n'etes pas autorise a acceder aux employes.")
        return redirect("dashboard")
    employe = get_object_or_404(
        accessible_employees(profile(request)).select_related("departement", "service", "poste", "responsable"),
        pk=pk,
    )
    return render(
        request,
        "employes/detail.html",
        {
            "page_title": "Detail employe",
            "employe": employe,
            "conges": employe.conges.all(),
            "documents": employe.documents.all(),
        },
    )


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
def employe_create(request):
    return render(request, "employes/form.html", {"page_title": "Nouvel employe", "form": EmployeForm(), "employe": None})


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
def employe_update(request, pk):
    employe = get_object_or_404(Employe, pk=pk)
    return render(request, "employes/form.html", {"page_title": "Modifier employe", "form": EmployeForm(instance=employe), "employe": employe})


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def employe_save(request):
    pk = request.POST.get("id")
    employe = get_object_or_404(Employe, pk=pk) if pk else None
    form = EmployeForm(request.POST, request.FILES, instance=employe)
    if form.is_valid():
        saved = form.save(commit=False)
        if not saved.pk:
            saved.actif = True
        saved.save()
        photo = request.FILES.get("photoFile")
        if photo:
            try:
                validate_uploaded_file(photo, PHOTO_EXTENSION_VALIDATOR)
            except ValidationError as exc:
                form.add_error(None, exc)
                return render(request, "employes/form.html", {"page_title": "Employe", "form": form, "employe": employe})
            saved.photo = photo
            saved.save(update_fields=["photo"])
        audit(request, "CREATION_EMPLOYE" if not employe else "MODIFICATION_EMPLOYE", f"Employe {saved.nom_complet}", "Employe", saved.pk)
        messages.success(request, "Employe enregistre avec succes.")
        return redirect("employe_detail", pk=saved.pk)
    return render(request, "employes/form.html", {"page_title": "Employe", "form": form, "employe": employe})


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def employe_archive(request, pk):
    employe = get_object_or_404(Employe, pk=pk)
    employe.actif = False
    employe.save(update_fields=["actif", "updated_at"])
    audit(request, "ARCHIVAGE_EMPLOYE", f"Archivage de {employe.nom_complet}", "Employe", employe.pk)
    messages.success(request, "Employe archive avec succes.")
    return redirect("employes_list")


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def employe_photo(request, pk):
    employe = get_object_or_404(Employe, pk=pk)
    photo = request.FILES.get("photoFile")
    if photo:
        try:
            validate_uploaded_file(photo, PHOTO_EXTENSION_VALIDATOR)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect("employe_detail", pk=pk)
        employe.photo = photo
        employe.save(update_fields=["photo", "updated_at"])
        audit(request, "UPLOAD_PHOTO", f"Photo ajoutee pour {employe.nom_complet}", "Employe", employe.pk)
        messages.success(request, "Photo mise a jour.")
    return redirect("employe_detail", pk=pk)


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
def departements_list(request):
    active_tab = request.GET.get("tab", "departements")
    if active_tab not in {"departements", "services", "postes"}:
        active_tab = "departements"
    return render(
        request,
        "departements/list.html",
        {
            "page_title": "Departements",
            "departements": Departement.objects.all(),
            "services": Service.objects.select_related("departement"),
            "postes": Poste.objects.all(),
            "departement_form": DepartementForm(),
            "service_form": ServiceForm(),
            "poste_form": PosteForm(),
            "active_tab": active_tab,
        },
    )


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
def departement_create(request):
    return render(request, "departements/form.html", {"page_title": "Nouveau departement", "form": DepartementForm(), "departement": None})


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
def departement_update(request, pk):
    departement = get_object_or_404(Departement, pk=pk)
    return render(request, "departements/form.html", {"page_title": "Modifier departement", "form": DepartementForm(instance=departement), "departement": departement})


def save_model_form(request, form_class, model_name, success_message, redirect_name):
    pk = request.POST.get("id")
    instance = form_class.Meta.model.objects.filter(pk=pk).first() if pk else None
    form = form_class(request.POST, instance=instance)
    if form.is_valid():
        saved = form.save()
        audit(request, f"SAVE_{model_name.upper()}", f"{model_name} {saved}", model_name, saved.pk)
        messages.success(request, success_message)
    else:
        messages.error(request, "Veuillez corriger les champs obligatoires.")
    return redirect(redirect_name)


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def departement_save(request):
    return save_model_form(request, DepartementForm, "Departement", "Departement enregistre avec succes.", "departements_list")


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def service_save(request):
    return save_model_form(request, ServiceForm, "Service", "Service enregistre avec succes.", "departements_list")


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def poste_save(request):
    return save_model_form(request, PosteForm, "Poste", "Poste enregistre avec succes.", "departements_list")


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def departement_delete(request, pk):
    get_object_or_404(Departement, pk=pk).delete()
    messages.success(request, "Departement supprime.")
    return redirect("departements_list")


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def service_delete(request, pk):
    get_object_or_404(Service, pk=pk).delete()
    messages.success(request, "Service supprime.")
    return redirect("departements_list")


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def poste_delete(request, pk):
    get_object_or_404(Poste, pk=pk).delete()
    messages.success(request, "Poste supprime.")
    return redirect("departements_list")


def conges_for_profile(user_profile):
    # TRAITEMENT PERMISSION CONGE — RH voit tout, manager voit son equipe, employe voit ses demandes.
    if not user_profile or not user_profile.employe:
        return DemandeConge.objects.none()
    if user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH}:
        return DemandeConge.objects.select_related("employe", "traitee_par")
    if user_profile.role == Role.RESPONSABLE_HIERARCHIQUE:
        return DemandeConge.objects.filter(employe__responsable=user_profile.employe).select_related("employe", "traitee_par")
    return DemandeConge.objects.filter(employe=user_profile.employe).select_related("employe", "traitee_par")


@login_required
def conges_list(request):
    demandes = conges_for_profile(profile(request))
    statut = request.GET.get("statut")
    type_conge = request.GET.get("type")
    if statut:
        demandes = demandes.filter(statut=statut)
    if type_conge:
        demandes = demandes.filter(type=type_conge)
    return render(
        request,
        "conges/list.html",
        {"page_title": "Conges & Absences", "demandes": demandes, "statuts": StatutDemande.choices, "types": TypeConge.choices, "statut_filtre": statut, "type_filtre": type_conge},
    )


@login_required
def conge_create(request):
    return render(request, "conges/form.html", {"page_title": "Nouvelle demande de conge", "form": DemandeCongeForm()})


@login_required
@require_POST
def conge_submit(request):
    user_profile = profile(request)
    if not user_profile or not user_profile.employe:
        messages.error(request, "Aucun employe n'est lie a votre compte.")
        return redirect("conges_list")
    form = DemandeCongeForm(request.POST, request.FILES, employee=user_profile.employe)
    if form.is_valid():
        demande = form.save(commit=False)
        demande.employe = user_profile.employe
        demande.statut = StatutDemande.EN_ATTENTE
        demande.date_creation = timezone.now()
        demande.save()
        justificatif = request.FILES.get("justificatif")
        if justificatif:
            try:
                validate_uploaded_file(justificatif, DOCUMENT_EXTENSION_VALIDATOR)
            except ValidationError as exc:
                form.add_error(None, exc)
                demande.delete()
                return render(request, "conges/form.html", {"page_title": "Nouvelle demande de conge", "form": form})
            create_document(request, justificatif, "Justificatif conge", user_profile.employe, None)
        if user_profile.employe.responsable:
            manager_profile = getattr(user_profile.employe.responsable, "utilisateur_profile", None)
            notify(manager_profile, f"Nouvelle demande de conge de {user_profile.employe.nom_complet}", "/conges")
        audit(request, "SOUMISSION_CONGE", f"Demande de conge soumise par {user_profile.employe.nom_complet}", "DemandeConge", demande.pk)
        messages.success(request, "Demande de conge soumise avec succes.")
        return redirect("conges_list")
    return render(request, "conges/form.html", {"page_title": "Nouvelle demande de conge", "form": form})


def can_process_conge(user_profile, demande):
    # TRAITEMENT PERMISSION — seuls RH/Admin ou le responsable direct peuvent traiter un conge.
    if not user_profile or not user_profile.employe:
        return False
    if user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH}:
        return True
    return user_profile.role == Role.RESPONSABLE_HIERARCHIQUE and demande.employe.responsable_id == user_profile.employe_id


@role_required(Role.ADMIN, Role.RESPONSABLE_RH, Role.RESPONSABLE_HIERARCHIQUE)
@require_POST
def conge_validate(request, pk):
    demande = get_object_or_404(DemandeConge, pk=pk)
    user_profile = profile(request)
    if not can_process_conge(user_profile, demande):
        messages.error(request, "Vous n'etes pas autorise a traiter cette demande.")
        return redirect("conges_list")
    if demande.statut != StatutDemande.EN_ATTENTE:
        messages.error(request, "Cette demande a deja ete traitee.")
        return redirect("conges_list")
    # TRAITEMENT SOLDE CONGE — deduction uniquement au moment de la validation.
    try:
        deduire_solde_conge(demande, user_profile)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("conges_list")
    demande.statut = StatutDemande.VALIDEE
    demande.traitee_par = user_profile.employe
    demande.date_traitement = timezone.now()
    demande.commentaire_reponse = request.POST.get("commentaire", "")
    demande.save()
    notify_employee(demande.employe, "Votre demande de conge a ete validee", "/conges")
    audit(request, "VALIDATION_CONGE", "Validation de la demande de conge", "DemandeConge", demande.pk)
    messages.success(request, "Demande validee.")
    return redirect("conges_list")


@role_required(Role.ADMIN, Role.RESPONSABLE_RH, Role.RESPONSABLE_HIERARCHIQUE)
@require_POST
def conge_refuse(request, pk):
    demande = get_object_or_404(DemandeConge, pk=pk)
    user_profile = profile(request)
    if not can_process_conge(user_profile, demande):
        messages.error(request, "Vous n'etes pas autorise a traiter cette demande.")
        return redirect("conges_list")
    if demande.statut != StatutDemande.EN_ATTENTE:
        messages.error(request, "Cette demande a deja ete traitee.")
        return redirect("conges_list")
    demande.statut = StatutDemande.REFUSEE
    demande.traitee_par = user_profile.employe
    demande.date_traitement = timezone.now()
    demande.commentaire_reponse = request.POST.get("commentaire", "")
    demande.save()
    notify_employee(demande.employe, "Votre demande de conge a ete refusee", "/conges")
    audit(request, "REFUS_CONGE", "Refus de la demande de conge", "DemandeConge", demande.pk)
    messages.success(request, "Demande refusee.")
    return redirect("conges_list")


@login_required
@require_POST
def conge_cancel(request, pk):
    user_profile = profile(request)
    demande = get_object_or_404(DemandeConge, pk=pk)
    if not user_profile or demande.employe_id != user_profile.employe_id or demande.statut not in {StatutDemande.EN_ATTENTE, StatutDemande.VALIDEE}:
        messages.error(request, "Cette demande ne peut pas etre annulee.")
        return redirect("conges_list")
    was_validated = demande.statut == StatutDemande.VALIDEE
    demande.statut = StatutDemande.CLOTUREE
    demande.save(update_fields=["statut", "updated_at"])
    if was_validated:
        # TRAITEMENT SOLDE CONGE — remboursement si le conge annule etait deja valide.
        from .services import rembourser_solde_conge
        rembourser_solde_conge(demande, user_profile)
    audit(request, "ANNULATION_CONGE", "Annulation de la demande de conge", "DemandeConge", demande.pk)
    messages.success(request, "Demande annulee.")
    return redirect("conges_list")


def demandes_for_profile(user_profile):
    if not user_profile or not user_profile.employe:
        return DemandeAdministrative.objects.none()
    if user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH}:
        return DemandeAdministrative.objects.select_related("employe", "traitee_par").prefetch_related("documents")
    return DemandeAdministrative.objects.filter(employe=user_profile.employe).select_related("employe", "traitee_par").prefetch_related("documents")


@login_required
def demandes_list(request):
    demandes = demandes_for_profile(profile(request))
    statut = request.GET.get("statut")
    if statut:
        demandes = demandes.filter(statut=statut)
    return render(request, "demandes/list.html", {"page_title": "Demandes Admin", "demandes": demandes, "statuts": StatutDemande.choices, "statut_filtre": statut})


@login_required
def demande_create(request):
    return render(request, "demandes/form.html", {"page_title": "Nouvelle demande administrative", "form": DemandeAdministrativeForm()})


@login_required
@require_POST
def demande_submit(request):
    user_profile = profile(request)
    if not user_profile or not user_profile.employe:
        messages.error(request, "Aucun employe n'est lie a votre compte.")
        return redirect("demandes_list")
    form = DemandeAdministrativeForm(request.POST, request.FILES)
    if form.is_valid():
        demande = form.save(commit=False)
        demande.employe = user_profile.employe
        demande.statut = StatutDemande.EN_ATTENTE
        demande.date_creation = timezone.now()
        demande.save()
        piece_jointe = request.FILES.get("pieceJointe")
        if piece_jointe:
            try:
                validate_uploaded_file(piece_jointe, DOCUMENT_EXTENSION_VALIDATOR)
            except ValidationError as exc:
                form.add_error(None, exc)
                demande.delete()
                return render(request, "demandes/form.html", {"page_title": "Nouvelle demande administrative", "form": form})
            create_document(request, piece_jointe, "Demande administrative", user_profile.employe, demande)
        notify_rh_and_admin(f"Nouvelle demande administrative de {user_profile.employe.nom_complet}", "/demandes")
        audit(request, "SOUMISSION_DEMANDE_ADMIN", "Demande administrative soumise", "DemandeAdministrative", demande.pk)
        messages.success(request, "Demande administrative soumise avec succes.")
        return redirect("demandes_list")
    return render(request, "demandes/form.html", {"page_title": "Nouvelle demande administrative", "form": form})


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def demande_process(request, pk):
    demande = get_object_or_404(DemandeAdministrative, pk=pk)
    user_profile = profile(request)
    if demande.statut in {StatutDemande.VALIDEE, StatutDemande.REFUSEE, StatutDemande.CLOTUREE}:
        messages.error(request, "Cette demande a deja ete finalisee.")
        return redirect("demandes_list")
    if request.POST.get("statut") not in {StatutDemande.EN_COURS, StatutDemande.VALIDEE, StatutDemande.REFUSEE, StatutDemande.CLOTUREE}:
        messages.error(request, "Statut invalide.")
        return redirect("demandes_list")
    demande.reponse = request.POST.get("reponse", "")
    demande.statut = request.POST.get("statut")
    demande.traitee_par = user_profile.employe
    demande.date_traitement = timezone.now()
    demande.save()
    notify_employee(demande.employe, "Votre demande administrative a ete traitee", "/demandes")
    audit(request, "TRAITEMENT_DEMANDE_ADMIN", "Traitement d'une demande administrative", "DemandeAdministrative", demande.pk)
    messages.success(request, "Demande traitee avec succes.")
    return redirect("demandes_list")


def create_document(request, uploaded_file, categorie, employe, demande_admin):
    document = Document.objects.create(
        fichier=uploaded_file,
        nom_fichier=Path(uploaded_file.name).name,
        nom_original=Path(uploaded_file.name).name,
        categorie=categorie or "General",
        taille=uploaded_file.size,
        employe=employe,
        demande_admin=demande_admin,
        uploade_par=request.user,
    )
    document.chemin_fichier = document.fichier.path
    document.nom_fichier = Path(document.fichier.name).name
    document.save(update_fields=["chemin_fichier", "nom_fichier"])
    audit(request, "UPLOAD_DOCUMENT", f"Televersement du document {document.nom_original}", "Document", document.pk)
    return document


def accessible_employees(user_profile):
    if not user_profile or not user_profile.employe:
        return Employe.objects.none()
    if user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH}:
        return Employe.objects.filter(actif=True)
    if user_profile.role == Role.RESPONSABLE_HIERARCHIQUE:
        return Employe.objects.filter(direct_report_filter(user_profile.employe), actif=True)
    return Employe.objects.filter(pk=user_profile.employe_id)


def accessible_documents(user_profile):
    # TRAITEMENT PERMISSION DOCUMENT — limite les documents selon role et lien employe.
    if not user_profile or not user_profile.employe:
        return Document.objects.none()
    if user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH}:
        return Document.objects.select_related("employe", "uploade_par")
    if user_profile.role == Role.RESPONSABLE_HIERARCHIQUE:
        return Document.objects.filter(employe__in=accessible_employees(user_profile)).select_related("employe", "uploade_par")
    return Document.objects.filter(employe=user_profile.employe).select_related("employe", "uploade_par")


@login_required
def documents_list(request):
    user_profile = profile(request)
    documents = accessible_documents(user_profile)
    categorie = request.GET.get("categorie", "").strip()
    employe_id = request.GET.get("employeId")
    if categorie:
        documents = documents.filter(categorie__iexact=categorie)
    if employe_id:
        documents = documents.filter(employe_id=employe_id)
    return render(
        request,
        "documents/list.html",
        {"page_title": "Documents", "documents": documents, "employes": accessible_employees(user_profile), "categorie_filtre": categorie, "employe_filtre": employe_id},
    )


@login_required
@require_POST
def document_upload(request):
    user_profile = profile(request)
    if not user_profile:
        messages.error(request, "Aucun profil n'est lie a votre compte.")
        return redirect("documents_list")
    uploaded = request.FILES.get("file")
    if not uploaded:
        messages.error(request, "Le fichier est obligatoire.")
        return redirect("documents_list")
    try:
        validate_uploaded_file(uploaded, DOCUMENT_EXTENSION_VALIDATOR)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("documents_list")
    employe = user_profile.employe
    if user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH} and request.POST.get("employeId"):
        employe = Employe.objects.filter(pk=request.POST.get("employeId")).first()
    create_document(request, uploaded, request.POST.get("categorie"), employe, None)
    messages.success(request, "Document televerse avec succes.")
    return redirect("documents_list")


@login_required
def document_download(request, pk):
    document = get_object_or_404(Document, pk=pk)
    # TRAITEMENT SECURITE DOCUMENT — protege aussi le telechargement par URL directe.
    if not accessible_documents(profile(request)).filter(pk=pk).exists():
        return HttpResponseForbidden()
    return FileResponse(document.fichier.open("rb"), as_attachment=True, filename=document.nom_original)


@login_required
@require_POST
def document_delete(request, pk):
    document = get_object_or_404(Document, pk=pk)
    user_profile = profile(request)
    if not (user_profile and user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH}) and document.uploade_par_id != request.user.id:
        messages.error(request, "Vous n'etes pas autorise a supprimer ce document.")
        return redirect("documents_list")
    document.fichier.delete(save=False)
    document.delete()
    messages.success(request, "Document supprime.")
    return redirect("documents_list")


@login_required
def notifications_list(request):
    user_profile = profile(request)
    notifications = user_profile.notifications.all() if user_profile else Notification.objects.none()
    return render(request, "notifications/list.html", {"page_title": "Notifications", "notifications": notifications})


@login_required
@require_POST
def notification_read(request, pk):
    user_profile = profile(request)
    notification = get_object_or_404(Notification, pk=pk, destinataire=user_profile)
    notification.lue = True
    notification.save(update_fields=["lue", "updated_at"])
    messages.success(request, "Notification marquee comme lue.")
    return redirect("notifications_list")


@login_required
@require_POST
def notifications_read_all(request):
    user_profile = profile(request)
    if user_profile:
        user_profile.notifications.filter(lue=False).update(lue=True)
        messages.success(request, "Toutes les notifications sont marquees comme lues.")
    return redirect("notifications_list")


@login_required
def attendance_view(request):
    user_profile = profile(request)
    if not user_profile or not user_profile.employe:
        return redirect("dashboard")
    qs = Pointage.objects.select_related("employe", "employe__departement")
    # TRAITEMENT PERMISSION POINTAGE — filtre la presence selon role.
    if user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH}:
        pointages = qs.all()
    elif user_profile.role == Role.RESPONSABLE_HIERARCHIQUE:
        pointages = qs.filter(Q(employe=user_profile.employe) | Q(employe__responsable=user_profile.employe))
    else:
        pointages = qs.filter(employe=user_profile.employe)
    today = timezone.localdate()
    today_pointages = pointages.filter(date=today)
    shift_today = (
        PlanningShift.objects.filter(
            employe=user_profile.employe,
            statut="publie",
            date_debut__date__lte=today,
            date_fin__date__gte=today,
        )
        .order_by("date_debut")
        .first()
    )
    total_hours_today = sum(float(pointage.total_heures or 0) for pointage in today_pointages)
    planned_today = PlanningShift.objects.filter(date_debut__date__lte=today, date_fin__date__gte=today).exclude(statut="annule")
    if user_profile.role not in {Role.ADMIN, Role.RESPONSABLE_RH}:
        planned_today = planned_today.filter(employe__in=accessible_employees(user_profile))
    return render(
        request,
        "pointage/index.html",
        {
            "page_title": "Presence / Pointage",
            "pointages": pointages[:80],
            "today": pointages.filter(employe=user_profile.employe, date=today).first(),
            "shift_today": shift_today,
            "today_pointages_count": today_pointages.count(),
            "today_retards_count": today_pointages.filter(statut="retard").count(),
            "today_open_count": today_pointages.filter(heure_sortie__isnull=True).count(),
            "today_total_hours": total_hours_today,
            "planned_today_count": planned_today.count(),
            "compte": ComptePoints.objects.get_or_create(employe=user_profile.employe)[0],
        },
    )


@login_required
@require_POST
def attendance_checkin(request):
    try:
        pointer_entree(profile(request).employe)
        messages.success(request, "Entree pointee avec succes.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("attendance")


@login_required
@require_POST
def attendance_checkout(request):
    try:
        pointer_sortie(profile(request).employe)
        messages.success(request, "Sortie pointee avec succes.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("attendance")


def planning_for_profile(user_profile):
    qs = PlanningShift.objects.select_related("employe", "departement", "service")
    if not user_profile or not user_profile.employe:
        return qs.none()
    if user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH}:
        return qs
    if user_profile.role == Role.RESPONSABLE_HIERARCHIQUE:
        return qs.filter(Q(employe=user_profile.employe) | Q(employe__responsable=user_profile.employe) | Q(employe__isnull=True))
    return qs.filter(Q(employe=user_profile.employe) | Q(employe__isnull=True, statut="ouvert"))


def employees_for_planning_scope(cleaned):
    scope = cleaned["scope"]
    employees = Employe.objects.filter(actif=True).select_related("departement", "service")
    if scope == "company":
        return employees
    if scope == "departement":
        return employees.filter(departement=cleaned["departement"])
    if scope == "service":
        return employees.filter(service=cleaned["service"])
    return cleaned["employes"]


def planning_board(shifts):
    groups = {}
    for shift in shifts:
        departement = shift.departement or (shift.employe.departement if shift.employe else None)
        service = shift.service or (shift.employe.service if shift.employe else None)
        key = (
            departement.pk if departement else 0,
            service.pk if service else 0,
        )
        if key not in groups:
            groups[key] = {
                "departement": departement.libelle if departement else "Sans departement",
                "service": service.libelle if service else "Sans service",
                "shifts": [],
            }
        groups[key]["shifts"].append(shift)
    return sorted(groups.values(), key=lambda item: (item["departement"], item["service"]))


@login_required
def planning(request):
    user_profile = profile(request)
    shifts = planning_for_profile(user_profile)
    today = timezone.localdate()
    date_debut = request.GET.get("date_debut") or today.isoformat()
    date_fin = request.GET.get("date_fin") or (today + timezone.timedelta(days=14)).isoformat()
    statut = request.GET.get("statut", "").strip()
    employe_id = request.GET.get("employe", "").strip()
    if date_debut:
        shifts = shifts.filter(date_fin__date__gte=date_debut)
    if date_fin:
        shifts = shifts.filter(date_debut__date__lte=date_fin)
    if statut:
        shifts = shifts.filter(statut=statut)
    if employe_id:
        shifts = shifts.filter(employe_id=employe_id)
    can_manage = user_profile and user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH}
    shifts = shifts.order_by("departement__libelle", "service__libelle", "date_debut", "employe__nom")
    return render(
        request,
        "planning/index.html",
        {
            "page_title": "Planning / Shifts",
            "shifts": shifts[:200],
            "planning_groups": planning_board(shifts[:200]),
            "form": PlanningBulkForm() if can_manage else None,
            "employes": accessible_employees(user_profile),
            "departements": Departement.objects.all(),
            "services": Service.objects.select_related("departement"),
            "statuts": PlanningShift.STATUTS,
            "date_debut": date_debut,
            "date_fin": date_fin,
            "statut_filtre": statut,
            "employe_filtre": employe_id,
            "can_manage": can_manage,
        },
    )


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def planning_create(request):
    form = PlanningBulkForm(request.POST)
    if form.is_valid():
        created = 0
        skipped = []
        employees = list(employees_for_planning_scope(form.cleaned_data))
        for employe in employees:
            shift = PlanningShift(
                titre=form.cleaned_data["titre"],
                employe=employe,
                departement=employe.departement or form.cleaned_data.get("departement"),
                service=employe.service or form.cleaned_data.get("service"),
                lieu=form.cleaned_data["lieu"],
                date_debut=form.cleaned_data["date_debut"],
                date_fin=form.cleaned_data["date_fin"],
                pause_minutes=form.cleaned_data["pause_minutes"],
                statut=form.cleaned_data["statut"],
                notes=form.cleaned_data["notes"],
                cree_par=profile(request),
            )
            try:
                shift.full_clean()
                shift.save()
                created += 1
                notify_employee(employe, f"Nouveau shift planifie: {shift.titre}", "/planning")
            except ValidationError as exc:
                skipped.append(f"{employe.nom_complet}: {' '.join(exc.messages)}")
        audit(request, "CREATION_PLANNING_GROUPE", f"{created} shift(s) crees via {form.cleaned_data['scope']}", "PlanningShift", None)
        if created:
            messages.success(request, f"{created} shift(s) ajoute(s) au planning.")
        if skipped:
            messages.warning(request, f"{len(skipped)} employe(s) ignore(s) pour conflit de planning ou conge.")
    else:
        messages.error(request, "Planning invalide: veuillez verifier les dates, conges et chevauchements.")
    return redirect("planning")


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def planning_status(request, pk):
    shift = get_object_or_404(PlanningShift, pk=pk)
    statut = request.POST.get("statut")
    if statut not in dict(PlanningShift.STATUTS):
        messages.error(request, "Statut de shift invalide.")
        return redirect("planning")
    shift.statut = statut
    try:
        shift.full_clean()
        shift.save(update_fields=["statut", "updated_at"])
        if shift.employe and statut in {"publie", "annule"}:
            notify_employee(shift.employe, f"Votre planning a ete mis a jour: {shift.titre}", "/planning")
        audit(request, "STATUT_SHIFT", f"{shift} -> {statut}", "PlanningShift", shift.pk)
        messages.success(request, "Planning mis a jour.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("planning")


def tasks_for_profile(user_profile):
    qs = TacheEquipe.objects.select_related("employe", "departement", "shift")
    if not user_profile or not user_profile.employe:
        return qs.none()
    if user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH}:
        return qs
    if user_profile.role == Role.RESPONSABLE_HIERARCHIQUE:
        return qs.filter(Q(employe=user_profile.employe) | Q(employe__responsable=user_profile.employe) | Q(departement=user_profile.employe.departement))
    return qs.filter(Q(employe=user_profile.employe) | Q(departement=user_profile.employe.departement, employe__isnull=True))


@login_required
def team_tasks(request):
    user_profile = profile(request)
    can_manage = user_profile and user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH, Role.RESPONSABLE_HIERARCHIQUE}
    tasks = tasks_for_profile(user_profile)
    statut = request.GET.get("statut", "").strip()
    if statut:
        tasks = tasks.filter(statut=statut)
    return render(
        request,
        "taches/index.html",
        {
            "page_title": "Taches equipe",
            "tasks": tasks[:200],
            "form": TacheEquipeForm() if can_manage else None,
            "statuts": TacheEquipe.STATUTS,
            "statut_filtre": statut,
            "can_manage": can_manage,
        },
    )


@role_required(Role.ADMIN, Role.RESPONSABLE_RH, Role.RESPONSABLE_HIERARCHIQUE)
@require_POST
def task_create(request):
    form = TacheEquipeForm(request.POST)
    if form.is_valid():
        task = form.save(commit=False)
        task.cree_par = profile(request)
        task.full_clean()
        task.save()
        if task.employe:
            notify_employee(task.employe, f"Nouvelle tache: {task.titre}", "/taches")
        messages.success(request, "Tache creee.")
    else:
        messages.error(request, "Tache invalide.")
    return redirect("team_tasks")


@login_required
@require_POST
def task_status(request, pk):
    user_profile = profile(request)
    task = get_object_or_404(tasks_for_profile(user_profile), pk=pk)
    statut = request.POST.get("statut")
    if statut not in dict(TacheEquipe.STATUTS):
        messages.error(request, "Statut de tache invalide.")
        return redirect("team_tasks")
    task.statut = statut
    if statut == "terminee":
        task.terminee_par = user_profile
        task.date_completion = timezone.now()
    task.full_clean()
    task.save()
    messages.success(request, "Tache mise a jour.")
    return redirect("team_tasks")


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
def formations_admin(request):
    if request.method == "POST":
        form = AffectationFormationForm(request.POST)
        if form.is_valid():
            formation = form.cleaned_data["formation"]
            employe = form.cleaned_data["employe"]
            existing_active = AffectationFormation.objects.filter(formation=formation, employe=employe, statut__in=["assignee", "en_cours"]).first()
            if existing_active:
                messages.warning(request, "Cette formation est deja affectee a cet employe.")
            else:
                aff = AffectationFormation.objects.create(
                    formation=formation,
                    employe=employe,
                    assigne_par=profile(request),
                    date_limite=form.cleaned_data["date_limite"],
                )
                notify_employee(employe, f"Nouvelle formation assignee: {formation.titre}", "/formations/mes-formations")
                audit(request, "AFFECTATION_FORMATION", f"Formation assignee: {formation.titre} a {employe.nom_complet}", "AffectationFormation", aff.pk)
                messages.success(request, "Formation assignee.")
            return redirect("formations_admin")
    else:
        form = AffectationFormationForm()
    return render(request, "formations/admin.html", {"page_title": "Affectation des formations", "form": form, "formations": Formation.objects.all(), "affectations": AffectationFormation.objects.select_related("formation", "employe").order_by("-date_affectation", "-id"), "formation_form": FormationForm()})


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def formation_create(request):
    form = FormationForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, "Formation creee.")
    else:
        messages.error(request, "Formation invalide.")
    return redirect("formations_admin")


@login_required
def my_trainings(request):
    user_profile = profile(request)
    qs = AffectationFormation.objects.filter(employe=user_profile.employe).select_related("formation") if user_profile and user_profile.employe else AffectationFormation.objects.none()
    return render(request, "formations/me.html", {"page_title": "Mes formations", "affectations": qs})


@login_required
@require_POST
def training_status(request, pk):
    aff = get_object_or_404(AffectationFormation, pk=pk, employe=profile(request).employe)
    if aff.statut == "annulee":
        messages.error(request, "Cette formation a ete annulee par les RH.")
        return redirect("my_trainings")
    statut = request.POST.get("statut")
    if statut in {"en_cours", "terminee"}:
        was_awarded = aff.points_attribues
        aff.statut = statut
        if statut == "terminee":
            aff.date_completion = timezone.localdate()
        aff.full_clean()
        aff.save()
        # TRAITEMENT POINTS FORMATION — attribue les points une seule fois apres completion.
        if statut == "terminee" and not was_awarded and aff.formation.points_recompense > 0:
            appliquer_transaction_points(aff.employe, "gain", aff.formation.points_recompense, "formation", f"Formation terminee: {aff.formation.titre}", profile(request), f"AffectationFormation:{aff.pk}")
            aff.points_attribues = True
            aff.save(update_fields=["points_attribues"])
            notify_employee(aff.employe, f"Points attribues pour la formation {aff.formation.titre}.", "/pointage")
            audit(request, "FORMATION_TERMINEE", f"Formation terminee: {aff.formation.titre}", "AffectationFormation", aff.pk)
        messages.success(request, "Formation mise a jour.")
    return redirect("my_trainings")


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def formation_assignment_status(request, pk):
    aff = get_object_or_404(AffectationFormation.objects.select_related("formation", "employe"), pk=pk)
    statut = request.POST.get("statut")
    if statut not in {"assignee", "en_cours", "terminee", "en_retard", "annulee"}:
        messages.error(request, "Statut de formation invalide.")
        return redirect("formations_admin")
    was_awarded = aff.points_attribues
    aff.statut = statut
    if statut == "terminee" and not aff.date_completion:
        aff.date_completion = timezone.localdate()
    aff.full_clean()
    aff.save()
    if statut == "annulee":
        notify_employee(aff.employe, f"La formation {aff.formation.titre} a ete annulee par les RH.", "/formations/mes-formations")
    if statut == "terminee" and not was_awarded and aff.formation.points_recompense > 0:
        appliquer_transaction_points(aff.employe, "gain", aff.formation.points_recompense, "formation", f"Formation terminee par RH: {aff.formation.titre}", profile(request), f"AffectationFormation:{aff.pk}")
        aff.points_attribues = True
        aff.save(update_fields=["points_attribues"])
        notify_employee(aff.employe, f"Points attribues pour la formation {aff.formation.titre}.", "/pointage")
    audit(request, "MISE_A_JOUR_FORMATION", f"{aff.formation.titre} - {aff.employe.nom_complet} - {statut}", "AffectationFormation", aff.pk)
    messages.success(request, "Affectation de formation mise a jour.")
    return redirect("formations_admin")


def conversations_for_profile(user_profile):
    if user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH}:
        return ConversationRH.objects.select_related("employe", "responsable_rh")
    return ConversationRH.objects.filter(employe=user_profile.employe)


@login_required
def rh_messages(request):
    user_profile = profile(request)
    return render(request, "messages_rh/list.html", {"page_title": "Contact RH / Messages RH", "conversations": conversations_for_profile(user_profile), "form": ConversationRHForm()})


@login_required
@require_POST
def rh_conversation_create(request):
    user_profile = profile(request)
    form = ConversationRHForm(request.POST)
    if form.is_valid():
        conv = ConversationRH.objects.create(sujet=form.cleaned_data["sujet"], employe=user_profile.employe, statut="en_attente")
        MessageRH.objects.create(conversation=conv, expediteur=user_profile, contenu=form.cleaned_data["contenu"])
        notify_rh_and_admin(f"Nouveau message RH de {user_profile.employe.nom_complet}", "/messages-rh")
        messages.success(request, "Message envoye aux RH.")
    else:
        messages.error(request, "Message invalide.")
    return redirect("rh_messages")


@login_required
def rh_conversation_detail(request, pk):
    user_profile = profile(request)
    conv = get_object_or_404(conversations_for_profile(user_profile), pk=pk)
    if request.method == "POST":
        form = MessageRHForm(request.POST)
        if form.is_valid():
            msg = form.save(commit=False)
            msg.conversation = conv
            msg.expediteur = user_profile
            if user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH}:
                msg.destinataire = getattr(conv.employe, "utilisateur_profile", None)
            msg.save()
            conv.date_derniere_reponse = timezone.now()
            if user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH}:
                conv.responsable_rh = user_profile
                conv.statut = "ouverte"
                conv.save(update_fields=["date_derniere_reponse", "responsable_rh", "statut"])
                notify_employee(conv.employe, "Nouvelle reponse RH.", f"/messages-rh/{conv.pk}")
            else:
                conv.statut = "en_attente"
                conv.save(update_fields=["date_derniere_reponse", "statut"])
                notify_rh_and_admin("Nouvelle reponse dans une conversation RH.", f"/messages-rh/{conv.pk}")
            return redirect("rh_conversation_detail", pk=pk)
    else:
        form = MessageRHForm()
    return render(request, "messages_rh/detail.html", {"page_title": "Conversation RH", "conversation": conv, "form": form})


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
def payroll_analytics(request):
    remunerations = Remuneration.objects.filter(actif=True).select_related("employe", "employe__departement", "employe__poste")
    if request.GET.get("departement"):
        remunerations = remunerations.filter(employe__departement_id=request.GET["departement"])
    salaires = list(remunerations.values_list("salaire_base", flat=True))
    mediane = sorted(salaires)[len(salaires) // 2] if salaires else 0
    stats = remunerations.aggregate(min=Min("salaire_base"), max=Max("salaire_base"), avg=Avg("salaire_base"))
    par_departement = remunerations.values("employe__departement__libelle").annotate(total=Count("id"), moyenne=Avg("salaire_base"), minimum=Min("salaire_base"), maximum=Max("salaire_base"))
    par_poste = remunerations.values("employe__poste__libelle").annotate(total=Count("id"), moyenne=Avg("salaire_base"), minimum=Min("salaire_base"), maximum=Max("salaire_base"))[:20]
    return render(request, "paie/analytics.html", {"page_title": "Paie et analyses salariales", "remunerations": remunerations[:100], "stats": stats, "mediane": mediane, "par_departement": par_departement, "par_poste": par_poste, "departements": Departement.objects.all()})


@role_required(Role.ADMIN)
def salary_edit(request, pk):
    remuneration = get_object_or_404(Remuneration, pk=pk)
    if request.method == "POST":
        before = f"{remuneration.salaire_base} {remuneration.devise} + prime {remuneration.prime}"
        form = RemunerationForm(request.POST, instance=remuneration)
        if form.is_valid():
            saved = form.save(commit=False)
            saved.cree_par = profile(request)
            saved.save()
            audit(request, "MISE_A_JOUR_SALAIRE", f"{saved.employe.nom_complet}: {before} -> {saved.salaire_base} {saved.devise} + prime {saved.prime}", "Remuneration", saved.pk)
            messages.success(request, "Remuneration mise a jour.")
            return redirect("payroll_analytics")
    else:
        form = RemunerationForm(instance=remuneration)
    return render(request, "paie/form.html", {"page_title": "Modifier la remuneration", "form": form, "remuneration": remuneration})


@login_required
def news_list(request):
    user_profile = profile(request)
    news = Actualite.objects.filter(statut="publiee")
    if user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH}:
        news = Actualite.objects.all()
    return render(request, "actualites/list.html", {"page_title": "Actualites / Newsletter", "actualites": news, "form": ActualiteForm() if user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH} else None})


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def news_create(request):
    form = ActualiteForm(request.POST, request.FILES)
    if form.is_valid():
        news = form.save(commit=False)
        news.auteur = profile(request)
        if news.statut == "publiee" and not news.date_publication:
            news.date_publication = timezone.now()
        news.full_clean()
        news.save()
        audit(request, "PUBLICATION_ACTUALITE", news.titre, "Actualite", news.pk)
        messages.success(request, "Actualite enregistree.")
    else:
        messages.error(request, "Actualite invalide.")
    return redirect("news_list")


@login_required
def shop(request):
    user_profile = profile(request)
    employe = user_profile.employe
    if request.method == "POST":
        form = CommandeProduitForm(request.POST, employe=employe)
        if form.is_valid():
            # TRAITEMENT BOUTIQUE — creation d'une commande en attente apres validation stock/points.
            commande = form.save(commit=False)
            commande.employe = employe
            commande.cout_total_points = commande.produit.cout_points * commande.quantite
            commande.full_clean()
            commande.save()
            notify_rh_and_admin(f"Nouvelle commande materiel de {employe.nom_complet}", "/boutique")
            messages.success(request, "Commande envoyee.")
            return redirect("shop")
    else:
        form = CommandeProduitForm(employe=employe)
    commandes = CommandeProduit.objects.filter(employe=employe).select_related("produit")
    if user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH}:
        commandes = CommandeProduit.objects.select_related("employe", "produit")
    is_rh = user_profile.role in {Role.ADMIN, Role.RESPONSABLE_RH}
    materiels = AffectationMateriel.objects.select_related("employe", "produit") if is_rh else AffectationMateriel.objects.filter(employe=employe).select_related("produit")
    transactions = TransactionPoints.objects.filter(employe=employe, source="boutique")[:50]
    return render(request, "boutique/index.html", {"page_title": "Boutique employe / Materiel", "produits": Produit.objects.filter(actif=True), "form": form, "commandes": commandes, "compte": ComptePoints.objects.get_or_create(employe=employe)[0], "produit_form": ProduitForm() if is_rh else None, "materiels": materiels[:80], "transactions_boutique": transactions, "is_rh": is_rh})


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def product_create(request):
    form = ProduitForm(request.POST, request.FILES)
    if form.is_valid():
        form.save()
        messages.success(request, "Produit enregistre.")
    else:
        messages.error(request, "Produit invalide.")
    return redirect("shop")


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def order_process(request, pk):
    commande = get_object_or_404(CommandeProduit, pk=pk)
    try:
        action = request.POST.get("action")
        if action == "approuver":
            approuver_commande(commande, profile(request))
        elif action == "livrer":
            livrer_commande(commande, profile(request))
        elif action in {"refuser", "annuler"}:
            refuser_ou_annuler_commande(commande, "refusee" if action == "refuser" else "annulee", profile(request), request.POST.get("motif", ""))
        messages.success(request, "Commande traitee.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("shop")


@login_required
def reclamations(request):
    user_profile = profile(request)
    qs = ReclamationRH.objects.select_related("employe", "traite_par")
    if user_profile.role not in {Role.ADMIN, Role.RESPONSABLE_RH}:
        qs = qs.filter(employe=user_profile.employe)
    return render(request, "reclamations/list.html", {"page_title": "Reclamations RH", "reclamations": qs, "form": ReclamationRHForm()})


@login_required
@require_POST
def reclamation_create(request):
    user_profile = profile(request)
    form = ReclamationRHForm(request.POST)
    if form.is_valid():
        rec = form.save(commit=False)
        rec.employe = user_profile.employe
        rec.save()
        notify_rh_and_admin(f"Nouvelle reclamation de {rec.employe.nom_complet}", "/reclamations")
        messages.success(request, "Reclamation envoyee.")
    else:
        messages.error(request, "Reclamation invalide.")
    return redirect("reclamations")


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
@require_POST
def reclamation_process(request, pk):
    rec = get_object_or_404(ReclamationRH, pk=pk)
    form = TraitementReclamationForm(request.POST, instance=rec)
    if form.is_valid():
        action = form.cleaned_data["action"]
        rec.reponse_rh = form.cleaned_data["reponse_rh"]
        rec.date_traitement = timezone.now()
        rec.traite_par = profile(request)
        rec.points_accordes = form.cleaned_data["points_accordes"] or 0
        rec.statut = {"refuser": "refusee", "accepter": "acceptee", "points": "acceptee", "infos": "en_cours", "cloturer": "cloturee"}[action]
        # TRAITEMENT RECLAMATION/POINTS — evite le double ajout grace a action_points_appliquee.
        if action == "points" and not rec.action_points_appliquee:
            appliquer_transaction_points(rec.employe, "gain", rec.points_accordes, "reclamation", f"Compensation reclamation: {rec.sujet}", profile(request), f"ReclamationRH:{rec.pk}")
            rec.action_points_appliquee = True
        rec.save()
        notify_employee(rec.employe, "Votre reclamation RH a ete traitee.", "/reclamations")
        audit(request, "TRAITEMENT_RECLAMATION", rec.sujet, "ReclamationRH", rec.pk)
        messages.success(request, "Reclamation traitee.")
    else:
        messages.error(request, "Traitement invalide.")
    return redirect("reclamations")


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
def manual_points(request):
    if request.method == "POST":
        form = AjustementPointsManuelForm(request.POST)
        if form.is_valid():
            adj = form.save(commit=False)
            adj.cree_par = profile(request)
            # TRAITEMENT PERMISSION POINTS — un RH ne peut pas ajuster ses propres points.
            if adj.employe_id == profile(request).employe_id and profile(request).role != Role.ADMIN:
                messages.error(request, "Un RH ne peut pas ajuster ses propres points.")
                return redirect("manual_points")
            type_tx = "gain" if adj.type_adjustement in {"ajout", "remboursement"} else "deduction"
            try:
                appliquer_transaction_points(adj.employe, type_tx, adj.nombre_points, "manuel", adj.motif_obligatoire, profile(request))
                adj.save()
                notify_employee(adj.employe, "Votre solde de points a ete ajuste par les RH.", "/pointage")
                messages.success(request, "Ajustement enregistre.")
                return redirect("manual_points")
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
        else:
            messages.error(request, "Ajustement invalide.")
    return render(request, "points/manual.html", {"page_title": "Correction manuelle des points", "form": AjustementPointsManuelForm(), "transactions": []})


@role_required(Role.ADMIN, Role.RESPONSABLE_RH)
def audit_history(request):
    # TRAITEMENT AUDIT — consultation filtree de l'historique par role, action, module et dates.
    actions = HistoriqueAction.objects.select_related("utilisateur", "utilisateur__user")
    search = request.GET.get("search", "").strip()
    role = request.GET.get("role", "").strip()
    action_type = request.GET.get("action", "").strip()
    module = request.GET.get("module", "").strip()
    date_debut = request.GET.get("date_debut", "").strip()
    date_fin = request.GET.get("date_fin", "").strip()
    if search:
        actions = actions.filter(Q(details__icontains=search) | Q(action__icontains=search) | Q(entite_concernee__icontains=search) | Q(utilisateur__user__username__icontains=search))
    if role:
        actions = actions.filter(utilisateur__role=role)
    if action_type:
        actions = actions.filter(action__icontains=action_type)
    if module:
        actions = actions.filter(entite_concernee__icontains=module)
    if date_debut:
        actions = actions.filter(date_action__date__gte=date_debut)
    if date_fin:
        actions = actions.filter(date_action__date__lte=date_fin)
    return render(request, "audit/list.html", {"page_title": "Historique / Audit", "actions": actions[:200], "roles": Role.choices})
