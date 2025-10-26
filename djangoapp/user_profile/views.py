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
            'user_profile': user_profile,
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
            'user_profile': user_profile,
        }
        
        return render(request, self.template_name, context)


from django.http import JsonResponse
from django.shortcuts import get_object_or_404
import uuid

class RegenerateUniqueCodeView(LoginRequiredMixin, View):
    """Представление для генерации нового уникального кода"""
    
    def generate_unique_code(self):
        """Генерация уникального кода"""
        return str(uuid.uuid4())[:12].upper().replace('-', '')
    
    def get(self, request, *args, **kwargs):
        # При прямом GET запросе показываем 404
        from django.http import Http404
        raise Http404("Page not found")
    
    def post(self, request, *args, **kwargs):
        # Проверяем, что запрос пришел через AJAX
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            # Если не AJAX, показываем 404
            from django.http import Http404
            raise Http404("Page not found")
        
        profile = get_object_or_404(UserProfile, user=request.user)
        
        # Генерируем новый уникальный код
        new_code = self.generate_unique_code()
        
        # Проверяем уникальность (на всякий случай)
        while UserProfile.objects.filter(unique_code=new_code).exists():
            new_code = self.generate_unique_code()
        
        # Сохраняем новый код
        old_code = profile.unique_code
        profile.unique_code = new_code
        profile.save()
        
        return JsonResponse({
            'success': True,
            'new_code': profile.unique_code,
        })