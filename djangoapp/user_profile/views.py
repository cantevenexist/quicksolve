from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from .models import User, UserProfile
from .forms import UserProfileForm


class MyProfileView(LoginRequiredMixin, View):
    def get(self, request):
        return redirect('profile', username=request.user.username)


class ProfileView(View):
    template_name = 'profile/profile.html'
    
    def get(self, request, username):
        user = get_object_or_404(User, username=username)
        user_profile = get_object_or_404(UserProfile, user=user)
        
        is_owner = request.user.is_authenticated and request.user == user
        
        context = {
            'profile_user': user,
            'user_profile': user_profile,
            'is_owner': is_owner,
        }
        
        return render(request, self.template_name, context)


class ProfileEditView(LoginRequiredMixin, View):
    template_name = 'profile/profile_edit.html'
    
    def get(self, request):
        user_profile = get_object_or_404(UserProfile, user=request.user)
        form = UserProfileForm(instance=user_profile)
        
        context = {
            'form': form,
            'profile_user': request.user,
        }
        
        return render(request, self.template_name, context)
    
    def post(self, request):
        user_profile = get_object_or_404(UserProfile, user=request.user)
        form = UserProfileForm(request.POST, instance=user_profile)
        
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully!")
            return redirect('profile', username=request.user.username)
        
        context = {
            'form': form,
            'profile_user': request.user,
        }
        
        return render(request, self.template_name, context)