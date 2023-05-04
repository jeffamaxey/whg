from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import auth

def profile(request):
    return render(request, 'accounts/profile.html')

def register(request):
    if request.method != 'POST':
        return render(request, 'accounts/register.html')
    if request.POST['password1'] != request.POST['password2']:
        return render(request, 'accounts/register.html', {'error': 'Sorry, password mismatch!'})
    try:
        User.objects.get(username=request.POST['username'])
        return render(request, 'accounts/register.html', {'error': 'User name is already taken'})
    except User.DoesNotExist:
        user = User.objects.create_user(request.POST['username'], password=request.POST['password1'])
        auth.login(request, user)
        return redirect('home')

def login(request):
    if request.method != 'POST':
        return render(request, 'accounts/login.html')
    user = auth.authenticate(username=request.POST['username'],password=request.POST['password'])
    if user is not None:
        auth.login(request,user)
        return redirect('dashboard')
    else:
        return redirect('home', {'error': 'username or password is incorrect :^('})

def logout(request):
    if request.method == 'POST':
        auth.logout(request)
        return redirect('home')
