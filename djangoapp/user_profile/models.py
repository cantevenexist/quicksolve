from django.db import models
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()

class UserProfile(models.Model):
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE, 
        related_name='profile'
    )
    about_me = models.TextField(blank=True, null=True)
    unique_code = models.CharField(
        max_length=20, 
        unique=True, 
        blank=True, 
        null=True,
        verbose_name="Unique Code"
    )

    def __str__(self):
        return f'{self.user.username}'

    def save(self, *args, **kwargs):
        """Автоматически генерирует уникальный код при создании профиля"""
        if not self.unique_code:
            code = str(uuid.uuid4())[:12].upper().replace('-', '')
            # Убедимся, что код уникален
            while UserProfile.objects.filter(unique_code=code).exists():
                code = str(uuid.uuid4())[:12].upper().replace('-', '')
            self.unique_code = code
        super().save(*args, **kwargs)