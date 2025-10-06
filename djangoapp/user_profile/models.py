from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class UserProfile(models.Model):
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='profile'
    )
    about_me = models.TextField(blank=True, null=True)

    def __str__(self):
        return f'Profile of {self.user.username}'