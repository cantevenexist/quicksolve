from django.shortcuts import get_object_or_404
from django.views import View
from django.http import HttpResponse
from .models import User, UserProfile


class IndexView(View):
    def get(self, request):
        users = User.objects.all()
        
        html = "all users"
        html += "<div><a href='/'>mainpage</a></div>"
        for user in users:
            html += f"<li><a href='/profile/{user.username}/'>{user.username}</a></li>"
        return HttpResponse(html)
    

class ProfileView(View):
    def get(self, request, username):
        user = get_object_or_404(User, username=username)
        user_profile = get_object_or_404(UserProfile, user=user)
        
        # Проверка, является ли пользователь владельцем профиля
        is_owner = request.user.is_authenticated and request.user == user
        
        response_content = (
            f"Username: {user.username}<br>"
            f"About me: {user_profile.about_me}<br>"
        )
        
        # Добавляем информацию о владельце и дополнительные возможности
        if is_owner:
            response_content += "<div><a href='/'>mainpage</a></div>""This is your profile! You can edit it."
            # Здесь можно добавить ссылки для редактирования и т.д.
        else:
            response_content += "<div><a href='/'>mainpage</a></div>"f"This is {user.username}'s profile"
        
        return HttpResponse(response_content)