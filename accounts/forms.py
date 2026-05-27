from django import forms
from django.contrib.auth.forms import AuthenticationForm


class LoginForm(AuthenticationForm):
    username = forms.CharField(label="Login", widget=forms.TextInput(attrs={"name": "login", "class": "form-control"}))
    password = forms.CharField(label="Mot de passe", widget=forms.PasswordInput(attrs={"class": "form-control"}))
