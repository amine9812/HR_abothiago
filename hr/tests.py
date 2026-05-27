from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, UtilisateurProfile
from hr.forms import AffectationFormationForm, CommandeProduitForm, DemandeAdministrativeForm, DemandeCongeForm, EmployeForm
from hr.models import (
    AffectationFormation,
    CategorieProduit,
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
    Pointage,
    Poste,
    Produit,
    ReclamationRH,
    Remuneration,
    SoldeConge,
    StatutDemande,
    TransactionPoints,
    TypeConge,
)
from hr.services import appliquer_transaction_points, approuver_commande, deduire_solde_conge


class HrSmokeTests(TestCase):
    def setUp(self):
        departement = Departement.objects.create(libelle="IT")
        poste = Poste.objects.create(libelle="Dev")
        self.employe = Employe.objects.create(
            matricule="EMP-T",
            nom="Test",
            prenom="User",
            email="user@test.local",
            date_embauche=timezone.localdate() - timedelta(days=30),
            departement=departement,
            poste=poste,
        )
        user = User.objects.create_user(username="admin", password="admin123")
        UtilisateurProfile.objects.create(user=user, role=Role.ADMIN, employe=self.employe)

    def test_login_page_loads(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)

    def test_dashboard_requires_login_then_loads(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.client.login(username="admin", password="admin123")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_employee_list_loads_for_admin(self):
        self.client.login(username="admin", password="admin123")
        response = self.client.get(reverse("employes_list"))
        self.assertEqual(response.status_code, 200)

    def test_employee_sidebar_parent_stays_open_on_hierarchy(self):
        self.client.login(username="admin", password="admin123")
        response = self.client.get(reverse("hierarchy_tree"))
        self.assertContains(response, 'id="menuEmployes"')
        self.assertContains(response, 'sidebar-submenu show')
        self.assertContains(response, 'sidebar-subitem active')
        self.assertContains(response, 'bi bi-diagram-3')

    def test_department_sidebar_active_child_uses_query_tab(self):
        self.client.login(username="admin", password="admin123")
        response = self.client.get(reverse("departements_list"), {"tab": "services"})
        self.assertContains(response, 'id="menuDepartements"')
        self.assertContains(response, 'sidebar-submenu show')
        self.assertContains(response, 'sidebar-subitem active')
        self.assertContains(response, "Services")


class FormValidationTests(TestCase):
    def setUp(self):
        self.employee = Employe.objects.create(
            matricule="EMP-001",
            nom="Valid",
            prenom="User",
            email="valid@example.com",
            telephone="+212 600000000",
            date_embauche=timezone.localdate() - timedelta(days=60),
        )

    def test_employee_form_rejects_invalid_name_future_dates_and_duplicate_email(self):
        form = EmployeForm(
            data={
                "matricule": "EMP-002",
                "nom": "User123",
                "prenom": "A",
                "email": "VALID@EXAMPLE.COM",
                "telephone": "abc123",
                "date_naissance": timezone.localdate() + timedelta(days=1),
                "date_embauche": timezone.localdate() + timedelta(days=1),
                "adresse": "  ",
                "actif": "on",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("nom", form.errors)
        self.assertIn("prenom", form.errors)
        self.assertIn("email", form.errors)
        self.assertIn("telephone", form.errors)
        self.assertIn("date_naissance", form.errors)
        self.assertIn("date_embauche", form.errors)

    def test_leave_form_rejects_past_reverse_and_overlapping_dates(self):
        today = timezone.localdate()
        reverse_form = DemandeCongeForm(
            data={"type": TypeConge.ANNUEL, "date_debut": today + timedelta(days=3), "date_fin": today + timedelta(days=1), "motif": ""}
        )
        self.assertFalse(reverse_form.is_valid())
        self.assertIn("date_fin", reverse_form.errors)

        past_form = DemandeCongeForm(
            data={"type": TypeConge.ANNUEL, "date_debut": today - timedelta(days=1), "date_fin": today, "motif": ""}
        )
        self.assertFalse(past_form.is_valid())
        self.assertIn("date_debut", past_form.errors)

        DemandeConge.objects.create(
            type=TypeConge.ANNUEL,
            date_debut=today + timedelta(days=5),
            date_fin=today + timedelta(days=7),
            employe=self.employee,
        )
        overlap_form = DemandeCongeForm(
            employee=self.employee,
            data={"type": TypeConge.MALADIE, "date_debut": today + timedelta(days=6), "date_fin": today + timedelta(days=8), "motif": ""}
        )
        self.assertFalse(overlap_form.is_valid())
        self.assertIn("__all__", overlap_form.errors)

    def test_admin_request_requires_meaningful_text(self):
        form = DemandeAdministrativeForm(data={"type_demande": "A", "description": "short"})

        self.assertFalse(form.is_valid())
        self.assertIn("type_demande", form.errors)
        self.assertIn("description", form.errors)


class WorkflowSecurityTests(TestCase):
    def setUp(self):
        self.department = Departement.objects.create(libelle="Operations")
        self.manager_employee = Employe.objects.create(
            matricule="MGR-001",
            nom="Manager",
            prenom="Main",
            email="manager@example.com",
            date_embauche=timezone.localdate() - timedelta(days=100),
            departement=self.department,
        )
        self.employee = Employe.objects.create(
            matricule="EMP-002",
            nom="Employee",
            prenom="Direct",
            email="employee@example.com",
            date_embauche=timezone.localdate() - timedelta(days=90),
            departement=self.department,
            responsable=self.manager_employee,
        )
        self.other_employee = Employe.objects.create(
            matricule="EMP-003",
            nom="Other",
            prenom="Hidden",
            email="other@example.com",
            date_embauche=timezone.localdate() - timedelta(days=80),
            departement=self.department,
        )
        self.rh_employee = Employe.objects.create(
            matricule="RH-001",
            nom="Human",
            prenom="Resources",
            email="rh.employee@example.com",
            date_embauche=timezone.localdate() - timedelta(days=120),
            departement=self.department,
        )
        self.manager_user = User.objects.create_user(username="manager", password="manager123")
        self.employee_user = User.objects.create_user(username="employee", password="employee123")
        self.rh_user = User.objects.create_user(username="rh", password="rh123")
        UtilisateurProfile.objects.create(user=self.manager_user, role=Role.RESPONSABLE_HIERARCHIQUE, employe=self.manager_employee)
        UtilisateurProfile.objects.create(user=self.employee_user, role=Role.EMPLOYE, employe=self.employee)
        UtilisateurProfile.objects.create(user=self.rh_user, role=Role.RESPONSABLE_RH, employe=self.rh_employee)

    def test_manager_cannot_view_unrelated_employee_by_direct_url(self):
        self.client.login(username="manager", password="manager123")

        response = self.client.get(reverse("employe_detail", args=[self.other_employee.pk]))

        self.assertEqual(response.status_code, 404)

    def test_state_changing_leave_action_rejects_get_and_cannot_process_twice(self):
        demande = DemandeConge.objects.create(
            type=TypeConge.ANNUEL,
            date_debut=timezone.localdate() + timedelta(days=2),
            date_fin=timezone.localdate() + timedelta(days=3),
            employe=self.employee,
        )
        self.client.login(username="manager", password="manager123")

        get_response = self.client.get(reverse("conge_validate", args=[demande.pk]))
        self.assertEqual(get_response.status_code, 405)

        post_response = self.client.post(reverse("conge_validate", args=[demande.pk]))
        self.assertEqual(post_response.status_code, 302)
        demande.refresh_from_db()
        self.assertEqual(demande.statut, StatutDemande.VALIDEE)


class NewHrFeatureAbuseTests(TestCase):
    def setUp(self):
        self.dep = Departement.objects.create(libelle="RH")
        self.poste = Poste.objects.create(libelle="Manager", rang_hierarchique=30, est_manager=True)
        self.rh_emp = Employe.objects.create(matricule="RH-X", nom="Rh", prenom="Admin", email="rhx@example.com", date_embauche=timezone.localdate() - timedelta(days=300), departement=self.dep, poste=self.poste)
        self.emp = Employe.objects.create(matricule="EMP-X", nom="Test", prenom="Employe", email="empx@example.com", date_embauche=timezone.localdate() - timedelta(days=100), departement=self.dep, responsable=self.rh_emp)
        self.other = Employe.objects.create(matricule="EMP-Y", nom="Autre", prenom="Employe", email="empy@example.com", date_embauche=timezone.localdate() - timedelta(days=100), departement=self.dep)
        self.rh_user = User.objects.create_user(username="rh2", password="rh123")
        self.emp_user = User.objects.create_user(username="emp2", password="emp123")
        UtilisateurProfile.objects.create(user=self.rh_user, role=Role.RESPONSABLE_RH, employe=self.rh_emp)
        UtilisateurProfile.objects.create(user=self.emp_user, role=Role.EMPLOYE, employe=self.emp)
        ComptePoints.objects.create(employe=self.emp, solde_points=100)
        SoldeConge.objects.create(employe=self.emp, jours_disponibles=3, jours_utilises=0)

    def test_points_balance_never_negative(self):
        with self.assertRaises(Exception):
            appliquer_transaction_points(self.emp, "achat", 999, "boutique", "Achat impossible")
        self.emp.compte_points.refresh_from_db()
        self.assertEqual(self.emp.compte_points.solde_points, 100)

    def test_employee_cannot_access_manual_point_adjustment(self):
        self.client.login(username="emp2", password="emp123")
        response = self.client.get(reverse("manual_points"))
        self.assertEqual(response.status_code, 302)

    def test_hr_can_add_points_with_reason(self):
        self.client.login(username="rh2", password="rh123")
        response = self.client.post(reverse("manual_points"), {"employe": self.emp.id, "type_adjustement": "ajout", "nombre_points": 25, "motif_obligatoire": "Correction pointage validee"})
        self.assertEqual(response.status_code, 302)
        self.emp.compte_points.refresh_from_db()
        self.assertEqual(self.emp.compte_points.solde_points, 125)

    def test_salary_and_position_permissions_protected(self):
        Remuneration.objects.create(employe=self.emp, salaire_base=10000)
        self.client.login(username="emp2", password="emp123")
        self.assertEqual(self.client.get(reverse("payroll_analytics")).status_code, 302)
        self.assertEqual(self.client.get(reverse("position_management")).status_code, 302)

    def test_hierarchy_cycle_prevented(self):
        self.rh_emp.responsable = self.emp
        with self.assertRaises(Exception):
            self.rh_emp.full_clean()

    def test_hierarchy_page_uses_real_data_and_hides_salary(self):
        Remuneration.objects.create(employe=self.emp, salaire_base=123456, prime=789)
        self.client.login(username="emp2", password="emp123")
        response = self.client.get(reverse("hierarchy_tree"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.rh_emp.nom_complet)
        self.assertContains(response, self.emp.nom_complet)
        self.assertContains(response, "org-card")
        self.assertNotContains(response, "123456")
        self.assertNotContains(response, "789")

    def test_unauthenticated_user_cannot_view_hierarchy(self):
        response = self.client.get(reverse("hierarchy_tree"))
        self.assertEqual(response.status_code, 302)

    def test_manager_change_updates_hierarchy_output(self):
        self.client.login(username="emp2", password="emp123")
        first_response = self.client.get(reverse("hierarchy_tree"))
        self.assertContains(first_response, self.rh_emp.nom_complet)
        self.emp.responsable = self.other
        self.emp.save(update_fields=["responsable"])
        second_response = self.client.get(reverse("hierarchy_tree"))
        content = second_response.content.decode()
        self.assertIn(self.other.nom_complet, content)
        self.assertIn(self.emp.nom_complet, content)

    def test_ceo_position_change_updates_top_hierarchy_data(self):
        direction = Poste.objects.create(libelle="Directeur General Test", niveau="Direction generale", rang_hierarchique=1, est_direction=True, est_manager=True)
        self.other.poste = direction
        self.other.responsable = None
        self.other.save(update_fields=["poste", "responsable"])
        self.client.login(username="emp2", password="emp123")
        response = self.client.get(reverse("hierarchy_tree"))
        content = response.content.decode()
        self.assertIn("Directeur General Test", content)
        self.assertIn(self.other.nom_complet, content)

    def test_leave_balance_blocks_excess_and_deducts_when_validated(self):
        demande = DemandeConge.objects.create(type=TypeConge.ANNUEL, date_debut=timezone.localdate() + timedelta(days=5), date_fin=timezone.localdate() + timedelta(days=9), employe=self.emp)
        with self.assertRaises(Exception):
            deduire_solde_conge(demande)
        demande.date_fin = timezone.localdate() + timedelta(days=6)
        demande.save()
        deduire_solde_conge(demande)
        self.emp.solde_conge.refresh_from_db()
        self.assertEqual(float(self.emp.solde_conge.jours_disponibles), 1.0)

    def test_unpaid_leave_bypasses_balance_on_request_and_validation(self):
        start = timezone.localdate() + timedelta(days=5)
        end = start + timedelta(days=9)
        annual_form = DemandeCongeForm(employee=self.emp, data={"type": TypeConge.ANNUEL, "date_debut": start, "date_fin": end, "motif": ""})
        unpaid_form = DemandeCongeForm(employee=self.emp, data={"type": TypeConge.SANS_SOLDE, "date_debut": start, "date_fin": end, "motif": ""})

        self.assertFalse(annual_form.is_valid())
        self.assertTrue(unpaid_form.is_valid())

        demande = DemandeConge.objects.create(type=TypeConge.SANS_SOLDE, date_debut=start, date_fin=end, employe=self.emp)
        self.client.login(username="rh2", password="rh123")
        response = self.client.post(reverse("conge_validate", args=[demande.pk]))

        self.assertEqual(response.status_code, 302)
        demande.refresh_from_db()
        self.emp.solde_conge.refresh_from_db()
        self.assertEqual(demande.statut, StatutDemande.VALIDEE)
        self.assertEqual(float(self.emp.solde_conge.jours_disponibles), 3.0)
        self.assertEqual(float(self.emp.solde_conge.jours_utilises), 0.0)

    def test_checkout_before_checkin_blocked_by_model(self):
        p = Pointage(employe=self.emp, date=timezone.localdate(), heure_entree=timezone.now(), heure_sortie=timezone.now() - timedelta(hours=1))
        with self.assertRaises(Exception):
            p.full_clean()

    def test_formation_deadline_before_assignment_blocked(self):
        formation = Formation.objects.create(titre="Securite")
        form = AffectationFormationForm(data={"formation": formation.id, "employe": self.emp.id, "date_limite": timezone.localdate() - timedelta(days=1)})
        self.assertFalse(form.is_valid())

    def test_formation_assignment_form_has_no_department_choice(self):
        form = AffectationFormationForm()
        self.assertIn("employe", form.fields)
        self.assertNotIn("departement", form.fields)

    def test_formation_assignment_targets_only_selected_employee_and_notifies_them(self):
        other_user = User.objects.create_user(username="other", password="emp123")
        other_profile = UtilisateurProfile.objects.create(user=other_user, role=Role.EMPLOYE, employe=self.other)
        formation = Formation.objects.create(titre="Securite ciblee")
        self.client.login(username="rh2", password="rh123")

        response = self.client.post(reverse("formations_admin"), {"formation": formation.id, "employe": self.emp.id, "departement": self.dep.id})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(AffectationFormation.objects.filter(formation=formation, employe=self.emp).exists())
        self.assertFalse(AffectationFormation.objects.filter(formation=formation, employe=self.other).exists())
        self.assertTrue(self.emp.utilisateur_profile.notifications.filter(message__icontains=formation.titre).exists())
        self.assertFalse(Notification.objects.filter(destinataire=other_profile, message__icontains=formation.titre).exists())

    def test_shop_purchase_deducts_once_and_refund_possible(self):
        cat = CategorieProduit.objects.create(nom="Ordinateurs")
        produit = Produit.objects.create(nom="Laptop", categorie=cat, cout_points=40, stock_disponible=2)
        commande = CommandeProduit.objects.create(employe=self.emp, produit=produit, quantite=1, cout_total_points=40)
        approuver_commande(commande, self.rh_user.profile)
        self.emp.compte_points.refresh_from_db()
        self.assertEqual(self.emp.compte_points.solde_points, 60)
        commande.refresh_from_db()
        with self.assertRaises(Exception):
            approuver_commande(commande, self.rh_user.profile)
        self.emp.compte_points.refresh_from_db()
        self.assertEqual(self.emp.compte_points.solde_points, 60)

    def test_employee_sees_only_own_reclamations(self):
        ReclamationRH.objects.create(employe=self.emp, sujet="Mes points", description="Probleme de points", type_reclamation="points")
        ReclamationRH.objects.create(employe=self.other, sujet="Sujet cache", description="Probleme cache", type_reclamation="document")
        self.client.login(username="emp2", password="emp123")
        response = self.client.get(reverse("reclamations"))
        self.assertContains(response, "Mes points")
        self.assertNotContains(response, "Sujet cache")

    def test_document_upload_rejects_disallowed_extension(self):
        self.client.login(username="emp2", password="emp123")
        uploaded = SimpleUploadedFile("payload.exe", b"not safe", content_type="application/octet-stream")

        response = self.client.post(reverse("document_upload"), {"file": uploaded, "categorie": "General"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.emp.documents.count(), 0)

    def test_finalized_admin_request_cannot_be_processed_again(self):
        demande = DemandeAdministrative.objects.create(
            type_demande="Attestation",
            description="Besoin d'une attestation de travail.",
            employe=self.emp,
            statut=StatutDemande.VALIDEE,
        )
        self.client.login(username="rh2", password="rh123")

        response = self.client.post(reverse("demande_process", args=[demande.pk]), {"statut": StatutDemande.REFUSEE, "reponse": "Non"})

        self.assertEqual(response.status_code, 302)
        demande.refresh_from_db()
        self.assertEqual(demande.statut, StatutDemande.VALIDEE)

    def test_admin_request_list_shows_full_detail_and_large_reply_form(self):
        demande = DemandeAdministrative.objects.create(
            type_demande="Attestation",
            description="Besoin d'une attestation de travail avec details complets.",
            employe=self.emp,
        )
        Document.objects.create(
            fichier=SimpleUploadedFile("attestation.pdf", b"pdf", content_type="application/pdf"),
            nom_fichier="attestation.pdf",
            nom_original="attestation.pdf",
            categorie="Demande administrative",
            taille=3,
            employe=self.emp,
            demande_admin=demande,
            uploade_par=self.emp_user,
        )
        self.client.login(username="rh2", password="rh123")

        response = self.client.get(reverse("demandes_list"))

        self.assertContains(response, "<details", html=False)
        self.assertContains(response, "attestation de travail avec details complets.")
        self.assertContains(response, "attestation.pdf")
        self.assertContains(response, '<textarea class="form-control"', html=False)

    def test_position_search_and_change_create_notification_and_audit(self):
        self.client.login(username="rh2", password="rh123")
        response = self.client.get(reverse("position_management"), {"search": "Employe"})
        self.assertContains(response, "Employe Test")
        new_poste = Poste.objects.create(libelle="Chef equipe", rang_hierarchique=45, est_manager=True)
        response = self.client.post(reverse("position_edit", args=[self.emp.pk]), {"poste": new_poste.pk, "departement": self.dep.pk, "service": "", "responsable": self.rh_emp.pk, "actif": "on"})
        self.assertEqual(response.status_code, 302)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.poste_id, new_poste.pk)
        self.assertTrue(self.emp.utilisateur_profile.notifications.filter(message__icontains="poste").exists() if hasattr(self.emp, "utilisateur_profile") else True)
        self.assertTrue(HistoriqueAction.objects.filter(action="CHANGEMENT_POSTE", entite_id=self.emp.pk).exists())

    def test_formation_completion_awards_points_once(self):
        formation = Formation.objects.create(titre="Cyber hygiene", points_recompense=30)
        aff = AffectationFormation.objects.create(formation=formation, employe=self.emp)
        self.client.login(username="emp2", password="emp123")
        self.client.post(reverse("training_status", args=[aff.pk]), {"statut": "terminee"})
        self.emp.compte_points.refresh_from_db()
        self.assertEqual(self.emp.compte_points.solde_points, 130)
        self.assertEqual(TransactionPoints.objects.filter(source="formation", employe=self.emp).count(), 1)
        self.client.post(reverse("training_status", args=[aff.pk]), {"statut": "terminee"})
        self.emp.compte_points.refresh_from_db()
        self.assertEqual(self.emp.compte_points.solde_points, 130)
        self.assertEqual(TransactionPoints.objects.filter(source="formation", employe=self.emp).count(), 1)

    def test_employee_cannot_complete_another_employee_training(self):
        formation = Formation.objects.create(titre="Formation cachee", points_recompense=10)
        aff = AffectationFormation.objects.create(formation=formation, employe=self.other)
        self.client.login(username="emp2", password="emp123")
        response = self.client.post(reverse("training_status", args=[aff.pk]), {"statut": "terminee"})
        self.assertEqual(response.status_code, 404)

    def test_hr_can_update_formation_assignment_status(self):
        formation = Formation.objects.create(titre="Leadership", points_recompense=15)
        aff = AffectationFormation.objects.create(formation=formation, employe=self.emp)
        self.client.login(username="rh2", password="rh123")
        response = self.client.post(reverse("formation_assignment_status", args=[aff.pk]), {"statut": "terminee"})
        self.assertEqual(response.status_code, 302)
        aff.refresh_from_db()
        self.assertEqual(aff.statut, "terminee")
        self.assertTrue(aff.points_attribues)

    def test_hr_can_cancel_completed_formation_without_removing_points(self):
        formation = Formation.objects.create(titre="Leadership annule", points_recompense=15)
        aff = AffectationFormation.objects.create(formation=formation, employe=self.emp)
        self.client.login(username="rh2", password="rh123")

        self.client.post(reverse("formation_assignment_status", args=[aff.pk]), {"statut": "terminee"})
        self.emp.compte_points.refresh_from_db()
        self.assertEqual(self.emp.compte_points.solde_points, 115)

        response = self.client.post(reverse("formation_assignment_status", args=[aff.pk]), {"statut": "annulee"})

        self.assertEqual(response.status_code, 302)
        aff.refresh_from_db()
        self.emp.compte_points.refresh_from_db()
        self.assertEqual(aff.statut, "annulee")
        self.assertTrue(aff.points_attribues)
        self.assertEqual(self.emp.compte_points.solde_points, 115)
        self.assertTrue(self.emp.utilisateur_profile.notifications.filter(message__icontains="annulee").exists())

    def test_employee_cannot_complete_cancelled_training(self):
        formation = Formation.objects.create(titre="Formation annulee", points_recompense=20)
        aff = AffectationFormation.objects.create(formation=formation, employe=self.emp, statut="annulee")
        self.client.login(username="emp2", password="emp123")

        response = self.client.post(reverse("training_status", args=[aff.pk]), {"statut": "terminee"})

        self.assertEqual(response.status_code, 302)
        aff.refresh_from_db()
        self.emp.compte_points.refresh_from_db()
        self.assertEqual(aff.statut, "annulee")
        self.assertEqual(self.emp.compte_points.solde_points, 100)

    def test_audit_filters_load(self):
        HistoriqueAction.objects.create(action="CHANGEMENT_POSTE", details="Test", utilisateur=self.rh_user.profile, entite_concernee="Employe", entite_id=self.emp.pk)
        self.client.login(username="rh2", password="rh123")
        response = self.client.get(reverse("audit_history"), {"role": Role.RESPONSABLE_RH, "module": "Employe", "action": "POSTE"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CHANGEMENT_POSTE")

    def test_hr_sees_all_conversations_employee_only_own(self):
        ConversationRH.objects.create(employe=self.emp, sujet="Mon sujet")
        ConversationRH.objects.create(employe=self.other, sujet="Sujet autre")
        self.client.login(username="emp2", password="emp123")
        response = self.client.get(reverse("rh_messages"))
        self.assertContains(response, "Mon sujet")
        self.assertNotContains(response, "Sujet autre")
        self.client.login(username="rh2", password="rh123")
        response = self.client.get(reverse("rh_messages"))
        self.assertContains(response, "Mon sujet")
        self.assertContains(response, "Sujet autre")

    def test_employee_sees_rh_reply_in_contact_rh(self):
        conv = ConversationRH.objects.create(employe=self.emp, sujet="Question RH", statut="en_attente")
        self.client.login(username="rh2", password="rh123")

        response = self.client.post(reverse("rh_conversation_detail", args=[conv.pk]), {"contenu": "Voici la reponse RH."})

        self.assertEqual(response.status_code, 302)
        conv.refresh_from_db()
        reply = MessageRH.objects.get(conversation=conv, contenu="Voici la reponse RH.")
        self.assertEqual(conv.statut, "ouverte")
        self.assertEqual(reply.destinataire, self.emp.utilisateur_profile)
        self.client.login(username="emp2", password="emp123")
        response = self.client.get(reverse("rh_messages"))
        self.assertContains(response, "Question RH")
        response = self.client.get(reverse("rh_conversation_detail", args=[conv.pk]))
        self.assertContains(response, "Voici la reponse RH.")

    def test_rh_sidebar_does_not_show_audit_link(self):
        self.client.login(username="rh2", password="rh123")
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, "Historique / Audit")
