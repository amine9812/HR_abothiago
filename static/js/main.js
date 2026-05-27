document.addEventListener("DOMContentLoaded", function () {
    const sidebarToggle = document.getElementById("sidebarToggle");
    if (sidebarToggle) {
        sidebarToggle.addEventListener("click", function () {
            document.body.classList.toggle("sidebar-open");
        });
    }

    document.querySelectorAll(".flash-message").forEach(function (message) {
        setTimeout(function () {
            const alert = bootstrap.Alert.getOrCreateInstance(message);
            alert.close();
        }, 4000);
    });

    const debut = document.getElementById("dateDebut");
    const fin = document.getElementById("dateFin");
    const jours = document.getElementById("nombreJours");
    const calculerJours = function () {
        if (!debut || !fin || !jours || !debut.value || !fin.value) {
            return;
        }
        const start = new Date(debut.value);
        const end = new Date(fin.value);
        const diff = Math.floor((end - start) / 86400000) + 1;
        jours.textContent = diff > 0 ? diff + " jour(s)" : "Dates invalides";
        jours.classList.toggle("text-danger", diff <= 0);
    };
    if (debut && fin) {
        debut.addEventListener("change", calculerJours);
        fin.addEventListener("change", calculerJours);
        calculerJours();
    }

    document.querySelectorAll(".confirm-delete, .confirm-archive").forEach(function (form) {
        form.addEventListener("submit", function (event) {
            const message = form.classList.contains("confirm-archive")
                ? "Confirmer l'archivage de cet element ?"
                : "Confirmer la suppression de cet element ?";
            if (!window.confirm(message)) {
                event.preventDefault();
            }
        });
    });

    const path = window.location.pathname;
    document.querySelectorAll(".sidebar-nav .nav-link, .sidebar-nav .sidebar-subitem").forEach(function (link) {
        const route = link.getAttribute("data-route");
        const isSubitem = link.classList.contains("sidebar-subitem");
        const isActiveRoute = route && (isSubitem ? path === route : (path === route || path.startsWith(route + "/")));
        if (isActiveRoute) {
            link.classList.add("active");
            const group = link.closest(".sidebar-group");
            const submenu = group ? group.querySelector(".collapse") : null;
            const parent = group ? group.querySelector(".sidebar-parent") : null;
            if (submenu && parent) {
                submenu.classList.add("show");
                parent.classList.add("active");
                parent.setAttribute("aria-expanded", "true");
            }
        }
    });

    document.querySelectorAll("input[type='file']").forEach(function (input) {
        input.addEventListener("change", function () {
            const label = input.closest(".file-field")?.querySelector(".selected-file");
            if (label) {
                label.textContent = input.files.length ? input.files[0].name : "Aucun fichier selectionne";
            }
        });
    });

    const planningScope = document.querySelector("select[name='scope']");
    if (planningScope) {
        const togglePlanningFields = function () {
            const scope = planningScope.value;
            const fields = {
                departement: document.querySelector("[name='departement']")?.closest("[class*='col-']"),
                service: document.querySelector("[name='service']")?.closest("[class*='col-']"),
                employes: document.querySelector("[name='employes']")?.closest("[class*='col-']"),
            };
            if (fields.departement) fields.departement.classList.toggle("is-soft-hidden", scope !== "departement" && scope !== "service");
            if (fields.service) fields.service.classList.toggle("is-soft-hidden", scope !== "service");
            if (fields.employes) fields.employes.classList.toggle("is-soft-hidden", scope !== "employees");
        };
        planningScope.addEventListener("change", togglePlanningFields);
        togglePlanningFields();
    }
});
