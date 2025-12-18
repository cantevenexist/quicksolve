from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from .models import User, UserProfile, Notification
from .forms import UserProfileForm
from django.http import JsonResponse
import uuid

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


class RegenerateUniqueCodeView(LoginRequiredMixin, View):
    """Представление для генерации нового уникального кода"""
    
    def post(self, request, *args, **kwargs):
        # Проверяем, что запрос пришел через AJAX
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        profile = get_object_or_404(UserProfile, user=request.user)
        
        # Генерируем новый уникальный код
        new_code = str(uuid.uuid4())[:12].upper().replace('-', '')
        
        # Проверяем уникальность
        while UserProfile.objects.filter(unique_code=new_code).exists():
            new_code = str(uuid.uuid4())[:12].upper().replace('-', '')
        
        # Сохраняем новый код
        old_code = profile.unique_code
        profile.unique_code = new_code
        profile.save()
        
        return JsonResponse({
            'success': True,
            'new_code': profile.unique_code,
            'message': 'Код успешно обновлен!'
        })


class NotificationDetailView(LoginRequiredMixin, View):
    """Получить детали уведомления"""
    
    def get(self, request, notification_id):
        notification = get_object_or_404(Notification, id=notification_id, user=request.user)
        
        return JsonResponse({
            'success': True,
            'notification': {
                'id': notification.id,
                'message': notification.message,
                'level': notification.level,
                'is_read': notification.is_read,
                'created_at': notification.created_at,
                'related_url': notification.related_url or ''
            }
        })

class AllNotificationsView(LoginRequiredMixin, View):
    """Получить все уведомления пользователя"""
    
    def get(self, request):
        notifications = Notification.objects.filter(user=request.user)
        
        notifications_data = []
        for notification in notifications:
            notifications_data.append({
                'id': notification.id,
                'message': notification.message,
                'level': notification.level,
                'is_read': notification.is_read,
                'created_at': notification.created_at.strftime("%d.%m.%Y %H:%M"),
                'related_url': notification.related_url or ''
            })
        
        return JsonResponse({
            'success': True,
            'notifications': notifications_data
        })

class MarkNotificationReadView(LoginRequiredMixin, View):
    """Пометить уведомление как прочитанное"""
    
    def post(self, request, notification_id):
        # Проверяем, что запрос пришел через AJAX
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        notification = get_object_or_404(Notification, id=notification_id, user=request.user)
        notification.is_read = True
        notification.save()
        
        return JsonResponse({'success': True})