from django.urls import path
from . import views

urlpatterns = [
    path('profile/', views.IndexView.as_view(), name='profile_list'),
    path('profile/<str:username>/', views.ProfileView.as_view(), name='profile'),
]