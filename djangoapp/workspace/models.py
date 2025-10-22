from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
import hashlib
import time
import uuid

class Workspace(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, default='Новая рабочая область')
    access_users = models.ManyToManyField(User, blank=True, related_name='accessible_workspaces')
    url_hash = models.CharField(max_length=64, unique=True, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.url_hash:
            server_time = str(time.time())
            hash_input = f"{self.name}{server_time}{self.user.username}{uuid.uuid4()}"
            self.url_hash = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name}'

    def get_all_members(self):
        """Возвращает всех участников workspace (владелец + приглашенные)"""
        return User.objects.filter(
            models.Q(id=self.user_id) | 
            models.Q(accessible_workspaces=self)
        ).distinct()
    
    def has_access(self, user):
        """Проверяет, есть ли у пользователя доступ к workspace"""
        return user == self.user or user in self.access_users.all()


class Team(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, default='Новая команда')
    members = models.ManyToManyField(User, through='TeamMembership')
    url_hash = models.CharField(max_length=64, unique=True, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.url_hash:
            server_time = str(time.time())
            hash_input = f"{self.name}{server_time}{self.workspace.name}{uuid.uuid4()}"
            self.url_hash = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name}'


class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, default='member')
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['team', 'user']

    def clean(self):
        """Проверяем, что пользователь является участником workspace"""
        workspace_members = self.team.workspace.get_all_members()
        if self.user not in workspace_members:
            raise ValidationError(
                f"Пользователь {self.user.username} не является участником рабочей области {self.team.workspace.name}"
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.user.username} - {self.team.name}'


class Task(models.Model):
    STATUS_CHOICES = [
        ('backlog', 'Бэклог'),
        ('todo', 'К выполнению'),
        ('in_progress', 'В работе'),
        ('review', 'На проверке'),
        ('done', 'Выполнено'),
    ]
    
    workspace = models.ForeignKey(
        Workspace, 
        on_delete=models.CASCADE,
        verbose_name='Рабочая область'
    )
    team = models.ForeignKey(
        Team, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name='Команда'
    )
    title = models.CharField(
        max_length=255,
        verbose_name='Название задачи'
    )
    description = models.TextField(
        blank=True, 
        null=True,
        verbose_name='Описание'
    )
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='backlog',
        verbose_name='Статус'
    )
    assignee = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='assigned_tasks',
        verbose_name='Исполнитель'
    )
    reporter = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='reported_tasks',
        verbose_name='Автор'
    )
    url_hash = models.CharField(
        max_length=64, 
        unique=True, 
        blank=True, 
        null=True
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )

    class Meta:
        verbose_name = 'Задача'
        verbose_name_plural = 'Задачи'
        ordering = ['-created_at']

    def clean(self):
        """Валидация данных задачи"""
        errors = {}

        # Проверяем, что автор состоит в workspace
        if self.workspace and self.reporter:
            workspace_members = self.workspace.get_all_members()
            if self.reporter not in workspace_members:
                errors['reporter'] = 'Автор задачи должен быть участником рабочей области'

        # Проверяем, что команда принадлежит workspace
        if self.team and self.workspace:
            if self.team.workspace != self.workspace:
                errors['team'] = 'Команда должна принадлежать той же рабочей области'

        # Проверяем, что исполнитель состоит в команде (если команда указана)
        if self.assignee and self.team:
            if not self.team.members.filter(id=self.assignee.id).exists():
                errors['assignee'] = f'Исполнитель не состоит в команде {self.team.name}'

        # Проверяем, что исполнитель состоит в workspace (если команда не указана)
        if self.assignee and not self.team and self.workspace:
            workspace_members = self.workspace.get_all_members()
            if self.assignee not in workspace_members:
                errors['assignee'] = 'Исполнитель должен быть участником рабочей области'

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Генерируем URL hash если его нет
        if not self.url_hash:
            server_time = str(time.time())
            hash_input = f"{self.title}{server_time}{self.workspace.name}{uuid.uuid4()}"
            self.url_hash = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
        
        # Выполняем валидацию
        self.clean()
        super().save(*args, **kwargs)

    def get_available_assignees(self):
        """Возвращает доступных исполнителей для задачи"""
        if self.team:
            # Если есть команда - только участники команды
            return self.team.members.all()
        else:
            # Если команды нет - все участники workspace
            return self.workspace.get_all_members()

    def __str__(self):
        return f'{self.title} (Workspace: {self.workspace.name})'