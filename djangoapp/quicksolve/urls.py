from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("", include("main_page.urls")),
    path("admin/", admin.site.urls),
    path('account/', include('allauth.urls')),
    path('', include('user_profile.urls')),
]