from datetime import date, time, timedelta
import random

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Role, UtilisateurProfile
from hr.models import (
    Actualite,
    AffectationFormation,
    CategorieProduit,
    CommandeProduit,
    ComptePoints,
    ConversationRH,
    DemandeAdministrative,
    DemandeConge,
    Departement,
    Employe,
    Formation,
    HistoriqueAction,
    MessageRH,
    ParametrePointage,
    Pointage,
    Poste,
    Produit,
    Remuneration,
    Service,
    SoldeConge,
    StatutDemande,
    TypeConge,
)
from hr.services import appliquer_transaction_points


class Command(BaseCommand):
    help = "Cree des donnees demo RH fictives pour Maroc Telecom Demo."

    def add_arguments(self, parser):
        parser.add_argument("--reset-demo", action="store_true", help="Supprime les donnees demo avant recreation.")

    def handle(self, *args, **options):
        if options["reset_demo"]:
            for model in [HistoriqueAction, MessageRH, ConversationRH, CommandeProduit, Produit, CategorieProduit, AffectationFormation, Formation, Remuneration, Pointage, DemandeConge, DemandeAdministrative, ComptePoints, SoldeConge, UtilisateurProfile, Employe, Service, Poste, Departement]:
                model.objects.all().delete()
            User.objects.filter(username__in=["admin", "rh", "manager", "employe"]).delete()

        random.seed(19)
        departments = [
            "Direction Generale", "Ressources Humaines", "Technologie / IT", "Reseau & Infrastructure",
            "Cybersecurite", "Produit", "Marketing", "Ventes", "Finance", "Comptabilite",
            "Juridique", "Support Client", "Operations", "Achats / Procurement",
            "Formation & Developpement", "Administration",
        ]
        dep_objs = {name: Departement.objects.get_or_create(libelle=name, defaults={"description": f"Departement {name} - Maroc Telecom Demo"})[0] for name in departments}
        for dep in dep_objs.values():
            Service.objects.get_or_create(libelle=f"Service {dep.libelle}", departement=dep)

        role_specs = [
            ("Directeur General / CEO", "Executive", 1, True, True, 95000),
            ("Directeur des Operations / COO", "Executive", 2, True, True, 78000),
            ("Directeur Financier / CFO", "Executive", 2, True, True, 76000),
            ("Directeur Technique / CTO", "Executive", 2, True, True, 80000),
            ("Directeur RH / CHRO", "Executive", 2, True, True, 70000),
            ("Directeur Marketing / CMO", "Executive", 2, True, True, 68000),
            ("Directeur Commercial / CRO", "Executive", 2, True, True, 72000),
            ("Directeur Produit / CPO", "Executive", 2, True, True, 70000),
            ("Directeur Juridique", "Direction", 3, True, True, 65000),
            ("Directeur de departement", "Direction", 8, True, True, 52000),
            ("Responsable service", "Manager", 18, False, True, 34000),
            ("Manager", "Manager", 35, False, True, 28000),
            ("Chef d'equipe", "Lead", 45, False, True, 22000),
            ("Senior", "Senior", 60, False, False, 17000),
            ("Confirme", "Confirme", 70, False, False, 12500),
            ("Junior", "Junior", 85, False, False, 8500),
            ("Stagiaire", "Stagiaire", 95, False, False, 3500),
        ]
        postes = {name: Poste.objects.update_or_create(libelle=name, defaults={"niveau": niveau, "rang_hierarchique": rang, "est_direction": direction, "est_manager": manager})[0] for name, niveau, rang, direction, manager, _ in role_specs}

        prenoms = ["Yasmine", "Mehdi", "Sara", "Amine", "Nadia", "Karim", "Leila", "Omar", "Imane", "Hicham", "Salma", "Rachid", "Meryem", "Anas", "Kenza", "Youssef", "Fatima", "Nabil", "Sofia", "Adil"]
        noms = ["El Amrani", "Benjelloun", "Bennani", "Alaoui", "Tazi", "Fassi", "Berrada", "Lahlou", "Cherkaoui", "Mansouri", "Zerhouni", "Naciri", "Lamrani", "Sefrioui", "Raji", "Idrissi", "Sbai", "Guessous", "Mernissi", "Bennis"]
        employees = []
        ceo = self.employee("MTD-0001", "Alaoui", "Samir", dep_objs["Direction Generale"], postes["Directeur General / CEO"], None, 1)
        employees.append(ceo)
        executives = []
        for i, title in enumerate(list(postes.keys())[1:9], start=2):
            dep = dep_objs[departments[i - 1]]
            executives.append(self.employee(f"MTD-{i:04d}", random.choice(noms), random.choice(prenoms), dep, postes[title], ceo, i))
        employees += executives
        managers = executives[:]
        for i in range(10, 101):
            dep = dep_objs[departments[i % len(departments)]]
            if i < 26:
                poste = postes["Directeur de departement"]
                manager = random.choice(executives)
            elif i < 50:
                poste = random.choice([postes["Responsable service"], postes["Manager"], postes["Chef d'equipe"]])
                manager = random.choice(managers)
            else:
                poste = random.choice([postes["Senior"], postes["Confirme"], postes["Junior"], postes["Stagiaire"]])
                manager = random.choice(managers[-35:])
            emp = self.employee(f"MTD-{i:04d}", random.choice(noms), random.choice(prenoms), dep, poste, manager, i)
            employees.append(emp)
            if poste.est_manager:
                managers.append(emp)

        for username, password, role, emp in [("admin", "admin123", Role.ADMIN, employees[0]), ("rh", "rh123", Role.RESPONSABLE_RH, executives[3]), ("manager", "manager123", Role.RESPONSABLE_HIERARCHIQUE, managers[-1]), ("employe", "employe123", Role.EMPLOYE, employees[-1])]:
            user, _ = User.objects.get_or_create(username=username, defaults={"is_staff": role == Role.ADMIN, "is_superuser": role == Role.ADMIN})
            user.set_password(password)
            user.save()
            UtilisateurProfile.objects.update_or_create(user=user, defaults={"role": role, "employe": emp, "actif": True})
        admin_profile = UtilisateurProfile.objects.get(user__username="admin")

        ParametrePointage.objects.get_or_create(actif=True, defaults={"heure_debut_officielle": time(9, 0), "heure_fin_officielle": time(18, 0)})
        salary_map = {name: base for name, _, _, _, _, base in role_specs}
        for emp in employees:
            base = salary_map.get(emp.poste.libelle, 10000)
            Remuneration.objects.update_or_create(employe=emp, actif=True, defaults={"salaire_base": base + random.randint(-2500, 4500), "prime": random.randint(0, 8000), "devise": "MAD", "cree_par": admin_profile})
            SoldeConge.objects.update_or_create(employe=emp, defaults={"jours_disponibles": random.randint(8, 28), "jours_utilises": random.randint(0, 12)})
            ComptePoints.objects.update_or_create(employe=emp, defaults={"solde_points": random.randint(80, 650)})
            if random.random() < .45:
                entree = timezone.make_aware(timezone.datetime.combine(timezone.localdate(), time(9, random.choice([0, 5, 12, 25]))))
                sortie = entree + timedelta(hours=random.choice([7, 8, 9]))
                Pointage.objects.update_or_create(employe=emp, date=timezone.localdate(), defaults={"heure_entree": entree, "heure_sortie": sortie, "total_heures": round((sortie - entree).total_seconds() / 3600, 2), "statut": "retard" if entree.time() > time(9, 10) else "present", "points_calcules": 5 if entree.time() > time(9, 10) else 10})

        for i, emp in enumerate(employees[:24]):
            DemandeConge.objects.get_or_create(employe=emp, date_debut=timezone.localdate() + timedelta(days=10 + i), defaults={"type": TypeConge.ANNUEL, "date_fin": timezone.localdate() + timedelta(days=11 + i), "statut": random.choice([StatutDemande.EN_ATTENTE, StatutDemande.VALIDEE, StatutDemande.REFUSEE])})
            DemandeAdministrative.objects.get_or_create(employe=emp, type_demande=f"Attestation {i}", defaults={"description": "Demande administrative demo pour validation RH.", "statut": random.choice([StatutDemande.EN_ATTENTE, StatutDemande.VALIDEE])})

        categories = {n: CategorieProduit.objects.get_or_create(nom=n)[0] for n in ["Ordinateurs", "Ecrans", "Accessoires", "Audio", "Telephones"]}
        for name, cat, cost, stock in [("MacBook Air M3", "Ordinateurs", 420, 8), ("Lenovo ThinkPad", "Ordinateurs", 360, 12), ("Dell Latitude", "Ordinateurs", 320, 10), ("Ecran Dell 24 pouces", "Ecrans", 140, 24), ("Clavier USB-C", "Accessoires", 60, 30), ("Souris sans fil", "Accessoires", 45, 40), ("Casque Logitech", "Audio", 80, 25), ("Telephone professionnel", "Telephones", 220, 12)]:
            Produit.objects.update_or_create(nom=name, defaults={"categorie": categories[cat], "description": f"Materiel demo {name}", "cout_points": cost, "stock_disponible": stock, "actif": True})
        products = list(Produit.objects.all())
        for emp in employees[20:38]:
            CommandeProduit.objects.get_or_create(employe=emp, produit=random.choice(products), defaults={"quantite": 1, "cout_total_points": 0, "statut": random.choice(["en_attente", "approuvee", "livree"])})

        formations = [Formation.objects.get_or_create(titre=t, defaults={"categorie": "RH", "description": f"Formation demo {t}", "duree_estimee_heures": random.randint(2, 12)})[0] for t in ["Securite des donnees", "Leadership manager", "Onboarding corporate", "Service client avance"]]
        for emp in employees[15:55]:
            AffectationFormation.objects.get_or_create(employe=emp, formation=random.choice(formations), defaults={"assigne_par": admin_profile, "date_limite": timezone.localdate() + timedelta(days=random.randint(15, 60)), "statut": random.choice(["assignee", "en_cours", "terminee"])})
        for i in range(5):
            Actualite.objects.get_or_create(titre=f"Newsletter Maroc Telecom Demo {i+1}", defaults={"contenu": "Actualite interne fictive pour la demonstration RH.", "auteur": admin_profile, "statut": "publiee", "date_publication": timezone.now() - timedelta(days=i)})
        for emp in employees[5:15]:
            conv, _ = ConversationRH.objects.get_or_create(employe=emp, sujet="Question RH demo")
            MessageRH.objects.get_or_create(conversation=conv, expediteur=admin_profile, contenu="Bonjour, votre demande est en cours de traitement.")
        HistoriqueAction.objects.get_or_create(action="SEED_DEMO_RH", details="Donnees demo Maroc Telecom Demo creees.", utilisateur=admin_profile)
        self.stdout.write(self.style.SUCCESS(f"Donnees demo creees: {len(employees)} employes fictifs pour Maroc Telecom Demo."))

    def employee(self, matricule, nom, prenom, dep, poste, manager, index):
        return Employe.objects.update_or_create(
            matricule=matricule,
            defaults={
                "nom": nom,
                "prenom": prenom,
                "email": f"{prenom.lower()}.{nom.lower().replace(' ', '')}.{index}@maroctelecom-demo.local",
                "telephone": f"+212 6{index:08d}"[:13],
                "date_naissance": date(1980 + (index % 20), (index % 12) + 1, (index % 27) + 1),
                "date_embauche": timezone.localdate() - timedelta(days=120 + index * 17),
                "departement": dep,
                "service": dep.services.first(),
                "poste": poste,
                "responsable": manager,
                "localisation": random.choice(["Casablanca", "Rabat", "Marrakech", "Tanger", "Fes"]),
                "actif": True,
            },
        )[0]
