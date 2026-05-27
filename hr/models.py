from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class StatutDemande(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente"
    EN_COURS = "EN_COURS", "En cours"
    VALIDEE = "VALIDEE", "Validee"
    REFUSEE = "REFUSEE", "Refusee"
    CLOTUREE = "CLOTUREE", "Cloturee"


class TypeConge(models.TextChoices):
    ANNUEL = "ANNUEL", "Annuel"
    MALADIE = "MALADIE", "Maladie"
    MATERNITE = "MATERNITE", "Maternite"
    SANS_SOLDE = "SANS_SOLDE", "Sans solde"


class Departement(models.Model):
    libelle = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["libelle"]

    def __str__(self):
        return self.libelle


class Service(models.Model):
    libelle = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    departement = models.ForeignKey(Departement, on_delete=models.SET_NULL, null=True, blank=True, related_name="services")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["libelle"]

    def __str__(self):
        return self.libelle


class Poste(models.Model):
    libelle = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    niveau = models.CharField(max_length=255, blank=True)
    rang_hierarchique = models.PositiveSmallIntegerField(default=50)
    est_direction = models.BooleanField(default=False)
    est_manager = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["libelle"]

    def __str__(self):
        return self.libelle


class Employe(models.Model):
    # ==================================================
    # TABLE : EMPLOYE
    # Gestion du profil RH, poste, departement et hierarchie
    # ==================================================
    matricule = models.CharField(max_length=100, unique=True)
    nom = models.CharField(max_length=255)
    prenom = models.CharField(max_length=255)
    email = models.EmailField()
    telephone = models.CharField(max_length=80, blank=True)
    date_naissance = models.DateField(null=True, blank=True)
    date_embauche = models.DateField()
    adresse = models.TextField(blank=True)
    photo = models.ImageField(upload_to="uploads/photos/", null=True, blank=True)
    departement = models.ForeignKey(Departement, on_delete=models.SET_NULL, null=True, blank=True, related_name="employes")
    service = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True, blank=True, related_name="employes")
    poste = models.ForeignKey(Poste, on_delete=models.SET_NULL, null=True, blank=True, related_name="employes")
    responsable = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="collaborateurs")
    localisation = models.CharField(max_length=255, blank=True, default="Casablanca")
    actif = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nom", "prenom"]

    def __str__(self):
        return self.nom_complet

    @property
    def nom_complet(self):
        return f"{self.prenom or ''} {self.nom or ''}".strip()

    @property
    def anciennete_annees(self):
        if not self.date_embauche:
            return 0
        return max(0, int((timezone.localdate() - self.date_embauche).days / 365))

    def clean(self):
        super().clean()
        # TRAITEMENT HIERARCHIE — empeche un employe d'etre son propre responsable ou de creer une boucle.
        if self.responsable_id and self.pk and self.responsable_id == self.pk:
            raise ValidationError({"responsable": "Un employe ne peut pas etre son propre responsable."})
        manager = self.responsable
        visited = set()
        while manager:
            if manager.pk == self.pk:
                raise ValidationError({"responsable": "Cette affectation cree une boucle hierarchique."})
            if manager.pk in visited:
                raise ValidationError({"responsable": "La chaine hierarchique contient deja une boucle."})
            visited.add(manager.pk)
            manager = manager.responsable


class DemandeConge(models.Model):
    # ==================================================
    # TABLE : DEMANDE_CONGE
    # Gestion des conges, dates, statuts et solde
    # ==================================================
    type = models.CharField(max_length=30, choices=TypeConge.choices)
    date_debut = models.DateField()
    date_fin = models.DateField()
    motif = models.TextField(blank=True)
    statut = models.CharField(max_length=30, choices=StatutDemande.choices, default=StatutDemande.EN_ATTENTE)
    employe = models.ForeignKey(Employe, on_delete=models.CASCADE, related_name="conges")
    traitee_par = models.ForeignKey(
        Employe,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conges_traites",
    )
    date_traitement = models.DateTimeField(null=True, blank=True)
    commentaire_reponse = models.TextField(blank=True)
    date_creation = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_creation"]

    def __str__(self):
        return f"{self.employe} - {self.type}"

    @property
    def duree_jours(self):
        if not self.date_debut or not self.date_fin:
            return 0
        return (self.date_fin - self.date_debut).days + 1

    def clean(self):
        super().clean()
        # TRAITEMENT DATE — bloque une demande en attente dans le passe et une date de fin avant le debut.
        today = timezone.localdate()
        if self.date_debut and self.date_debut < today and self.statut == StatutDemande.EN_ATTENTE:
            raise ValidationError({"date_debut": "La date de debut ne peut pas etre dans le passe."})
        if self.date_debut and self.date_fin and self.date_fin < self.date_debut:
            raise ValidationError({"date_fin": "La date de fin doit etre apres la date de debut."})


class DemandeAdministrative(models.Model):
    type_demande = models.CharField(max_length=255)
    description = models.TextField()
    statut = models.CharField(max_length=30, choices=StatutDemande.choices, default=StatutDemande.EN_ATTENTE)
    date_creation = models.DateTimeField(default=timezone.now)
    employe = models.ForeignKey(Employe, on_delete=models.CASCADE, related_name="demandes_administratives")
    traitee_par = models.ForeignKey(
        Employe,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="demandes_admin_traitees",
    )
    date_traitement = models.DateTimeField(null=True, blank=True)
    reponse = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_creation"]

    def __str__(self):
        return f"{self.type_demande} - {self.employe}"


class Document(models.Model):
    fichier = models.FileField(upload_to="uploads/documents/")
    nom_fichier = models.CharField(max_length=255)
    nom_original = models.CharField(max_length=255)
    categorie = models.CharField(max_length=255, blank=True, default="General")
    chemin_fichier = models.CharField(max_length=500, blank=True)
    date_ajout = models.DateTimeField(default=timezone.now)
    taille = models.PositiveBigIntegerField(default=0)
    employe = models.ForeignKey(Employe, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents")
    demande_admin = models.ForeignKey(
        DemandeAdministrative,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )
    uploade_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documents_uploades")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_ajout"]

    def __str__(self):
        return self.nom_original


class Notification(models.Model):
    message = models.TextField()
    date_envoi = models.DateTimeField(default=timezone.now)
    lue = models.BooleanField(default=False)
    destinataire = models.ForeignKey("accounts.UtilisateurProfile", on_delete=models.CASCADE, related_name="notifications")
    lien = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_envoi"]

    def __str__(self):
        return self.message[:80]


class HistoriqueAction(models.Model):
    action = models.CharField(max_length=255)
    details = models.TextField(blank=True)
    date_action = models.DateTimeField(default=timezone.now)
    utilisateur = models.ForeignKey(
        "accounts.UtilisateurProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="actions",
    )
    entite_concernee = models.CharField(max_length=255, blank=True)
    entite_id = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-date_action"]

    def __str__(self):
        return self.action


class SoldeConge(models.Model):
    # ==================================================
    # TABLE : SOLDE_CONGE
    # Solde disponible/utilise et protection contre les valeurs negatives
    # ==================================================
    employe = models.OneToOneField(Employe, on_delete=models.CASCADE, related_name="solde_conge")
    jours_disponibles = models.DecimalField(max_digits=6, decimal_places=2, default=22)
    jours_utilises = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        # TRAITEMENT SOLDE CONGE — le solde et les jours utilises ne peuvent pas etre negatifs.
        if self.jours_disponibles < 0 or self.jours_utilises < 0:
            raise ValidationError("Le solde de conges ne peut pas etre negatif.")


class MouvementSoldeConge(models.Model):
    solde = models.ForeignKey(SoldeConge, on_delete=models.CASCADE, related_name="mouvements")
    demande = models.ForeignKey(DemandeConge, on_delete=models.SET_NULL, null=True, blank=True, related_name="mouvements_solde")
    type_mouvement = models.CharField(max_length=40)
    jours = models.DecimalField(max_digits=6, decimal_places=2)
    solde_avant = models.DecimalField(max_digits=6, decimal_places=2)
    solde_apres = models.DecimalField(max_digits=6, decimal_places=2)
    description = models.TextField(blank=True)
    date_mouvement = models.DateTimeField(default=timezone.now)
    cree_par = models.ForeignKey("accounts.UtilisateurProfile", on_delete=models.SET_NULL, null=True, blank=True)


class ParametrePointage(models.Model):
    heure_debut_officielle = models.TimeField(default="09:00")
    heure_fin_officielle = models.TimeField(default="18:00")
    tolerance_retard_minutes = models.PositiveSmallIntegerField(default=10)
    heures_minimum_jour = models.DecimalField(max_digits=4, decimal_places=2, default=8)
    points_presence_normale = models.IntegerField(default=10)
    penalite_retard = models.IntegerField(default=5)
    penalite_sortie_anticipee = models.IntegerField(default=5)
    bonus_heures_supplementaires = models.IntegerField(default=3)
    actif = models.BooleanField(default=True)


class Pointage(models.Model):
    # ==================================================
    # TABLE : POINTAGE
    # Gestion entree/sortie, heures travaillees et points
    # ==================================================
    STATUTS = [
        ("present", "Present"),
        ("retard", "Retard"),
        ("sortie_anticipee", "Sortie anticipee"),
        ("incomplet", "Incomplet"),
        ("absent", "Absent"),
    ]
    employe = models.ForeignKey(Employe, on_delete=models.CASCADE, related_name="pointages")
    shift = models.ForeignKey("PlanningShift", on_delete=models.SET_NULL, null=True, blank=True, related_name="pointages")
    date = models.DateField(default=timezone.localdate)
    heure_entree = models.DateTimeField(null=True, blank=True)
    heure_sortie = models.DateTimeField(null=True, blank=True)
    total_heures = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    statut = models.CharField(max_length=40, choices=STATUTS, default="incomplet")
    points_calcules = models.IntegerField(default=0)
    commentaire = models.TextField(blank=True)

    class Meta:
        ordering = ["-date", "-heure_entree"]
        constraints = [models.UniqueConstraint(fields=["employe", "date"], name="unique_pointage_employe_date")]

    def clean(self):
        # TRAITEMENT POINTAGE — interdit une heure de sortie avant l'heure d'entree.
        if self.heure_entree and self.heure_sortie and self.heure_sortie < self.heure_entree:
            raise ValidationError("La sortie ne peut pas etre avant l'entree.")


class PlanningShift(models.Model):
    # ==================================================
    # TABLE : PLANNING_SHIFT
    # Planification des shifts, postes ouverts et conflits de disponibilite
    # ==================================================
    STATUTS = [
        ("brouillon", "Brouillon"),
        ("publie", "Publie"),
        ("ouvert", "Shift ouvert"),
        ("termine", "Termine"),
        ("annule", "Annule"),
    ]
    employe = models.ForeignKey(Employe, on_delete=models.SET_NULL, null=True, blank=True, related_name="shifts")
    departement = models.ForeignKey(Departement, on_delete=models.SET_NULL, null=True, blank=True, related_name="shifts")
    service = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True, blank=True, related_name="shifts")
    titre = models.CharField(max_length=160, default="Shift")
    lieu = models.CharField(max_length=255, blank=True, default="Casablanca")
    date_debut = models.DateTimeField()
    date_fin = models.DateTimeField()
    pause_minutes = models.PositiveSmallIntegerField(default=0)
    statut = models.CharField(max_length=30, choices=STATUTS, default="brouillon")
    notes = models.TextField(blank=True)
    cree_par = models.ForeignKey("accounts.UtilisateurProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="shifts_crees")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date_debut", "employe__nom"]

    def __str__(self):
        assigned_to = self.employe.nom_complet if self.employe else "Non assigne"
        return f"{self.titre} - {assigned_to}"

    @property
    def duree_heures(self):
        if not self.date_debut or not self.date_fin:
            return 0
        seconds = (self.date_fin - self.date_debut).total_seconds()
        return max(0, round((seconds / 3600) - (self.pause_minutes / 60), 2))

    def clean(self):
        super().clean()
        if self.date_debut and self.date_fin and self.date_fin <= self.date_debut:
            raise ValidationError({"date_fin": "La fin du shift doit etre apres le debut."})
        if self.statut == "publie" and not self.employe:
            self.statut = "ouvert"
        if self.employe and self.date_debut and self.date_fin and self.statut != "annule":
            overlaps = PlanningShift.objects.filter(
                employe=self.employe,
                date_debut__lt=self.date_fin,
                date_fin__gt=self.date_debut,
            ).exclude(statut="annule")
            if self.pk:
                overlaps = overlaps.exclude(pk=self.pk)
            if overlaps.exists():
                raise ValidationError("Ce shift chevauche deja un autre planning de cet employe.")
            leave_conflict = DemandeConge.objects.filter(
                employe=self.employe,
                statut=StatutDemande.VALIDEE,
                date_debut__lte=self.date_fin.date(),
                date_fin__gte=self.date_debut.date(),
            ).exists()
            if leave_conflict:
                raise ValidationError("Cet employe a deja un conge valide sur cette periode.")


class TacheEquipe(models.Model):
    # ==================================================
    # TABLE : TACHE_EQUIPE
    # Assignation de taches operationnelles aux equipes ou employes
    # ==================================================
    STATUTS = [("a_faire", "A faire"), ("en_cours", "En cours"), ("terminee", "Terminee"), ("annulee", "Annulee")]
    PRIORITES = [("basse", "Basse"), ("normale", "Normale"), ("haute", "Haute"), ("urgente", "Urgente")]
    titre = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    employe = models.ForeignKey(Employe, on_delete=models.SET_NULL, null=True, blank=True, related_name="taches")
    departement = models.ForeignKey(Departement, on_delete=models.SET_NULL, null=True, blank=True, related_name="taches")
    shift = models.ForeignKey(PlanningShift, on_delete=models.SET_NULL, null=True, blank=True, related_name="taches")
    priorite = models.CharField(max_length=20, choices=PRIORITES, default="normale")
    statut = models.CharField(max_length=30, choices=STATUTS, default="a_faire")
    date_limite = models.DateTimeField(null=True, blank=True)
    cree_par = models.ForeignKey("accounts.UtilisateurProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="taches_crees")
    terminee_par = models.ForeignKey("accounts.UtilisateurProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="taches_terminees")
    date_creation = models.DateTimeField(default=timezone.now)
    date_completion = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["statut", "date_limite", "-date_creation"]

    def __str__(self):
        return self.titre

    def clean(self):
        if not (self.titre or "").strip():
            raise ValidationError("Le titre de la tache est obligatoire.")
        if self.date_limite and self.date_limite < self.date_creation:
            raise ValidationError({"date_limite": "La date limite ne peut pas etre avant la creation."})


class ComptePoints(models.Model):
    # ==================================================
    # TABLE : COMPTE_POINTS
    # Solde de points actuel de l'employe
    # ==================================================
    employe = models.OneToOneField(Employe, on_delete=models.CASCADE, related_name="compte_points")
    solde_points = models.IntegerField(default=0)

    def clean(self):
        # TRAITEMENT POINTS — empeche un solde de points negatif.
        if self.solde_points < 0:
            raise ValidationError("Le solde de points ne peut pas etre negatif.")


class TransactionPoints(models.Model):
    # ==================================================
    # TABLE : TRANSACTION_POINTS
    # Historique des gains, deductions et corrections de points
    # ==================================================
    TYPES = [("gain", "Gain"), ("deduction", "Deduction"), ("achat", "Achat"), ("correction", "Correction"), ("remboursement", "Remboursement")]
    SOURCES = [("pointage", "Pointage"), ("boutique", "Boutique"), ("conge", "Conge"), ("formation", "Formation"), ("manuel", "Manuel"), ("reclamation", "Reclamation")]
    employe = models.ForeignKey(Employe, on_delete=models.CASCADE, related_name="transactions_points")
    type_transaction = models.CharField(max_length=30, choices=TYPES)
    source = models.CharField(max_length=30, choices=SOURCES)
    points = models.IntegerField()
    solde_avant = models.IntegerField()
    solde_apres = models.IntegerField()
    description = models.TextField()
    date_transaction = models.DateTimeField(default=timezone.now)
    cree_par = models.ForeignKey("accounts.UtilisateurProfile", on_delete=models.SET_NULL, null=True, blank=True)
    objet_lie = models.CharField(max_length=120, blank=True)


class AjustementPointsManuel(models.Model):
    TYPES = [("ajout", "Ajout"), ("retrait", "Retrait"), ("correction", "Correction"), ("remboursement", "Remboursement")]
    employe = models.ForeignKey(Employe, on_delete=models.CASCADE, related_name="ajustements_points")
    type_adjustement = models.CharField(max_length=30, choices=TYPES)
    nombre_points = models.PositiveIntegerField()
    motif_obligatoire = models.TextField()
    reclamation_liee = models.ForeignKey("ReclamationRH", on_delete=models.SET_NULL, null=True, blank=True)
    cree_par = models.ForeignKey("accounts.UtilisateurProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="ajustements_crees")
    date_creation = models.DateTimeField(default=timezone.now)

    def clean(self):
        if self.nombre_points <= 0:
            raise ValidationError("Le nombre de points doit etre superieur a 0.")
        if not (self.motif_obligatoire or "").strip():
            raise ValidationError("Le motif est obligatoire.")


class Formation(models.Model):
    titre = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    categorie = models.CharField(max_length=120, blank=True)
    duree_estimee_heures = models.PositiveSmallIntegerField(default=1)
    points_recompense = models.PositiveIntegerField(default=0)
    date_creation = models.DateTimeField(default=timezone.now)
    actif = models.BooleanField(default=True)

    def __str__(self):
        return self.titre


class AffectationFormation(models.Model):
    # ==================================================
    # TABLE : AFFECTATION_FORMATION
    # Suivi des formations assignees et attribution unique des points
    # ==================================================
    STATUTS = [("assignee", "Assignee"), ("en_cours", "En cours"), ("terminee", "Terminee"), ("en_retard", "En retard"), ("annulee", "Annulee")]
    formation = models.ForeignKey(Formation, on_delete=models.CASCADE, related_name="affectations")
    employe = models.ForeignKey(Employe, on_delete=models.CASCADE, related_name="formations_assignees")
    assigne_par = models.ForeignKey("accounts.UtilisateurProfile", on_delete=models.SET_NULL, null=True, blank=True)
    date_affectation = models.DateField(default=timezone.localdate)
    date_limite = models.DateField(null=True, blank=True)
    statut = models.CharField(max_length=30, choices=STATUTS, default="assignee")
    date_completion = models.DateField(null=True, blank=True)
    points_attribues = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["formation", "employe"], condition=models.Q(statut__in=["assignee", "en_cours"]), name="unique_formation_active_employe")]

    def clean(self):
        # TRAITEMENT DATE FORMATION — la limite et la completion ne peuvent pas preceder l'affectation.
        if self.date_limite and self.date_limite < self.date_affectation:
            raise ValidationError({"date_limite": "La date limite ne peut pas etre avant l'affectation."})
        if self.date_completion and self.date_completion < self.date_affectation:
            raise ValidationError({"date_completion": "La completion ne peut pas etre avant l'affectation."})


class ConversationRH(models.Model):
    STATUTS = [("ouverte", "Ouverte"), ("en_attente", "En attente"), ("cloturee", "Cloturee")]
    sujet = models.CharField(max_length=255)
    employe = models.ForeignKey(Employe, on_delete=models.CASCADE, related_name="conversations_rh")
    responsable_rh = models.ForeignKey("accounts.UtilisateurProfile", on_delete=models.SET_NULL, null=True, blank=True)
    statut = models.CharField(max_length=30, choices=STATUTS, default="ouverte")
    date_creation = models.DateTimeField(default=timezone.now)
    date_derniere_reponse = models.DateTimeField(default=timezone.now)


class MessageRH(models.Model):
    conversation = models.ForeignKey(ConversationRH, on_delete=models.CASCADE, related_name="messages")
    expediteur = models.ForeignKey("accounts.UtilisateurProfile", on_delete=models.CASCADE, related_name="messages_envoyes")
    destinataire = models.ForeignKey("accounts.UtilisateurProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages_recus")
    contenu = models.TextField()
    date_envoi = models.DateTimeField(default=timezone.now)
    lu = models.BooleanField(default=False)

    def clean(self):
        # TRAITEMENT MESSAGE RH — refuse l'envoi d'un message vide.
        if not (self.contenu or "").strip():
            raise ValidationError("Le message ne peut pas etre vide.")


class Actualite(models.Model):
    AUDIENCES = [("tous", "Tous"), ("departement", "Departement"), ("role", "Role")]
    STATUTS = [("brouillon", "Brouillon"), ("publiee", "Publiee"), ("archivee", "Archivee")]
    titre = models.CharField(max_length=255)
    contenu = models.TextField()
    auteur = models.ForeignKey("accounts.UtilisateurProfile", on_delete=models.SET_NULL, null=True, blank=True)
    audience = models.CharField(max_length=30, choices=AUDIENCES, default="tous")
    departement = models.ForeignKey(Departement, on_delete=models.SET_NULL, null=True, blank=True)
    role_cible = models.CharField(max_length=40, blank=True)
    statut = models.CharField(max_length=30, choices=STATUTS, default="brouillon")
    date_publication = models.DateTimeField(null=True, blank=True)
    date_evenement = models.DateField(null=True, blank=True)
    image = models.ImageField(upload_to="uploads/actualites/", null=True, blank=True)

    def clean(self):
        if not (self.titre or "").strip() or not (self.contenu or "").strip():
            raise ValidationError("Le titre et le contenu sont obligatoires.")
        if self.date_publication and self.date_evenement and self.date_evenement < self.date_publication.date():
            raise ValidationError({"date_evenement": "La date d'evenement ne peut pas etre avant la publication."})


class CategorieProduit(models.Model):
    nom = models.CharField(max_length=120, unique=True)

    def __str__(self):
        return self.nom


class Produit(models.Model):
    nom = models.CharField(max_length=255)
    categorie = models.ForeignKey(CategorieProduit, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="uploads/produits/", null=True, blank=True)
    cout_points = models.PositiveIntegerField(default=0)
    stock_disponible = models.PositiveIntegerField(default=0)
    actif = models.BooleanField(default=True)

    def __str__(self):
        return self.nom


class AffectationMateriel(models.Model):
    STATUTS = [("attribue", "Attribue"), ("livre", "Livre"), ("retourne", "Retourne"), ("perdu", "Perdu"), ("remplace", "Remplace")]
    employe = models.ForeignKey(Employe, on_delete=models.CASCADE, related_name="materiels")
    produit = models.ForeignKey(Produit, on_delete=models.CASCADE)
    quantite = models.PositiveIntegerField(default=1)
    attribue_par = models.ForeignKey("accounts.UtilisateurProfile", on_delete=models.SET_NULL, null=True, blank=True)
    date_attribution = models.DateTimeField(default=timezone.now)
    statut = models.CharField(max_length=30, choices=STATUTS, default="attribue")
    commentaire = models.TextField(blank=True)


class CommandeProduit(models.Model):
    # ==================================================
    # TABLE : COMMANDE_PRODUIT
    # Commandes boutique, cout en points, stock et validation
    # ==================================================
    STATUTS = [("en_attente", "En attente"), ("approuvee", "Approuvee"), ("refusee", "Refusee"), ("livree", "Livree"), ("annulee", "Annulee")]
    employe = models.ForeignKey(Employe, on_delete=models.CASCADE, related_name="commandes_produits")
    produit = models.ForeignKey(Produit, on_delete=models.CASCADE)
    quantite = models.PositiveIntegerField(default=1)
    cout_total_points = models.PositiveIntegerField(default=0)
    statut = models.CharField(max_length=30, choices=STATUTS, default="en_attente")
    date_commande = models.DateTimeField(default=timezone.now)
    date_validation = models.DateTimeField(null=True, blank=True)
    valide_par = models.ForeignKey("accounts.UtilisateurProfile", on_delete=models.SET_NULL, null=True, blank=True)
    motif_refus = models.TextField(blank=True)
    points_deduits = models.BooleanField(default=False)

    def clean(self):
        # TRAITEMENT STOCK/DATE — quantite positive, produit actif, validation apres commande.
        if self.quantite <= 0:
            raise ValidationError({"quantite": "La quantite doit etre superieure a 0."})
        if not self.produit.actif:
            raise ValidationError("Ce produit n'est pas actif.")
        if self.date_validation and self.date_validation < self.date_commande:
            raise ValidationError("La date de livraison/validation ne peut pas etre avant la commande.")


class Remuneration(models.Model):
    employe = models.ForeignKey(Employe, on_delete=models.CASCADE, related_name="remunerations")
    salaire_base = models.DecimalField(max_digits=12, decimal_places=2)
    prime = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    devise = models.CharField(max_length=8, default="MAD")
    date_effet = models.DateField(default=timezone.localdate)
    actif = models.BooleanField(default=True)
    cree_par = models.ForeignKey("accounts.UtilisateurProfile", on_delete=models.SET_NULL, null=True, blank=True)


class ReclamationRH(models.Model):
    # ==================================================
    # TABLE : RECLAMATION_RH
    # Reclamations employes, reponse RH et compensation en points
    # ==================================================
    TYPES = [("points", "Points"), ("pointage", "Pointage"), ("conge", "Conge"), ("materiel", "Materiel"), ("salaire", "Salaire"), ("document", "Document"), ("autre", "Autre")]
    STATUTS = [("ouverte", "Ouverte"), ("en_cours", "En cours"), ("acceptee", "Acceptee"), ("refusee", "Refusee"), ("cloturee", "Cloturee")]
    employe = models.ForeignKey(Employe, on_delete=models.CASCADE, related_name="reclamations")
    sujet = models.CharField(max_length=255)
    description = models.TextField()
    type_reclamation = models.CharField(max_length=30, choices=TYPES)
    statut = models.CharField(max_length=30, choices=STATUTS, default="ouverte")
    date_creation = models.DateTimeField(default=timezone.now)
    date_traitement = models.DateTimeField(null=True, blank=True)
    traite_par = models.ForeignKey("accounts.UtilisateurProfile", on_delete=models.SET_NULL, null=True, blank=True)
    reponse_rh = models.TextField(blank=True)
    points_accordes = models.PositiveIntegerField(default=0)
    action_points_appliquee = models.BooleanField(default=False)

    def clean(self):
        # TRAITEMENT RECLAMATION — sujet et description obligatoires.
        if not (self.sujet or "").strip() or not (self.description or "").strip():
            raise ValidationError("Le sujet et la description sont obligatoires.")
