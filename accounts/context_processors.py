def current_profile(request):
    profile = None
    notifications_non_lues = 0
    nav_module = ""
    nav_item = ""
    active_tab = ""
    if request.user.is_authenticated:
        profile = getattr(request.user, "profile", None)
        if profile:
            notifications_non_lues = profile.notifications.filter(lue=False).count()
    match = getattr(request, "resolver_match", None)
    url_name = match.url_name if match else ""
    employe_urls = {
        "employes_list": "employes_list",
        "employe_create": "employes_list",
        "employe_detail": "employes_list",
        "employe_update": "employes_list",
        "hierarchy_tree": "hierarchy_tree",
        "position_management": "position_management",
        "position_edit": "position_management",
        "formations_admin": "formations_admin",
        "formation_create": "formations_admin",
        "formation_assignment_status": "formations_admin",
        "payroll_analytics": "payroll_analytics",
        "salary_edit": "payroll_analytics",
        "my_trainings": "my_trainings",
        "training_status": "my_trainings",
    }
    departement_urls = {
        "departements_list",
        "departement_create",
        "departement_update",
        "departement_save",
        "service_save",
        "poste_save",
        "departement_delete",
        "service_delete",
        "poste_delete",
    }
    if url_name in employe_urls:
        nav_module = "employes"
        nav_item = employe_urls[url_name]
    elif url_name in departement_urls:
        nav_module = "departements"
        active_tab = request.GET.get("tab", "departements")
        nav_item = f"departements_{active_tab if active_tab in {'departements', 'services', 'postes'} else 'departements'}"
    return {
        "utilisateur_connecte": profile,
        "notifications_non_lues": notifications_non_lues,
        "nav_module": nav_module,
        "nav_item": nav_item,
    }
