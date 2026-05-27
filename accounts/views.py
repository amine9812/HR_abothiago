from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        username = request.POST.get("login") or request.POST.get("username")
        password = request.POST.get("password") or request.POST.get("motDePasse")
        user = authenticate(request, username=username, password=password)
        if user is not None and getattr(getattr(user, "profile", None), "actif", True):
            login(request, user)
            return redirect("dashboard")
        messages.error(request, "Login ou mot de passe incorrect.")
    return render(request, "auth/login.html")


def logout_view(request):
    if request.method == "POST":
        logout(request)
        messages.success(request, "Vous etes deconnecte.")
    return redirect("login")
