from django.contrib import messages
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.shortcuts import redirect, render

from .exceptions import ServiceError
from .forms import LoginForm
from .services import authenticate_user


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard:index')

    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        username = form.cleaned_data['username']
        password = form.cleaned_data['password']
        try:
            user = authenticate_user(username, password)
        except ServiceError as exc:
            messages.error(request, exc.message)
        else:
            django_login(request, user, backend='accounts.backends.LDAPOrLocalBackend')
            return redirect('dashboard:index')

    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    django_logout(request)
    messages.success(request, 'Anda telah logout.')
    return redirect('accounts:login')
