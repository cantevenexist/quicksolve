from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.contrib import messages
from django.http import JsonResponse
from django.views import View
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.db import transaction
from django.contrib.auth import authenticate
import json
User = get_user_model()
from .models import Workspace, WorkspaceMembership, Team, TeamMembership, Task, IndividualInvitation, WorkspaceRoleAccess, TeamRoleAccess
from .forms import WorkspaceCreateForm, TeamCreateForm, TaskCreateForm, MassInvitationForm, IndividualInvitationForm
from user_profile.models import UserProfile, Notification
from django import forms


class WorkspaceIndexView(LoginRequiredMixin, ListView):
    template_name = 'workspace/workspace_index.html'
    context_object_name = 'workspaces'

    def get_queryset(self):
        return Workspace.objects.filter(
            workspacemembership__user=self.request.user
        ).distinct()


class WorkspaceCreateView(LoginRequiredMixin, CreateView):
    model = Workspace
    form_class = WorkspaceCreateForm
    template_name = 'workspace/workspace_create.html'
    success_url = reverse_lazy('workspace:workspace_index')

    def form_valid(self, form):
        form.instance.user = self.request.user
        response = super().form_valid(form)
        
        # Создаем настройки прав доступа по умолчанию для workspace
        WorkspaceRoleAccess.objects.create(workspace=self.object)
        
        messages.success(self.request, 'Рабочая область успешно создана!')
        return response


class WorkspaceDetailView(LoginRequiredMixin, DetailView):
    model = Workspace
    template_name = 'workspace/workspace_detail.html'
    slug_field = 'url_hash'
    slug_url_kwarg = 'workspace_url_hash'

    def get_queryset(self):
        return Workspace.objects.filter(
            workspacemembership__user=self.request.user
        ).distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        workspace = self.get_object()
        
        # Получаем настройки прав доступа
        role_access, created = WorkspaceRoleAccess.objects.get_or_create(workspace=workspace)
        context['role_access'] = role_access
        
        # Право создавать задачи в workspace
        can_create_task_in_workspace = role_access.has_permission(self.request.user, 'can_create_tasks')
        
        # Право создавать задачи в командах, где он состоит
        user_teams = Team.objects.filter(
            workspace=workspace,
            members=self.request.user
        )
        
        can_create_in_any_team = False
        for team in user_teams:
            team_access, _ = TeamRoleAccess.objects.get_or_create(team=team)
            if team_access.has_permission(self.request.user, 'can_create_tasks'):
                can_create_in_any_team = True
                break
        
        if can_create_task_in_workspace or can_create_in_any_team: context['can_create_tasks'] = True
        else: context['can_create_tasks'] = False


        # ДОБАВЛЯЕМ ПРАВА ПОЛЬЗОВАТЕЛЯ В КОНТЕКСТ
        context['can_edit_workspace'] = role_access.has_permission(self.request.user, 'can_edit_workspace')
        context['can_manage_access'] = role_access.has_permission(self.request.user, 'can_manage_access')
        context['can_create_teams'] = role_access.has_permission(self.request.user, 'can_create_teams')
        # context['can_create_tasks'] = role_access.has_permission(self.request.user, 'can_create_tasks')
        context['can_invite_users'] = role_access.has_permission(self.request.user, 'can_invite_users')
        context['can_edit_tasks'] = role_access.has_permission(self.request.user, 'can_edit_tasks')
        context['can_delete_tasks'] = role_access.has_permission(self.request.user, 'can_delete_tasks')
        context['can_view_all_tasks'] = role_access.has_permission(self.request.user, 'can_view_all_tasks')
        context['can_view_all_teams'] = role_access.has_permission(self.request.user, 'can_view_all_teams')
        
        # Получаем команды с учетом видимости
        user_teams = Team.objects.filter(
            workspace=workspace,
            teammembership__user=self.request.user
        )
        
        # Все команды workspace для владельцев и администраторов
        if workspace.get_user_role(self.request.user) in ['owner', 'admin'] or context['can_view_all_teams']:
            context['teams'] = Team.objects.filter(workspace=workspace)
        else:
            # Для обычных пользователей - только команды, которые они видят
            visible_teams = []
            all_teams = Team.objects.filter(workspace=workspace)
            for team in all_teams:
                team_access, _ = TeamRoleAccess.objects.get_or_create(team=team)
                if team_access.is_team_visible_to_user(self.request.user):
                    visible_teams.append(team)
            context['teams'] = visible_teams
        
        # Получаем membership текущего пользователя
        workspace_user_membership = WorkspaceMembership.objects.filter(
            workspace=workspace, 
            user=self.request.user
        ).first()
        
        # Добавляем user_membership в контекст
        context['workspace_user_membership'] = workspace_user_membership
        
        # Проверяем права доступа для задач
        if context['can_view_all_tasks']:
            context['tasks'] = Task.objects.filter(workspace=workspace)
        else:
            # Показываем только задачи команд, в которых состоит пользователь
            context['tasks'] = Task.objects.filter(
                workspace=workspace, 
                team__in=user_teams
            )
        
        # Добавляем информацию о членах workspace
        context['members'] = WorkspaceMembership.objects.filter(workspace=workspace).select_related('user')
        context['user_role'] = workspace.get_user_role(self.request.user)
        
        # Добавляем данные массового приглашения в контекст
        context['mass_invitation_url'] = workspace.get_mass_invitation_url(self.request)
        context['mass_invitation_data'] = {
            'expiration_time': workspace.get_mass_invitation_expiration_display(),
            'max_uses': workspace.mass_invitation_max_uses or 'Без ограничений',
            'current_uses': workspace.mass_invitation_current_uses,
            'is_active': workspace.mass_invitation_is_active,
            'can_be_used': workspace.can_mass_invitation_be_used(),
        }
        
        return context


class WorkspaceEditView(LoginRequiredMixin, View):
    """Представление для редактирования основных настроек рабочей области"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        workspace = get_object_or_404(
            Workspace, 
            url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем, имеет ли пользователь право редактировать рабочую область
        can_edit = self.check_edit_permission(request.user, workspace)
        
        if not can_edit:
            return JsonResponse({
                'success': False, 
                'error': 'У вас нет прав для редактирования рабочей области'
            })
        
        # Получаем данные из запроса
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        
        # Валидация данных
        validation_error = self.validate_workspace_data(name, description)
        if validation_error:
            return JsonResponse({
                'success': False,
                'error': validation_error
            })
        
        try:
            # Сохраняем изменения в транзакции
            with transaction.atomic():
                # Сохраняем старые значения для логирования
                old_name = workspace.name
                old_description = workspace.description
                
                # Обновляем данные рабочей области
                workspace.name = name
                workspace.description = description if description else None
                workspace.save()
                
                # Логируем изменения
                changes = []
                if old_name != name:
                    changes.append(f'Название: "{old_name}" → "{name}"')
                if old_description != description:
                    if old_description and not description:
                        changes.append('Описание удалено')
                    elif not old_description and description:
                        changes.append(f'Добавлено описание')
                    elif old_description != description:
                        changes.append(f'Описание обновлено')
                
                # Создаем уведомление для пользователя
                self.create_edit_notification(request.user, workspace, changes)
                
                return JsonResponse({
                    'success': True,
                    'message': 'Настройки рабочей области успешно обновлены',
                    'workspace': {
                        'id': workspace.id,
                        'name': workspace.name,
                        'description': workspace.description or '',
                        'url_hash': workspace.url_hash
                    },
                    'changes': changes,
                    'updated_at': timezone.now().isoformat()
                })
                
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Ошибка при редактировании рабочей области: {str(e)}", exc_info=True)
            
            return JsonResponse({
                'success': False,
                'error': 'Произошла внутренняя ошибка сервера',
                'debug_info': str(e) if settings.DEBUG else None
            })
    
    def check_edit_permission(self, user, workspace):
        """Проверяет права пользователя на редактирование команды"""
        # Проверяем право на редактирование через TeamRoleAccess
        workspace_access, _ = WorkspaceRoleAccess.objects.get_or_create(workspace=workspace)
        
        # Если у пользователя есть право can_edit_team через TeamRoleAccess
        if workspace_access.has_permission(user, 'can_edit_team'):
            return True
        
        # Проверяем, является ли пользователь владельцем workspace
        workspace_membership = WorkspaceMembership.objects.filter(
            workspace=workspace,
            user=user,
            role='owner'
        ).first()
        
        if workspace_membership:
            return True
        
        return False
    
    def validate_workspace_data(self, name, description):
        """Валидация данных команды"""
        if not name:
            return 'Название команды не может быть пустым'
        
        if len(name) > 255:
            return 'Название команды не может превышать 255 символов'
        
        if len(description) > 255:
            return 'Описание команды не может превышать 255 символов'

        return None
    
    def create_edit_notification(self, user, workspace, changes):
        """Создает уведомление об изменениях рабочей области"""
        if changes:
            message = f'Вы обновили настройки рабочей области "{workspace.name}":\n'
            message += '\n'.join([f'• {change}' for change in changes])
            
            # В реальном приложении здесь можно создать Notification
            # Notification.objects.create(
            #     user=user,
            #     message=message,
            #     level='info'
            # )
            
            print(f"Уведомление для {user.username}: {message}")


class WorkspaceDeleteView(LoginRequiredMixin, View):
    """Представление для удаления рабочей области"""
    
    def post(self, request, *args, **kwargs):
        # Проверяем AJAX запрос
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        # Получаем рабочую область
        workspace = get_object_or_404(
            Workspace, 
            url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем, является ли пользователь владельцем
        if not self.check_owner_permission(request.user, workspace):
            return JsonResponse({
                'success': False, 
                'error': 'Только владелец рабочей области может её удалить'
            })
        
        # Получаем пароль для подтверждения
        password = request.POST.get('password', '').strip()
        
        # Проверяем пароль
        user = authenticate(username=request.user.username, password=password)
        if not user:
            return JsonResponse({
                'success': False,
                'error': 'Неверный пароль. Пожалуйста, подтвердите вашу личность'
            })
        
        try:
            # Собираем статистику перед удалением
            stats = self.collect_deletion_stats(workspace)
            
            # Удаляем в транзакции
            with transaction.atomic():
                # Сохраняем информацию для уведомлений
                workspace_name = workspace.name
                workspace_id = workspace.id
                workspace_owner = request.user
                
                # Удаляем рабочую область (каскадное удаление настроено в моделях)
                workspace.delete()
                
                # Создаем уведомление для владельца
                self.create_deletion_notification(request.user, workspace_name, stats)
                
                # Отправляем уведомления участникам
                self.notify_workspace_members(workspace_id, workspace_name, workspace_owner)
                
                return JsonResponse({
                    'success': True,
                    'message': 'Рабочая область успешно удалена',
                    'stats': stats,
                    'redirect_url': '/workspace/'  # URL для перенаправления
                })
                
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Ошибка при удалении рабочей области: {str(e)}", exc_info=True)
            
            return JsonResponse({
                'success': False,
                'error': 'Произошла внутренняя ошибка сервера при удалении',
                'debug_info': str(e) if settings.DEBUG else None
            })
    
    def check_owner_permission(self, user, workspace):
        """Проверяет, является ли пользователь владельцем рабочей области"""
        try:
            membership = WorkspaceMembership.objects.get(
                workspace=workspace,
                user=user
            )
            return membership.role == 'owner'
        except WorkspaceMembership.DoesNotExist:
            return False
    
    def collect_deletion_stats(self, workspace):
        """Собирает статистику перед удалением"""
        return {
            'workspace_name': workspace.name,
            'teams_count': Team.objects.filter(workspace=workspace).count(),
            'tasks_count': Task.objects.filter(team__workspace=workspace).count(),
            'members_count': WorkspaceMembership.objects.filter(workspace=workspace).count(),
        }
    
    def create_deletion_notification(self, user, workspace_name, stats):
        """Создает уведомление об удалении рабочей области"""
        message = f'Вы удалили рабочую область "{workspace_name}"\n\n'
        message += f'Статистика удаления:\n'
        message += f'• Команд: {stats["teams_count"]}\n'
        message += f'• Задач: {stats["tasks_count"]}\n'
        message += f'• Участников: {stats["members_count"]}\n'
        
        Notification.objects.create(
            user=user,
            message=message,
            level='warning',
        )
    
    def notify_workspace_members(self, workspace_id, workspace_name, owner):
        """Отправляет уведомления всем участникам рабочей области"""
        # Получаем всех участников рабочей области кроме владельца
        memberships = WorkspaceMembership.objects.filter(workspace_id=workspace_id)
        
        for membership in memberships:
            if membership.user != owner:
                message = f'Рабочая область "{workspace_name}", в которой вы участвовали, была удалена её владельцем.'
                
                Notification.objects.create(
                    user=membership.user,
                    message=message,
                    level='info',
                )


class TeamCreateView(LoginRequiredMixin, CreateView):
    model = Team
    form_class = TeamCreateForm
    template_name = 'workspace/team_create.html'

    def dispatch(self, request, *args, **kwargs):
        self.workspace = get_object_or_404(
            Workspace, 
            url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем право на создание команд
        role_access, created = WorkspaceRoleAccess.objects.get_or_create(workspace=self.workspace)
        if not role_access.has_permission(request.user, 'can_create_teams'):
            from django.http import Http404
            raise Http404("У вас нет прав для создания команд")
            
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.workspace = self.workspace
        response = super().form_valid(form)
        
        # Добавляем создателя в команду с ролью лидера
        TeamMembership.objects.create(
            team=self.object,
            user=self.request.user,
            role='leader'
        )
        
        # Создаем настройки прав доступа по умолчанию для команды
        TeamRoleAccess.objects.create(team=self.object)
        
        messages.success(self.request, 'Команда успешно создана!')
        return response

    def get_success_url(self):
        return reverse_lazy('workspace:workspace_detail', kwargs={
            'workspace_url_hash': self.workspace.url_hash
        })

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['workspace'] = self.workspace
        return context


class TeamDetailView(LoginRequiredMixin, DetailView):
    model = Team
    template_name = 'workspace/team_detail.html'
    slug_field = 'url_hash'
    slug_url_kwarg = 'team_url_hash'

    def dispatch(self, request, *args, **kwargs):
        # Проверяем видимость команды
        team = get_object_or_404(
            Team,
            url_hash=kwargs['team_url_hash'],
            workspace__url_hash=kwargs['workspace_url_hash']
        )
        
        team_access, _ = TeamRoleAccess.objects.get_or_create(team=team)
        if not team_access.is_team_visible_to_user(request.user):
            from django.http import Http404
            raise Http404("У вас нет доступа к этой команде")
            
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        user_workspaces = Workspace.objects.filter(
            workspacemembership__user=self.request.user
        )
        return Team.objects.filter(
            workspace__url_hash=self.kwargs['workspace_url_hash'],
            workspace__in=user_workspaces
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        team = self.get_object()
        
        # Получаем настройки прав доступа команды
        team_access, created = TeamRoleAccess.objects.get_or_create(team=team)
        workspace_access, created = WorkspaceRoleAccess.objects.get_or_create(workspace=team.workspace)

        context['team_access'] = team_access
        context['workspace_access'] = workspace_access  # Добавляем workspace_access для шаблона
        
        # Права для workspace
        context['can_create_tasks_in_workspace'] = workspace_access.has_permission(self.request.user, 'can_create_tasks')
        context['can_edit_tasks_in_workspace'] = workspace_access.has_permission(self.request.user, 'can_edit_tasks')
        context['can_delete_tasks_in_workspace'] = workspace_access.has_permission(self.request.user, 'can_delete_tasks')

        # Права для команды
        context['is_member'] = team.members.filter(id=self.request.user.id).exists()
        context['can_manage_access'] = team_access.has_permission(self.request.user, 'can_manage_access')
        context['can_edit_team'] = team_access.has_permission(self.request.user, 'can_edit_team')
        context['can_invite_users'] = team_access.has_permission(self.request.user, 'can_invite_users')
        context['can_create_tasks_in_team'] = team_access.has_permission(self.request.user, 'can_create_tasks')
        context['can_edit_tasks_in_team'] = team_access.has_permission(self.request.user, 'can_edit_tasks')
        context['can_delete_tasks_in_team'] = team_access.has_permission(self.request.user, 'can_delete_tasks')
        
        # Получаем текущих участников команды
        team_members = TeamMembership.objects.filter(team=team).select_related('user')
        
        # Получаем всех пользователей рабочей области
        workspace_members = WorkspaceMembership.objects.filter(
            workspace=team.workspace
        ).select_related('user')
        
        # Создаем список ID пользователей, которые уже в команде
        team_member_ids = set(team_members.values_list('user_id', flat=True))
        
        # Фильтруем пользователей рабочей области, исключая тех, кто уже в команде
        available_users = [
            member for member in workspace_members 
            if member.user_id not in team_member_ids
        ]
        
        # Получаем membership текущего пользователя
        workspace_user_membership = WorkspaceMembership.objects.filter(
            workspace=team.workspace,
            user=self.request.user
        ).first()
        
        team_user_membership = TeamMembership.objects.filter(
            team=team, 
            user=self.request.user
        ).first()
        
        # Получаем списки пользователей для назначения и разжалования
        members_for_promotion = [member for member in team_members if member.role == 'member']
        members_for_demotion = [member for member in team_members if member.role == 'admin']
        
        context['tasks'] = Task.objects.filter(team=team)
        context['is_team_member'] = team.members.filter(id=self.request.user.id).exists()
        context['team_members'] = team_members
        context['workspace_members'] = available_users
        context['team_members_users'] = [member.user for member in team_members]
        context['workspace_user_membership'] = workspace_user_membership  # Добавляем информацию о текущем пользователе рабочего пространства
        context['team_user_membership'] = team_user_membership  # Добавляем информацию о текущем пользователе рабочего пространства
        context['members_for_promotion'] = members_for_promotion  # Участники для назначения администраторами
        context['members_for_demotion'] = members_for_demotion    # Администраторы для разжалования
        
        return context


class TeamEditView(LoginRequiredMixin, View):
    """Представление для редактирования основных настроек команды"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        team = get_object_or_404(
            Team, 
            url_hash=kwargs['team_url_hash'],
            workspace__url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем, имеет ли пользователь право редактировать команду
        can_edit = self.check_edit_permission(request.user, team)
        
        if not can_edit:
            return JsonResponse({
                'success': False, 
                'error': 'У вас нет прав для редактирования команды'
            })
        
        # Получаем данные из запроса
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        
        # Валидация данных
        validation_error = self.validate_team_data(name, description)
        if validation_error:
            return JsonResponse({
                'success': False,
                'error': validation_error
            })
        
        try:
            # Сохраняем изменения в транзакции
            with transaction.atomic():
                # Сохраняем старые значения для логирования
                old_name = team.name
                old_description = team.description
                
                # Обновляем данные команды
                team.name = name
                team.description = description if description else None
                team.save()
                
                # Логируем изменения
                changes = []
                if old_name != name:
                    changes.append(f'Название: "{old_name}" → "{name}"')
                if old_description != description:
                    if old_description and not description:
                        changes.append('Описание удалено')
                    elif not old_description and description:
                        changes.append(f'Добавлено описание')
                    elif old_description != description:
                        changes.append(f'Описание обновлено')
                
                # Создаем уведомление для пользователя
                self.create_edit_notification(request.user, team, changes)
                
                return JsonResponse({
                    'success': True,
                    'message': 'Настройки команды успешно обновлены',
                    'team': {
                        'id': team.id,
                        'name': team.name,
                        'description': team.description or '',
                        'url_hash': team.url_hash
                    },
                    'changes': changes,
                    'updated_at': timezone.now().isoformat()
                })
                
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Ошибка при редактировании команды: {str(e)}", exc_info=True)
            
            return JsonResponse({
                'success': False,
                'error': 'Произошла внутренняя ошибка сервера',
                'debug_info': str(e) if settings.DEBUG else None
            })
    
    def check_edit_permission(self, user, team):
        """Проверяет права пользователя на редактирование команды"""
        # Проверяем право на редактирование через TeamRoleAccess
        team_access, _ = TeamRoleAccess.objects.get_or_create(team=team)
        
        # Если у пользователя есть право can_edit_team через TeamRoleAccess
        if team_access.has_permission(user, 'can_edit_team'):
            return True
        
        # Проверяем, является ли пользователь лидером команды
        team_membership = TeamMembership.objects.filter(
            team=team,
            user=user,
            role='leader'
        ).first()
        
        if team_membership:
            return True
        
        # Проверяем, является ли пользователь владельцем workspace
        workspace_membership = WorkspaceMembership.objects.filter(
            workspace=team.workspace,
            user=user,
            role='owner'
        ).first()
        
        if workspace_membership:
            return True
        
        return False
    
    def validate_team_data(self, name, description):
        """Валидация данных команды"""
        if not name:
            return 'Название команды не может быть пустым'
        
        if len(name) > 255:
            return 'Название команды не может превышать 255 символов'
        
        if len(description) > 255:
            return 'Описание команды не может превышать 255 символов'

        return None
    
    def create_edit_notification(self, user, team, changes):
        """Создает уведомление об изменениях команды"""
        if changes:
            message = f'Вы обновили настройки команды "{team.name}":\n'
            message += '\n'.join([f'• {change}' for change in changes])
            
            # В реальном приложении здесь можно создать Notification
            # Notification.objects.create(
            #     user=user,
            #     message=message,
            #     level='info'
            # )
            
            print(f"Уведомление для {user.username}: {message}")


class TaskListView(LoginRequiredMixin, ListView):
    model = Task
    template_name = 'workspace/task_list.html'
    context_object_name = 'tasks'
    # paginate_by = 20

    def dispatch(self, request, *args, **kwargs):
        self.workspace = get_object_or_404(
            Workspace, 
            url_hash=kwargs['workspace_url_hash']
        )
        if not self.workspace.has_access(request.user):
            from django.http import Http404
            raise Http404("У вас нет доступа к этой рабочей области")
        
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        # Начинаем с фильтрации по workspace
        queryset = Task.objects.filter(workspace=self.workspace)
        
        # Фильтрация по команде через GET параметр
        team_filter = self.request.GET.get('team')
        if team_filter:
            queryset = queryset.filter(team__url_hash=team_filter)
        
        # Фильтрация по приоритету через GET параметр
        priority_filter = self.request.GET.get('priority')
        if priority_filter:
            queryset = queryset.filter(priority=priority_filter)
        
        # Фильтрация по статусу через GET параметр
        status_filter = self.request.GET.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Фильтрация по дедлайну через GET параметр
        deadline_filter = self.request.GET.get('deadline')
        if deadline_filter:
            if deadline_filter == 'expired':
                queryset = queryset.filter(deadline__lt=timezone.now())
            elif deadline_filter == 'today':
                today = timezone.now().date()
                queryset = queryset.filter(
                    deadline__date=today
                )
            elif deadline_filter == 'week':
                week_end = timezone.now() + timezone.timedelta(days=7)
                queryset = queryset.filter(
                    deadline__range=[timezone.now(), week_end]
                )
            elif deadline_filter == 'future':
                queryset = queryset.filter(deadline__gt=timezone.now())
        
        # Фильтрация по назначенному исполнителю
        assignee_filter = self.request.GET.get('assignee')
        if assignee_filter:
            if assignee_filter == 'me':
                queryset = queryset.filter(assignee=self.request.user)
            elif assignee_filter == 'none':
                queryset = queryset.filter(assignee__isnull=True)
            else:
                # Пытаемся преобразовать в число, если это ID пользователя
                try:
                    user_id = int(assignee_filter)
                    queryset = queryset.filter(assignee__id=user_id)
                except (ValueError, TypeError):
                    # Если не число, игнорируем фильтр
                    pass
        
        # Фильтрация по автору задачи
        reporter_filter = self.request.GET.get('reporter')
        if reporter_filter:
            if reporter_filter == 'me':
                queryset = queryset.filter(reporter=self.request.user)
            else:
                # Пытаемся преобразовать в число, если это ID пользователя
                try:
                    user_id = int(reporter_filter)
                    queryset = queryset.filter(reporter__id=user_id)
                except (ValueError, TypeError):
                    # Если не число, игнорируем фильтр
                    pass
        
        # Сортировка через GET параметр
        sort_by = self.request.GET.get('sort', '-created_at')
        if sort_by in ['created_at', '-created_at', 'deadline', '-deadline', 'title', '-title', 'priority', '-priority']:
            queryset = queryset.order_by(sort_by)
        
        # Права доступа через WorkspaceRoleAccess
        role_access, created = WorkspaceRoleAccess.objects.get_or_create(workspace=self.workspace)
        
        # Если пользователь имеет право просматривать все задачи
        if role_access.has_permission(self.request.user, 'can_view_all_tasks'):
            # Владелец или администратор видит все задачи
            filtered_tasks = []
            for task in queryset.select_related('team', 'assignee', 'reporter', 'updated_by'):
                # Проверяем видимость для каждого пользователя
                if task.is_visible_to_user(self.request.user):
                    filtered_tasks.append(task.id)
            
            # Возвращаем отфильтрованные задачи
            if filtered_tasks:
                return Task.objects.filter(id__in=filtered_tasks).select_related(
                    'team', 'assignee', 'reporter', 'updated_by'
                ).order_by(sort_by)
            else:
                return Task.objects.none()
        else:
            # Фильтрация с учетом видимости команд и задач
            visible_teams = []
            all_teams = Team.objects.filter(workspace=self.workspace)
            for team in all_teams:
                team_access, _ = TeamRoleAccess.objects.get_or_create(team=team)
                if team_access.is_team_visible_to_user(self.request.user):
                    visible_teams.append(team)
            
            # Фильтруем задачи по видимым командам или отсутствию команды
            queryset = queryset.filter(
                Q(team__in=visible_teams) | Q(team__isnull=True)
            )
            
            # Дополнительная фильтрация по видимости задач
            filtered_tasks = []
            for task in queryset.select_related('team', 'assignee', 'reporter', 'updated_by'):
                if task.is_visible_to_user(self.request.user):
                    filtered_tasks.append(task.id)
            
            # Возвращаем отфильтрованные задачи
            if filtered_tasks:
                return Task.objects.filter(id__in=filtered_tasks).select_related(
                    'team', 'assignee', 'reporter', 'updated_by'
                ).order_by(sort_by)
            else:
                return Task.objects.none()

        
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['workspace'] = self.workspace
        
        # Получаем настройки прав доступа
        role_access, created = WorkspaceRoleAccess.objects.get_or_create(workspace=self.workspace)

        # Право создавать задачи в workspace
        can_create_task_in_workspace = role_access.has_permission(self.request.user, 'can_create_tasks')
        context['role_access'] = role_access

        # Право создавать задачи в командах, где он состоит
        user_teams = Team.objects.filter(
            workspace=self.workspace,
            members=self.request.user
        )
        
        can_create_in_any_team = False
        for team in user_teams:
            team_access, _ = TeamRoleAccess.objects.get_or_create(team=team)
            if team_access.has_permission(self.request.user, 'can_create_tasks'):
                can_create_in_any_team = True
                break
        
        if can_create_task_in_workspace or can_create_in_any_team: context['can_create_tasks'] = True
        else: context['can_create_tasks'] = False
                
        # Получаем текущего пользователя для отображения его задач
        context['current_user'] = self.request.user
        context['now'] = timezone.now()
        
        # Получаем все возможные значения для фильтров
        context['priority_choices'] = Task.PRIORITY_CHOICES
        context['status_choices'] = Task.STATUS_CHOICES
        context['deadline_filters'] = [
            ('expired', 'Просроченные'),
            ('today', 'На сегодня'),
            ('week', 'На неделю'),
            ('future', 'Будущие'),
        ]
        
        # Получаем команды с учетом видимости
        if role_access.has_permission(self.request.user, 'can_view_all_teams'):
            context['teams'] = Team.objects.filter(workspace=self.workspace)
        else:
            visible_teams = []
            all_teams = Team.objects.filter(workspace=self.workspace)
            for team in all_teams:
                team_access, _ = TeamRoleAccess.objects.get_or_create(team=team)
                if team_access.is_team_visible_to_user(self.request.user):
                    visible_teams.append(team)
            context['teams'] = visible_teams
        
        # Получаем всех участников workspace для фильтра по исполнителю/автору
        workspace_members = WorkspaceMembership.objects.filter(
            workspace=self.workspace
        ).select_related('user')
        context['workspace_members'] = [member.user for member in workspace_members]
        
        # Добавляем выбранные фильтры для сохранения состояния формы
        context['selected_filters'] = {
            'team': self.request.GET.get('team'),
            'priority': self.request.GET.get('priority'),
            'status': self.request.GET.get('status'),
            'deadline': self.request.GET.get('deadline'),
            'assignee': self.request.GET.get('assignee'),
            'reporter': self.request.GET.get('reporter'),
            'sort': self.request.GET.get('sort', '-created_at'),
        }
        
        # Если выбран фильтр по команде, добавляем команду в контекст
        selected_team_hash = self.request.GET.get('team')
        if selected_team_hash:
            try:
                context['selected_team'] = Team.objects.get(
                    url_hash=selected_team_hash,
                    workspace=self.workspace
                )
            except Team.DoesNotExist:
                context['selected_team'] = None
        
        # Если выбран фильтр по исполнителю, добавляем информацию в контекст
        selected_assignee = self.request.GET.get('assignee')
        if selected_assignee:
            context['selected_assignee_filter'] = selected_assignee
            if selected_assignee == 'me':
                context['selected_assignee_user'] = self.request.user
            elif selected_assignee == 'none':
                context['selected_assignee_user'] = None
            else:
                try:
                    user_id = int(selected_assignee)
                    context['selected_assignee_user'] = User.objects.get(id=user_id)
                except (ValueError, TypeError, User.DoesNotExist):
                    context['selected_assignee_user'] = None
        
        # Если выбран фильтр по автору, добавляем информацию в контекст
        selected_reporter = self.request.GET.get('reporter')
        if selected_reporter:
            context['selected_reporter_filter'] = selected_reporter
            if selected_reporter == 'me':
                context['selected_reporter_user'] = self.request.user
            else:
                try:
                    user_id = int(selected_reporter)
                    context['selected_reporter_user'] = User.objects.get(id=user_id)
                except (ValueError, TypeError, User.DoesNotExist):
                    context['selected_reporter_user'] = None
        
        # Добавляем статистику по задачам
        tasks_queryset = self.get_queryset()
        context['tasks_count'] = tasks_queryset.count()
        context['tasks_expired_count'] = tasks_queryset.filter(
            deadline__lt=timezone.now(),
            status__in=['backlog', 'todo', 'in_progress', 'review']
        ).count()
        
        # Задачи, назначенные на текущего пользователя
        context['my_assigned_tasks_count'] = tasks_queryset.filter(
            assignee=self.request.user
        ).count()
        
        # Задачи, созданные текущим пользователем
        context['my_reported_tasks_count'] = tasks_queryset.filter(
            reporter=self.request.user
        ).count()
        
        # Добавляем форму для быстрого создания задачи (если есть права)
        # if context['can_create_tasks']:
        #     # Проверяем, может ли пользователь создавать задачи в workspace
        #     workspace_access, _ = WorkspaceRoleAccess.objects.get_or_create(workspace=self.workspace)
        #     can_create_in_workspace = workspace_access.has_permission(self.request.user, 'can_create_tasks')
            
        #     # Проверяем, может ли пользователь создавать задачи в командах
        #     user_teams_with_rights = []
        #     user_teams = Team.objects.filter(
        #         workspace=self.workspace,
        #         members=self.request.user
        #     )
        #     for team in user_teams:
        #         team_access, _ = TeamRoleAccess.objects.get_or_create(team=team)
        #         if team_access.has_permission(self.request.user, 'can_create_tasks'):
        #             user_teams_with_rights.append(team)
            
        #     context['quick_task_form'] = TaskCreateForm(
        #         workspace=self.workspace,
        #         user=self.request.user,
        #         can_create_in_workspace=can_create_in_workspace,
        #         user_teams_with_task_create_rights=user_teams_with_rights
        #     )
        
        return context


class TaskCreateView(LoginRequiredMixin, CreateView):
    model = Task
    form_class = TaskCreateForm
    template_name = 'workspace/task_create.html'

    def dispatch(self, request, *args, **kwargs):
        self.workspace = get_object_or_404(
            Workspace, 
            url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем, имеет ли пользователь право создавать задачи где-либо
        workspace_access, created = WorkspaceRoleAccess.objects.get_or_create(workspace=self.workspace)
        
        # Проверяем право на создание задач в workspace
        can_create_in_workspace = workspace_access.has_permission(request.user, 'can_create_tasks')
        
        # Проверяем, есть ли у пользователя право создавать задачи в командах, где он состоит
        user_teams = Team.objects.filter(
            workspace=self.workspace,
            members=request.user
        )
        
        can_create_in_any_team = False
        for team in user_teams:
            team_access, _ = TeamRoleAccess.objects.get_or_create(team=team)
            if team_access.has_permission(request.user, 'can_create_tasks'):
                can_create_in_any_team = True
                break
        
        # Если у пользователя нет прав нигде - показываем 404
        if not can_create_in_workspace and not can_create_in_any_team:
            from django.http import Http404
            raise Http404("У вас нет прав для создания задачи")
            
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['workspace'] = self.workspace
        kwargs['user'] = self.request.user
        
        # Получаем права пользователя
        workspace_access, created = WorkspaceRoleAccess.objects.get_or_create(workspace=self.workspace)
        can_create_in_workspace = workspace_access.has_permission(self.request.user, 'can_create_tasks')
        
        # Получаем команду из GET параметра если есть
        team_from_get = self.request.GET.get('team')
        if team_from_get:
            try:
                kwargs['team_from_get'] = Team.objects.get(
                    url_hash=team_from_get,
                    workspace=self.workspace
                )
            except Team.DoesNotExist:
                kwargs['team_from_get'] = None
        else:
            kwargs['team_from_get'] = None
            
        # Добавляем информацию о правах пользователя
        kwargs['can_create_in_workspace'] = can_create_in_workspace
        kwargs['user_teams_with_task_create_rights'] = self.get_user_teams_with_task_create_rights()
        
        return kwargs

    def get_user_teams_with_task_create_rights(self):
        """Возвращает список команд, где пользователь может создавать задачи"""
        user_teams = Team.objects.filter(
            workspace=self.workspace,
            members=self.request.user
        )
        
        teams_with_rights = []
        for team in user_teams:
            team_access, _ = TeamRoleAccess.objects.get_or_create(team=team)
            if team_access.has_permission(self.request.user, 'can_create_tasks'):
                teams_with_rights.append(team)
        
        return teams_with_rights

    def get_form_class(self):
        """Возвращаем форму с учетом прав пользователя"""
        workspace_access, created = WorkspaceRoleAccess.objects.get_or_create(workspace=self.workspace)
        can_create_in_workspace = workspace_access.has_permission(self.request.user, 'can_create_tasks')
        user_teams_with_rights = self.get_user_teams_with_task_create_rights()
        
        # Создаем динамическую форму на основе прав пользователя
        class TaskCreateFormWithPermissions(TaskCreateForm):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                
                # Получаем информацию о правах из kwargs
                can_create_in_workspace = kwargs.get('can_create_in_workspace', False)
                user_teams_with_task_create_rights = kwargs.get('user_teams_with_task_create_rights', [])
                
                # Логика фильтрации команд
                if not can_create_in_workspace and not user_teams_with_task_create_rights:
                    # У пользователя нет прав нигде - это не должно произойти благодаря dispatch
                    self.fields['team'].queryset = Team.objects.none()
                elif not can_create_in_workspace and user_teams_with_task_create_rights:
                    # Может создавать только в командах с правами
                    self.fields['team'].queryset = Team.objects.filter(
                        id__in=[team.id for team in user_teams_with_task_create_rights]
                    )
                elif can_create_in_workspace and not user_teams_with_task_create_rights:
                    # Может создавать только без команды
                    self.fields['team'].queryset = Team.objects.none()
                    self.fields['team'].empty_label = "Без команды"
                else:
                    # Может создавать и в workspace, и в командах с правами
                    all_available_teams = list(user_teams_with_task_create_rights)
                    self.fields['team'].queryset = Team.objects.filter(
                        id__in=[team.id for team in all_available_teams]
                    )
                    self.fields['team'].empty_label = "Без команды"
        
        return TaskCreateFormWithPermissions

    def form_valid(self, form):
        # Устанавливаем workspace и reporter перед сохранением
        form.instance.workspace = self.workspace
        form.instance.reporter = self.request.user
        form.instance.updated_by = self.request.user  # Добавляем updated_by
        
        response = super().form_valid(form)
        messages.success(self.request, 'Задача успешно создана!')
        return response

    def get_success_url(self):
        return reverse_lazy('workspace:task_list', kwargs={
            'workspace_url_hash': self.workspace.url_hash
        })

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['workspace'] = self.workspace
        
        # Получаем настройки прав доступа
        role_access, created = WorkspaceRoleAccess.objects.get_or_create(workspace=self.workspace)
        context['role_access'] = role_access
        
        # Добавляем информацию о правах пользователя
        context['can_create_in_workspace'] = role_access.has_permission(self.request.user, 'can_create_tasks')
        context['user_teams_with_task_create_rights'] = self.get_user_teams_with_task_create_rights()
        
        # Добавляем team_from_get в контекст для шаблона
        team_from_get = self.request.GET.get('team')
        if team_from_get:
            try:
                context['team'] = Team.objects.get(
                    url_hash=team_from_get,
                    workspace=self.workspace
                )
                # Проверяем, имеет ли пользователь право создавать задачи в этой команде
                team_access, _ = TeamRoleAccess.objects.get_or_create(team=context['team'])
                context['can_create_in_selected_team'] = team_access.has_permission(
                    self.request.user, 'can_create_tasks'
                )
            except Team.DoesNotExist:
                context['team'] = None
                context['can_create_in_selected_team'] = False
        else:
            context['team'] = None
            context['can_create_in_selected_team'] = False
            
        return context


class TaskDetailView(LoginRequiredMixin, DetailView):
    """Детальная страница задачи"""
    model = Task
    template_name = 'workspace/task_detail.html'
    slug_field = 'url_hash'
    slug_url_kwarg = 'task_url_hash'

    def dispatch(self, request, *args, **kwargs):
        self.workspace = get_object_or_404(
            Workspace, 
            url_hash=kwargs['workspace_url_hash']
        )
        if not self.workspace.has_access(request.user):
            from django.http import Http404
            raise Http404("У вас нет доступа к этой рабочей области")
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        """Получаем объект задачи с проверкой видимости"""
        task = super().get_object(queryset)
        
        # Проверяем, видна ли задача пользователю
        if not task.is_visible_to_user(self.request.user):
            from django.http import Http404
            raise Http404("У вас нет доступа к этой задаче")
        
        return task

    def get_queryset(self):
        return Task.objects.filter(workspace=self.workspace)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        task = self.get_object()
        context['workspace'] = self.workspace
        context['now'] = timezone.now()
        
        # Получаем настройки прав доступа workspace
        workspace_access, created = WorkspaceRoleAccess.objects.get_or_create(workspace=self.workspace)
        context['workspace_access'] = workspace_access
        
        # Определяем, является ли пользователь редактором задачи
        context['is_editor'] = task.can_user_edit(self.request.user)
        context['is_special_editor'] = task.is_special_editor(self.request.user)
        
        # Проверяем права редактирования для конкретных полей
        if task.team:
            # Задача привязана к команде
            team_access, _ = TeamRoleAccess.objects.get_or_create(team=task.team)
            context['team_access'] = team_access
            
            # Получаем информацию о лидере команды
            try:
                team_leader = TeamMembership.objects.get(team=task.team, role='leader')
                context['team_leader'] = team_leader.user
                context['is_team_leader'] = (team_leader.user == self.request.user)
            except TeamMembership.DoesNotExist:
                context['team_leader'] = None
                context['is_team_leader'] = False
            
            # Определяем, является ли пользователь обычным редактором команды
            try:
                team_membership = TeamMembership.objects.get(team=task.team, user=self.request.user)
                context['is_team_editor'] = team_access.has_permission(self.request.user, 'can_edit_tasks')
            except TeamMembership.DoesNotExist:
                context['is_team_editor'] = False
        else:
            context['team_access'] = None
            context['team_leader'] = None
            context['is_team_leader'] = False
            context['is_team_editor'] = False
        
        # Получаем информацию о владельце workspace
        try:
            workspace_owner_membership = WorkspaceMembership.objects.get(
                workspace=self.workspace,
                role='owner'
            )
            context['workspace_owner'] = workspace_owner_membership.user
            context['is_workspace_owner'] = (workspace_owner_membership.user == self.request.user)
        except WorkspaceMembership.DoesNotExist:
            context['workspace_owner'] = None
            context['is_workspace_owner'] = False
        
        # Для workspace задач определяем, является ли пользователь редактором workspace
        if not task.team:
            try:
                workspace_membership = WorkspaceMembership.objects.get(
                    workspace=self.workspace,
                    user=self.request.user
                )
                context['is_workspace_editor'] = workspace_access.has_permission(self.request.user, 'can_edit_tasks')
            except WorkspaceMembership.DoesNotExist:
                context['is_workspace_editor'] = False
        else:
            context['is_workspace_editor'] = False
        
        # Права на редактирование конкретных аспектов задачи
        context['can_edit_content'] = task.can_user_edit_content(self.request.user)
        context['can_edit_team'] = task.can_user_edit_team(self.request.user)
        context['can_edit_assignee'] = task.can_user_edit_assignee(self.request.user)
        context['can_edit_visibility'] = task.can_user_edit_visibility(self.request.user)
        
        # Права на изменение прав доступа к задаче
        context['can_change_permissions'] = task.can_user_change_permissions(self.request.user)
        
        # Права на удаление задачи
        if task.team:
            team_access, _ = TeamRoleAccess.objects.get_or_create(team=task.team)
            context['can_delete_task'] = team_access.has_permission(self.request.user, 'can_delete_tasks')
        else:
            context['can_delete_task'] = workspace_access.has_permission(self.request.user, 'can_delete_tasks')
        
        # Общие права для шаблона
        context['can_create_tasks'] = workspace_access.has_permission(self.request.user, 'can_create_tasks')
        
        # Получаем список всех редакторов задачи
        context['editors'] = task.get_editors()
        
        # Получаем доступных исполнителей для формы изменения
        context['available_assignees'] = task.get_available_assignees()
        
        # Получаем доступные команды для формы изменения
        available_teams = []
        if task.team:
            # Если есть текущая команда, включаем ее в список
            available_teams.append(task.team)
        
        # Добавляем команды, где пользователь может создавать задачи
        user_teams = Team.objects.filter(
            workspace=self.workspace,
            members=self.request.user
        )
        for team in user_teams:
            team_access, _ = TeamRoleAccess.objects.get_or_create(team=team)
            if team_access.has_permission(self.request.user, 'can_create_tasks'):
                if team not in available_teams:
                    available_teams.append(team)
        
        context['available_teams'] = available_teams
        
        # Добавляем информацию для навигации
        context['task_list_url'] = reverse('workspace:task_list', kwargs={
            'workspace_url_hash': self.workspace.url_hash
        })
        
        if task.team:
            context['team_detail_url'] = reverse('workspace:team_detail', kwargs={
                'workspace_url_hash': self.workspace.url_hash,
                'team_url_hash': task.team.url_hash
            })
        
        # Добавляем информацию о просроченности задачи
        if task.deadline and task.deadline < timezone.now() and task.status != 'done':
            context['is_overdue'] = True
            context['overdue_days'] = (timezone.now() - task.deadline).days
        else:
            context['is_overdue'] = False
        
        # Добавляем информацию о правах для отображения в интерфейсе
        context['user_is_reporter'] = (self.request.user == task.reporter)
        context['user_is_assignee'] = (task.assignee and self.request.user == task.assignee)
        
        # Добавляем текущие права задачи для отображения
        context['task_permissions'] = {
            'can_edit_content': task.can_edit_content,
            'can_edit_team': task.can_edit_team,
            'can_edit_assignee': task.can_edit_assignee,
            'can_edit_visibility': task.can_edit_visibility,
        }
        
        return context

    def post(self, request, *args, **kwargs):
        """Обработка AJAX POST-запросов"""
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        task = self.get_object()
        action = request.POST.get('action')
        
        if action == 'update_task':
            return self.handle_task_update(request, task)
        elif action == 'update_permissions':
            return self.handle_permissions_update(request, task)
        elif action == 'delete_task':
            return self.handle_task_delete(request, task)
        else:
            return JsonResponse({
                'success': False, 
                'error': 'Unknown action'
            })
    
    def handle_task_update(self, request, task):
        """Обработка обновления параметров задачи"""
        try:
            # Проверяем, является ли пользователь редактором
            if not task.can_user_edit(request.user):
                return JsonResponse({
                    'success': False, 
                    'error': 'У вас нет прав для редактирования этой задачи'
                })
            
            # Собираем данные для обновления
            update_data = {}
            validation_errors = []
            has_changes = False
            
            # Обрабатываем только те поля, которые пришли в запросе
            # и которые пользователь имеет право редактировать
            
            # Содержание (название, описание, статус, приоритет)
            content_fields = ['title', 'description', 'status', 'priority']
            for field in content_fields:
                if field in request.POST:
                    if not task.can_user_edit_content(request.user):
                        # Пропускаем поле, если нет прав
                        continue
                    
                    new_value = request.POST[field]
                    current_value = getattr(task, field)
                    
                    # Для строковых полей сравниваем значения
                    if isinstance(current_value, str):
                        if new_value != current_value:
                            update_data[field] = new_value
                            has_changes = True
                    # Для других типов проверяем на равенство
                    elif str(new_value) != str(current_value):
                        update_data[field] = new_value
                        has_changes = True
            
            # Особенная обработка дедлайна с UTC (упрощенная версия)
            if 'deadline' in request.POST:
                if not task.can_user_edit_content(request.user):
                    # Пропускаем, если нет прав
                    pass
                else:
                    deadline_str = request.POST['deadline'].strip()
                    current_deadline = task.deadline
                    
                    # Проверяем, изменился ли дедлайн
                    if deadline_str:
                        try:
                            # Парсим дату из строки
                            from django.utils.dateparse import parse_datetime
                            new_deadline_naive = parse_datetime(deadline_str)
                            
                            if new_deadline_naive:
                                # Используем timezone для преобразования
                                if new_deadline_naive.tzinfo is None:
                                    # Преобразуем наивное время в aware с текущей таймзоной
                                    new_deadline_aware = timezone.make_aware(
                                        new_deadline_naive, 
                                        timezone.get_current_timezone()
                                    )
                                    # Сохраняем в базе (Django автоматически сохраняет в UTC)
                                    update_data['deadline'] = new_deadline_aware
                                    if new_deadline_aware != current_deadline: has_changes = True

                                else:
                                    # Уже aware время
                                    update_data['deadline'] = new_deadline_naive
                                    if new_deadline_naive != current_deadline: has_changes = True

                            else:
                                validation_errors.append('Некорректный формат даты для дедлайна')
                        except Exception as e:
                            validation_errors.append(f'Некорректный формат даты для дедлайна: {str(e)}')
                    else:
                        # Пустая строка означает удаление дедлайна
                        if current_deadline is not None:
                            update_data['deadline'] = None
                            has_changes = True
            
            # Команда
            if 'team' in request.POST:
                if not task.can_user_edit_team(request.user):
                    # Пропускаем, если нет прав
                    pass
                else:
                    team_id = request.POST['team'].strip()
                    current_team_id = str(task.team.id) if task.team else ''
                    
                    if team_id != current_team_id:
                        if team_id:
                            try:
                                new_team = Team.objects.get(
                                    id=int(team_id),
                                    workspace=self.workspace
                                )
                                update_data['team'] = new_team
                                has_changes = True
                            except (ValueError, Team.DoesNotExist):
                                validation_errors.append('Выбранная команда не найдена')
                        else:
                            # Проверяем, может ли пользователь убрать команду
                            if task.team is not None:
                                workspace_access, _ = WorkspaceRoleAccess.objects.get_or_create(
                                    workspace=self.workspace
                                )
                                can_create_task_in_workspace = workspace_access.has_permission(
                                    self.request.user, 
                                    'can_create_tasks'
                                )
                                
                                if can_create_task_in_workspace:
                                    update_data['team'] = None
                                    has_changes = True
                                else:
                                    validation_errors.append(
                                        'У вас нет прав на создание задач в рабочей области. '
                                        'Вы не можете убрать команду из задачи.'
                                    )
            
            # Исполнитель
            if 'assignee' in request.POST:
                if not task.can_user_edit_assignee(request.user):
                    # Пропускаем, если нет прав
                    pass
                else:
                    assignee_id = request.POST['assignee'].strip()
                    current_assignee_id = str(task.assignee.id) if task.assignee else ''
                    
                    if assignee_id != current_assignee_id:
                        if assignee_id:
                            try:
                                new_assignee = User.objects.get(id=int(assignee_id))
                                update_data['assignee'] = new_assignee
                                has_changes = True
                            except (ValueError, User.DoesNotExist):
                                validation_errors.append('Выбранный исполнитель не найден')
                        else:
                            update_data['assignee'] = None
                            has_changes = True
            
            # Видимость
            if 'visible' in request.POST:
                if not task.can_user_edit_visibility(request.user):
                    # Пропускаем, если нет прав
                    pass
                else:
                    new_visible = (request.POST['visible'] == 'on')
                    if new_visible != task.visible:
                        update_data['visible'] = new_visible
                        has_changes = True
            
            # Если есть ошибки валидации, возвращаем их
            if validation_errors:
                return JsonResponse({
                    'success': False,
                    'errors': validation_errors
                })
            
            # Проверяем, есть ли изменения для сохранения
            if not has_changes:
                return JsonResponse({
                    'success': True,
                    'message': 'Нет изменений для сохранения'
                })
            
            # Обновляем задачу
            try:
                # Используем упрощенную логику обновления
                for field, value in update_data.items():
                    setattr(task, field, value)
                
                # Устанавливаем, кто обновил задачу
                task.updated_by = request.user
                
                # Выполняем полную валидацию перед сохранением
                task.full_clean()
                task.save()

                # Добавляем информацию о просроченности задачи
                if task.deadline and task.deadline < timezone.now() and task.status != 'done':
                    overdue_days = str((timezone.now() - task.deadline).days)
                else: overdue_days = None

                # Возвращаем обновленные данные задачи
                return JsonResponse({
                    'success': True,
                    'message': 'Задача успешно обновлена',
                    'task_data': {
                        'title': task.title,
                        'description': task.description,
                        'status': task.status,
                        'status_display': task.get_status_display(),
                        'priority': task.priority,
                        'priority_display': task.get_priority_display(),
                        'deadline': task.deadline.isoformat() if task.deadline else None,
                        'deadline_display': task.deadline.strftime('%d.%m.%Y %H:%M') if task.deadline else 'Не установлен',
                        'assignee': {
                            'id': task.assignee.id if task.assignee else None,
                            'username': task.assignee.username if task.assignee else None
                        } if task.assignee else None,
                        'team': {
                            'id': task.team.id if task.team else None,
                            'name': task.team.name if task.team else None,
                            'url_hash': task.team.url_hash if task.team else None
                        } if task.team else None,
                        'visible': task.visible,
                        'updated_at': task.updated_at.isoformat(),
                        'updated_by': task.updated_by.username if task.updated_by else None,
                        'is_overdue': task.deadline and task.deadline < timezone.now() and task.status != 'done',
                        'overdue_days': overdue_days
                    }
                })
                
            except ValidationError as e:
                # Обрабатываем ошибки валидации модели
                error_messages = []
                if hasattr(e, 'error_dict'):
                    for field, errors in e.error_dict.items():
                        for error in errors:
                            error_messages.append(f'{field}: {error.message}')
                else:
                    error_messages.append(str(e))
                
                return JsonResponse({
                    'success': False,
                    'errors': error_messages
                })
                
            except Exception as e:
                return JsonResponse({
                    'success': False,
                    'error': f'Ошибка при обновлении задачи: {str(e)}'
                })
                
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Ошибка при обновлении задачи: {str(e)}'
            })
    
    def handle_permissions_update(self, request, task):
        """Обработка обновления прав доступа к задаче"""
        try:
            if not task.can_user_change_permissions(request.user):
                return JsonResponse({
                    'success': False,
                    'error': 'У вас нет прав для изменения прав доступа к этой задаче'
                })
            
            # Собираем данные для обновления прав
            permissions_data = {}
            permission_fields = ['can_edit_content', 'can_edit_team', 
                               'can_edit_assignee', 'can_edit_visibility']
            
            for field in permission_fields:
                if field in request.POST:
                    # Значение будет 'on' если чекбокс отмечен, 'off' если нет
                    permissions_data[field] = (request.POST[field] == 'on')
            
            if permissions_data:
                # Обновляем права
                for field, value in permissions_data.items():
                    setattr(task, field, value)
                
                # Сохраняем изменения
                task.updated_by = request.user
                task.save()
                
                return JsonResponse({
                    'success': True,
                    'message': 'Права доступа к задаче успешно обновлены',
                    'permissions': {
                        'can_edit_content': task.can_edit_content,
                        'can_edit_team': task.can_edit_team,
                        'can_edit_assignee': task.can_edit_assignee,
                        'can_edit_visibility': task.can_edit_visibility
                    }
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Не получены данные для обновления прав'
                })
                
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Ошибка при обновлении прав доступа: {str(e)}'
            })
    
    def handle_task_delete(self, request, task):
        """Обработка удаления задачи"""
        try:
            # Проверяем права на удаление
            if task.team:
                team_access, _ = TeamRoleAccess.objects.get_or_create(team=task.team)
                can_delete = team_access.has_permission(request.user, 'can_delete_tasks')
            else:
                workspace_access, _ = WorkspaceRoleAccess.objects.get_or_create(workspace=self.workspace)
                can_delete = workspace_access.has_permission(request.user, 'can_delete_tasks')
            
            if not can_delete:
                return JsonResponse({   
                    'success': False,
                    'error': 'У вас нет прав для удаления этой задачи'
                })
            
            # Сохраняем информацию для перенаправления
            task_title = task.title
            task_team = task.team
            
            # Удаляем задачу
            task.delete()
            
            # Определяем URL для перенаправления
            if task_team:
                redirect_url = reverse('workspace:team_detail', kwargs={
                    'workspace_url_hash': self.workspace.url_hash,
                    'team_url_hash': task_team.url_hash
                })
            else:
                redirect_url = reverse('workspace:task_list', kwargs={
                    'workspace_url_hash': self.workspace.url_hash
                })
            
            return JsonResponse({
                'success': True,
                'message': f'Задача "{task_title}" успешно удалена',
                'redirect_url': redirect_url
            })
                
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Ошибка при удалении задачи: {str(e)}'
            })


class CreateMassInvitationView(LoginRequiredMixin, View):
    """Обновление массового приглашения"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        workspace = get_object_or_404(
            Workspace, 
            url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем право на управление доступом через WorkspaceRoleAccess
        role_access, created = WorkspaceRoleAccess.objects.get_or_create(workspace=workspace)
        if not role_access.has_permission(request.user, 'can_manage_access'):
            return JsonResponse({'success': False, 'error': 'No permission'})
        
        form = MassInvitationForm(request.POST)
        
        if form.is_valid():
            # Генерируем новый токен
            workspace.regenerate_mass_invitation_token()
            
            # Обновляем остальные поля
            expiration_time = form.cleaned_data['expiration_time']
            max_uses = form.cleaned_data['max_uses']
            
            workspace.mass_invitation_expiration = expiration_time if expiration_time else None
            workspace.mass_invitation_max_uses = max_uses if max_uses else None
            workspace.mass_invitation_current_uses = 0  # Сбрасываем счетчик использований
            workspace.mass_invitation_is_active = True
            workspace.mass_invitation_created_at = timezone.now()
            workspace.save()
            
            # Генерируем полную ссылку для приглашения
            invitation_url = workspace.get_mass_invitation_url(request)
            
            return JsonResponse({
                'success': True,
                'invitation_url': invitation_url,
                'token': workspace.mass_invitation_token,
                'expiration_time': workspace.get_mass_invitation_expiration_display(),
                'max_uses': workspace.mass_invitation_max_uses or 'Без ограничений',
                'current_uses': workspace.mass_invitation_current_uses,
            })
        else:
            return JsonResponse({'success': False, 'errors': form.errors})


class CreateIndividualInvitationsView(LoginRequiredMixin, View):
    """Создание точечных приглашений"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        workspace = get_object_or_404(
            Workspace, 
            url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем право на приглашение пользователей через WorkspaceRoleAccess
        role_access, created = WorkspaceRoleAccess.objects.get_or_create(workspace=workspace)
        if not role_access.has_permission(request.user, 'can_invite_users'):
            return JsonResponse({'success': False, 'error': 'No permission'})
        
        identifiers = request.POST.get('identifiers', '').strip()
        if not identifiers:
            return JsonResponse({'success': False, 'error': 'No identifiers provided'})
        
        # Разделяем идентификаторы по пробелам
        identifier_list = [id.strip() for id in identifiers.split() if id.strip()]
        
        created_invitations = []
        errors = []
        
        for identifier in identifier_list:
            # Определяем тип идентификатора (email или код) и находим пользователя
            invited_user = None
            
            if '@' in identifier:
                # Это email - ищем пользователя по email
                try:
                    invited_user = User.objects.get(email=identifier)
                except User.DoesNotExist:
                    errors.append(f"Пользователь с email {identifier} не найден")
                    continue
            else:
                # Это уникальный код - ищем пользователя по коду профиля
                try:
                    profile = UserProfile.objects.get(unique_code=identifier)
                    invited_user = profile.user
                except UserProfile.DoesNotExist:
                    errors.append(f"Пользователь с кодом {identifier} не найден")
                    continue
            
            # Проверяем, не является ли пользователь уже участником workspace
            if WorkspaceMembership.objects.filter(workspace=workspace, user=invited_user).exists():
                errors.append(f"Пользователь {invited_user.email} уже является участником рабочей области")
                continue
            
            # Проверяем, не приглашен ли уже этот пользователь
            existing_invitation = IndividualInvitation.objects.filter(
                workspace=workspace,
                invited_user=invited_user,
                status='pending'
            ).exists()
            
            if existing_invitation:
                errors.append(f"Пользователь {invited_user.email} уже приглашен")
                continue
            
            # Создаем приглашение
            invitation = IndividualInvitation(
                workspace=workspace,
                created_by=request.user,
                invited_user=invited_user
            )
            
            invitation.save()
            created_invitations.append(invitation)
            
            # Отправляем уведомление по email
            self.send_invitation_notification(invitation, request)
            
            # Создаем уведомление в системе для приглашенного пользователя
            self.create_system_notification(invitation, request)
        
        # Создаем уведомление для создателя приглашений
        if created_invitations:
            self.create_creator_notification(request.user, created_invitations, workspace)
        
        return JsonResponse({
            'success': True,
            'created_count': len(created_invitations),
            'errors': errors
        })
    
    def send_invitation_notification(self, invitation, request):
        """Отправляет email уведомление о приглашении"""
        invitation_url = request.build_absolute_uri(
            reverse('workspace:accept_invitation', kwargs={'token': invitation.invitation_token})
        )
        
        subject = f'Приглашение в рабочую область {invitation.workspace.name}'
        message = f'''
        Вас пригласили присоединиться к рабочей области "{invitation.workspace.name}".
        
        Для принятия приглашения перейдите по ссылке:
        {invitation_url}
        '''
        
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [invitation.invited_user.email],
            fail_silently=True,
        )
    
    def create_system_notification(self, invitation, request):
        """Создает системное уведомление для приглашенного пользователя"""
        invitation_url = request.build_absolute_uri(
            reverse('workspace:accept_invitation', kwargs={'token': invitation.invitation_token})
        )
        
        message = f'Вас пригласили присоединиться к рабочей области "{invitation.workspace.name}"'
        
        Notification.objects.create(
            user=invitation.invited_user,
            message=message,
            level='info',
            related_url=invitation_url
        )
    
    def create_creator_notification(self, creator, created_invitations, workspace):
        """Создает уведомление для пользователя, который отправил приглашения"""
        if len(created_invitations) == 1:
            invited_user = created_invitations[0].invited_user
            message = f'Вы отправили приглашение пользователю {invited_user.username} в рабочую область "{workspace.name}"'
        else:
            message = f'Вы отправили {len(created_invitations)} приглашений в рабочую область "{workspace.name}"'
        
        Notification.objects.create(
            user=creator,
            message=message,
            level='info'
        )


class ToggleAllInvitationsView(LoginRequiredMixin, View):
    """Включение/выключение массового приглашения"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        workspace = get_object_or_404(
            Workspace, 
            url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем право на управление доступом через WorkspaceRoleAccess
        role_access, created = WorkspaceRoleAccess.objects.get_or_create(workspace=workspace)
        if not role_access.has_permission(request.user, 'can_manage_access'):
            return JsonResponse({'success': False, 'error': 'No permission'})
        
        action = request.POST.get('action')
        
        if action == 'disable':
            workspace.mass_invitation_is_active = False
        elif action == 'enable':
            workspace.mass_invitation_is_active = True
        
        workspace.save()
        
        return JsonResponse({'success': True})


class AcceptInvitationView(LoginRequiredMixin, View):
    """Принятие приглашения"""
    
    def get(self, request, *args, **kwargs):
        token = kwargs.get('token')
        print(f"DEBUG: Received token: {token}")  # Для отладки
        
        # Сначала ищем индивидуальное приглашение
        individual_invitation = self.get_individual_invitation(token)
        if individual_invitation:
            return self.handle_individual_invitation(request, individual_invitation)
        
        # Затем ищем массовое приглашение
        mass_invitation = self.get_mass_invitation(token)
        if mass_invitation:
            return self.handle_mass_invitation(request, mass_invitation)
        
        messages.error(request, 'Приглашение недействительно или истекло')
        return redirect('workspace:workspace_index')
    
    def get_individual_invitation(self, token):
        """Находит индивидуальное приглашение по токену"""
        try:
            return IndividualInvitation.objects.get(
                invitation_token=token,
                status='pending'
            )
        except IndividualInvitation.DoesNotExist:
            return None
    
    def get_mass_invitation(self, token):
        """Находит workspace по массовому токену"""
        try:
            workspace = Workspace.objects.get(mass_invitation_token=token)
            return workspace if workspace.can_mass_invitation_be_used() else None
        except Workspace.DoesNotExist:
            return None
    
    def handle_individual_invitation(self, request, invitation):
        """Обрабатывает индивидуальное приглашение"""
        print(f"DEBUG: Handling individual invitation for {invitation.invited_user.email}")  # Для отладки
        
        # Проверяем, соответствует ли пользователь приглашению
        if not self.user_matches_invitation(request.user, invitation):
            messages.error(request, 'Это приглашение предназначено для другого пользователя')
            return redirect('workspace:workspace_index')
        
        # Добавляем пользователя в workspace через WorkspaceMembership
        WorkspaceMembership.objects.create(
            workspace=invitation.workspace,
            user=request.user,
            role='member'  # По умолчанию добавляем как участника
        )
        
        invitation.status = 'accepted'
        invitation.accepted_at = timezone.now()
        invitation.save()
        
        # Создаем уведомление о принятии приглашения
        self.create_acceptance_notifications(invitation, request)
        
        messages.success(request, f'Вы успешно присоединились к рабочей области {invitation.workspace.name}')
        return redirect('workspace:workspace_detail', workspace_url_hash=invitation.workspace.url_hash)
    
    def handle_mass_invitation(self, request, workspace):
        """Обрабатывает массовое приглашение"""
        print(f"DEBUG: Handling mass invitation for {workspace.name}")  # Для отладки
        
        # Проверяем, не является ли пользователь уже участником
        if WorkspaceMembership.objects.filter(workspace=workspace, user=request.user).exists():
            messages.info(request, f'Вы уже являетесь участником рабочей области {workspace.name}')
            return redirect('workspace:workspace_detail', workspace_url_hash=workspace.url_hash)
        
        # Добавляем пользователя в workspace через WorkspaceMembership
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=request.user,
            role='member'  # По умолчанию добавляем как участника
        )
        
        workspace.mass_invitation_current_uses += 1
        workspace.save()
        
        # Создаем уведомление о присоединении через массовое приглашение
        self.create_mass_invitation_notification(request.user, workspace)
        
        messages.success(request, f'Вы успешно присоединились к рабочей области {workspace.name}')
        return redirect('workspace:workspace_detail', workspace_url_hash=workspace.url_hash)
    
    def user_matches_invitation(self, user, invitation):
        """Проверяет, соответствует ли пользователь приглашению"""
        # Простая проверка - пользователь должен совпадать с приглашенным
        return user == invitation.invited_user
    
    def create_acceptance_notifications(self, invitation, request):
        """Создает уведомления о принятии приглашения"""
        workspace_url = request.build_absolute_uri(
            reverse('workspace:workspace_detail', kwargs={'workspace_url_hash': invitation.workspace.url_hash})
        )
        
        # Уведомление для принявшего приглашение пользователя
        Notification.objects.create(
            user=invitation.invited_user,
            message=f'Вы приняли приглашение в рабочую область "{invitation.workspace.name}"',
            level='info',
            related_url=workspace_url
        )
        
        # Уведомление для создателя приглашения
        Notification.objects.create(
            user=invitation.created_by,
            message=f'Пользователь {invitation.invited_user.email} принял ваше приглашение в рабочую область "{invitation.workspace.name}"',
            level='info',
            related_url=workspace_url
        )
    
    def create_mass_invitation_notification(self, user, workspace):
        """Создает уведомление о присоединении через массовое приглашение"""
        Notification.objects.create(
            user=user,
            message=f'Вы присоединились к рабочей области "{workspace.name}" через массовое приглашение',
            level='info'
        )

class TeamInviteMemberView(LoginRequiredMixin, View):
    """Приглашение пользователей в команду"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        team = get_object_or_404(
            Team, 
            url_hash=kwargs['team_url_hash'],
            workspace__url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем право на приглашение пользователей через TeamRoleAccess
        team_access, created = TeamRoleAccess.objects.get_or_create(team=team)
        if not team_access.has_permission(request.user, 'can_invite_users'):
            return JsonResponse({'success': False, 'error': 'No permission'})
        
        user_ids = request.POST.getlist('user_ids[]')
        if not user_ids:
            return JsonResponse({'success': False, 'error': 'No users selected'})
        
        added_users = []
        errors = []
        
        for user_id in user_ids:
            try:
                user_to_add = User.objects.get(id=user_id)
                
                # Проверяем, что пользователь является участником workspace
                if not WorkspaceMembership.objects.filter(
                    workspace=team.workspace, 
                    user=user_to_add
                ).exists():
                    errors.append(f"Пользователь {user_to_add.username} не является участником рабочей области")
                    continue
                
                # Проверяем, не является ли пользователь уже участником команды
                if TeamMembership.objects.filter(team=team, user=user_to_add).exists():
                    errors.append(f"Пользователь {user_to_add.username} уже в команде")
                    continue
                
                # Добавляем пользователя в команду с ролью участника
                TeamMembership.objects.create(
                    team=team,
                    user=user_to_add,
                    role='member'
                )
                
                added_users.append({
                    'id': user_to_add.id,
                    'username': user_to_add.username,
                    'email': user_to_add.email
                })
                
                # Создаем уведомление для добавленного пользователя
                self.create_team_join_notification(user_to_add, team, request)
                
            except User.DoesNotExist:
                errors.append(f"Пользователь с ID {user_id} не найден")
                continue
        
        # Создаем уведомление для приглашающего
        if added_users:
            self.create_inviter_notification(request.user, added_users, team)
        
        return JsonResponse({
            'success': True,
            'added_count': len(added_users),
            'added_users': added_users,
            'members_count': team.members.count(),
            'errors': errors
        })
    
    def create_team_join_notification(self, user, team, request):
        """Создает уведомление о добавлении в команду"""
        team_url = request.build_absolute_uri(
            reverse('workspace:team_detail', kwargs={
                'workspace_url_hash': team.workspace.url_hash,
                'team_url_hash': team.url_hash
            })
        )
        
        message = f'Вас добавили в команду "{team.name}" рабочей области "{team.workspace.name}"'
        
        Notification.objects.create(
            user=user,
            message=message,
            level='info',
            related_url=team_url
        )
    
    def create_inviter_notification(self, inviter, added_users, team):
        """Создает уведомление для пользователя, который добавил участников"""
        if len(added_users) == 1:
            added_user = added_users[0]
            message = f'Вы добавили пользователя {added_user["username"]} в команду "{team.name}"'
        else:
            message = f'Вы добавили {len(added_users)} пользователей в команду "{team.name}"'
        
        Notification.objects.create(
            user=inviter,
            message=message,
            level='info'
        )


class TeamJoinView(LoginRequiredMixin, View):
    """Представление для присоединения к команде"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        workspace_url_hash = kwargs.get('workspace_url_hash')
        team_url_hash = kwargs.get('team_url_hash')
        
        try:
            # Получаем команду
            team = get_object_or_404(
                Team,
                url_hash=team_url_hash,
                workspace__url_hash=workspace_url_hash
            )
            
            # Проверяем, может ли пользователь присоединиться
            team_access, _ = TeamRoleAccess.objects.get_or_create(team=team)
            
            if not team_access.is_team_visible_to_user(request.user):
                return JsonResponse({
                    'success': False, 
                    'error': 'У вас нет доступа к этой команде'
                })
            
            # Проверяем, не является ли пользователь уже участником
            if TeamMembership.objects.filter(team=team, user=request.user).exists():
                return JsonResponse({
                    'success': False,
                    'error': 'Вы уже являетесь участником этой команды'
                })
            
            # Присоединяем пользователя к команде с ролью "member"
            TeamMembership.objects.create(
                team=team,
                user=request.user,
                role='member'
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Вы успешно присоединились к команде',
                'is_member': True,
                'members_count': team.members.count()
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })

class TeamLeaveView(LoginRequiredMixin, View):
    """Представление для выхода из команды"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        workspace_url_hash = kwargs.get('workspace_url_hash')
        team_url_hash = kwargs.get('team_url_hash')
        
        try:
            # Получаем команду
            team = get_object_or_404(
                Team,
                url_hash=team_url_hash,
                workspace__url_hash=workspace_url_hash
            )
            
            # Проверяем, является ли пользователь участником
            membership = TeamMembership.objects.filter(
                team=team,
                user=request.user
            ).first()
            
            if not membership:
                return JsonResponse({
                    'success': False,
                    'error': 'Вы не являетесь участником этой команды'
                })
            
            # Проверяем, является ли пользователь лидером
            if membership.role == 'leader':
                return JsonResponse({
                    'success': False,
                    'error': 'Нельзя покинуть команду, потому что вы являетесь её лидером, сначала назначьте другого лидера'
                })
            
            # Выполняем все операции в транзакции
            with transaction.atomic():
                # 1. Получаем задачи, где пользователь назначен исполнителем и задача назначена на эту команду
                tasks_to_update = Task.objects.filter(
                    team=team,
                    assignee=request.user
                )

                # 2. Убираем пользователя из исполнителей задач этой команды
                tasks_to_update.update(
                    assignee=None,
                    updated_at=timezone.now(),
                    updated_by=request.user
                )
                
                # 3. Удаляем пользователя из команды
                membership.delete()
                
                # 4. Проверяем, остался ли пользователь в команде (для кнопки)
                is_still_member = TeamMembership.objects.filter(
                    team=team,
                    user=request.user
                ).exists()
            
            return JsonResponse({
                'success': True,
                'message': 'Вы успешно покинули команду',
                'is_member': is_still_member,
                'members_count': team.members.count()
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })


class WorkspaceTransferOwnerRoleView(LoginRequiredMixin, View):
    """Представление для передачи роли владельца рабочей области с проверкой пароля"""
    
    def post(self, request, *args, **kwargs):
        # Проверяем, что это AJAX запрос
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False, 
                'error': 'Неверный тип запроса. Требуется AJAX.'
            })
        
        workspace_url_hash = kwargs.get('workspace_url_hash')
        
        try:
            # Получаем рабочую область
            workspace = get_object_or_404(
                Workspace,
                url_hash=workspace_url_hash
            )
            
            # Получаем данные из запроса
            new_owner_id = request.POST.get('new_owner_id')
            password = request.POST.get('password')
            
            # Валидация данных
            if not new_owner_id:
                return JsonResponse({
                    'success': False,
                    'error': 'Не выбран новый владелец рабочей области'
                })
            
            if not password:
                return JsonResponse({
                    'success': False,
                    'error': 'Для подтверждения действия необходимо ввести ваш пароль'
                })
            
            # Проверяем, является ли текущий пользователь владельцем рабочей области
            try:
                current_membership = WorkspaceMembership.objects.get(
                    workspace=workspace,
                    user=request.user
                )
                
                if current_membership.role != 'owner':
                    return JsonResponse({
                        'success': False,
                        'error': 'Только текущий владелец может передать роль владельца'
                    })
            except WorkspaceMembership.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': 'Вы не являетесь участником этой рабочей области'
                })
            
            # Проверяем пароль текущего пользователя
            user = authenticate(
                username=request.user.username,
                password=password
            )
            
            if not user:
                return JsonResponse({
                    'success': False,
                    'error': 'Неверный пароль. Проверьте правильность ввода.'
                })
            
            # Проверяем, что новый владелец существует в рабочей области
            try:
                new_owner_membership = WorkspaceMembership.objects.select_related('user').get(
                    workspace=workspace,
                    user_id=new_owner_id
                )
            except WorkspaceMembership.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': 'Выбранный пользователь не является участником рабочей области'
                })
            
            # Проверяем, что новый владелец не является текущим пользователем
            if new_owner_membership.user_id == request.user.id:
                return JsonResponse({
                    'success': False,
                    'error': 'Вы уже являетесь владельцем этой рабочей области'
                })
            
            # Выполняем передачу владельца в транзакции
            with transaction.atomic():
                # Изменяем роль текущего владельца на администратора
                current_membership.role = 'member'
                current_membership.save()
                
                # Назначаем нового владельца
                new_owner_membership.role = 'owner'
                new_owner_membership.save()
                
                # Обновляем владельца в модели Workspace
                workspace.owner = new_owner_membership.user
                workspace.save()
            
            # Создаем уведомления для участников
            self.create_notifications(request.user, new_owner_membership.user, workspace)
            
            # Получаем обновленные данные для ответа
            updated_current_membership = WorkspaceMembership.objects.get(
                workspace=workspace,
                user=request.user
            )
            
            # Формируем успешный ответ
            response_data = {
                'success': True,
                'message': f'Роль владельца рабочей области успешно передана пользователю {new_owner_membership.user.username}',
                'data': {
                    'new_owner': {
                        'id': new_owner_membership.user.id,
                        'username': new_owner_membership.user.username,
                        'first_name': new_owner_membership.user.first_name,
                        'last_name': new_owner_membership.user.last_name,
                        'full_name': f"{new_owner_membership.user.first_name} {new_owner_membership.user.last_name}".strip() or new_owner_membership.user.username,
                        'role': 'owner'
                    },
                    'current_user': {
                        'id': request.user.id,
                        'username': request.user.username,
                        'role': updated_current_membership.role,
                        'role_display': updated_current_membership.get_role_display()
                    },
                    'workspace': {
                        'id': workspace.id,
                        'name': workspace.name,
                        'url_hash': workspace.url_hash
                    },
                    'timestamp': timezone.now().isoformat()
                }
            }
            
            return JsonResponse(response_data)
            
        except Exception as e:
            # Логируем ошибку для отладки
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Ошибка при передаче владельца рабочей области: {str(e)}", exc_info=True)
            
            return JsonResponse({
                'success': False,
                'error': 'Произошла внутренняя ошибка сервера',
                'debug_info': str(e) if settings.DEBUG else None
            })
    
    def create_notifications(self, current_owner, new_owner, workspace):
        """Создает уведомления о передаче владельца"""
        
        # Уведомление для нового владельца
        Notification.objects.create(
            user=new_owner,
            message=f'Вам была передана роль владельца рабочей области "{workspace.name}" от пользователя {current_owner.username}',
            level='success',
        )
        
        # Уведомление для предыдущего владельца
        Notification.objects.create(
            user=current_owner,
            message=f'Вы передали роль владельца рабочей области "{workspace.name}" пользователю {new_owner.username}',
            level='info',
        )
        
        # # Уведомление для всех администраторов (опционально)
        # admin_memberships = WorkspaceMembership.objects.filter(
        #     workspace=workspace,
        #     role='admin'
        # ).exclude(user__in=[current_owner, new_owner])
        
        # for membership in admin_memberships:
        #     Notification.objects.create(
        #         user=membership.user,
        #         message=f'Владелец рабочей области "{workspace.name}" изменился. Новый владелец: {new_owner.username}',
        #         level='info',
        #     )


class TeamTransferLeaderRoleView(LoginRequiredMixin, View):
    """Представление для передачи роли лидера команды с проверкой пароля"""
    
    def post(self, request, *args, **kwargs):
        # Проверяем, что это AJAX запрос
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False, 
                'error': 'Неверный тип запроса. Требуется AJAX.'
            })
        
        workspace_url_hash = kwargs.get('workspace_url_hash')
        team_url_hash = kwargs.get('team_url_hash')
        
        try:
            # Получаем команду
            team = get_object_or_404(
                Team,
                url_hash=team_url_hash,
                workspace__url_hash=workspace_url_hash
            )
            
            # Получаем данные из запроса
            new_leader_id = request.POST.get('new_leader_id')
            password = request.POST.get('password')
            
            # Валидация данных
            if not new_leader_id:
                return JsonResponse({
                    'success': False,
                    'error': 'Не выбран новый лидер команды'
                })
            
            if not password:
                return JsonResponse({
                    'success': False,
                    'error': 'Для подтверждения действия необходимо ввести ваш пароль'
                })
            
            # Проверяем права текущего пользователя
            team_membership = TeamMembership.objects.filter(
                team=team,
                user=request.user
            ).first()
            
            workspace_membership = WorkspaceMembership.objects.filter(
                workspace=team.workspace,
                user=request.user
            ).first()
            
            # Определяем, может ли пользователь передать лидера
            is_team_leader = team_membership and team_membership.role == 'leader'
            is_workspace_owner = workspace_membership and workspace_membership.role == 'owner'
            
            if not (is_team_leader or is_workspace_owner):
                return JsonResponse({
                    'success': False,
                    'error': 'У вас нет прав для передачи роли лидера команды'
                })
            
            # Проверяем пароль текущего пользователя
            user = authenticate(
                username=request.user.username,
                password=password
            )
            
            if not user:
                return JsonResponse({
                    'success': False,
                    'error': 'Неверный пароль. Проверьте правильность ввода.'
                })
            
            # Проверяем, что новый лидер существует в команде
            try:
                new_leader_membership = TeamMembership.objects.select_related('user').get(
                    team=team,
                    user_id=new_leader_id
                )
            except TeamMembership.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': 'Выбранный пользователь не является участником команды'
                })
            
            # Проверяем, что новый лидер не является текущим пользователем
            if new_leader_membership.user_id == request.user.id:
                return JsonResponse({
                    'success': False,
                    'error': 'Вы уже являетесь лидером этой команды'
                })
            
            # Проверяем, что пользователь не передает лидера самому себе
            if is_team_leader and new_leader_membership.user_id == request.user.id:
                return JsonResponse({
                    'success': False,
                    'error': 'Вы не можете передать лидерство самому себе'
                })
            
            # Выполняем передачу лидера в транзакции
            with transaction.atomic():
                # Если текущий пользователь - лидер команды, меняем его роль на администратора
                if is_team_leader:
                    team_membership.role = 'member'
                    team_membership.save()
                
                # Назначаем нового лидера
                new_leader_membership.role = 'leader'
                new_leader_membership.save()
            
            # Получаем обновленные данные для ответа
            updated_current_membership = TeamMembership.objects.get(
                team=team,
                user=request.user
            )
            
            # Формируем успешный ответ
            response_data = {
                'success': True,
                'message': f'Роль лидера команды успешно передана пользователю {new_leader_membership.user.username}',
                'data': {
                    'new_leader': {
                        'id': new_leader_membership.user.id,
                        'username': new_leader_membership.user.username,
                        'first_name': new_leader_membership.user.first_name,
                        'last_name': new_leader_membership.user.last_name,
                        'full_name': f"{new_leader_membership.user.first_name} {new_leader_membership.user.last_name}".strip() or new_leader_membership.user.username,
                        'role': 'leader'
                    },
                    'current_user': {
                        'id': request.user.id,
                        'username': request.user.username,
                        'role': updated_current_membership.role,
                        'role_display': updated_current_membership.get_role_display()
                    },
                    'team': {
                        'id': team.id,
                        'name': team.name,
                        'url_hash': team.url_hash
                    },
                    'timestamp': timezone.now().isoformat()
                }
            }
            
            return JsonResponse(response_data)
            
        except Exception as e:
            # Логируем ошибку для отладки
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Ошибка при передаче лидера команды: {str(e)}", exc_info=True)
            
            return JsonResponse({
                'success': False,
                'error': 'Произошла внутренняя ошибка сервера',
                'debug_info': str(e) if settings.DEBUG else None
            })

class TeamDeleteView(LoginRequiredMixin, View):
    """Представление для удаления команды"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        team = get_object_or_404(
            Team, 
            url_hash=kwargs['team_url_hash'],
            workspace__url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем права: только лидер команды или владелец рабочей области
        team_membership = TeamMembership.objects.filter(
            team=team,
            user=request.user,
            role='leader'
        ).first()
        
        workspace_membership = WorkspaceMembership.objects.filter(
            workspace=team.workspace,
            user=request.user,
            role='owner'
        ).first()
        
        if not (team_membership or workspace_membership):
            return JsonResponse({
                'success': False, 
                'error': 'У вас нет прав для удаления команды. Только лидер команды или владелец рабочей области могут удалить команду.'
            })
        
        # Проверяем пароль для подтверждения
        if team_membership or workspace_membership:
            password = request.POST.get('password')
            if not password:
                return JsonResponse({
                    'success': False,
                    'error': 'Для подтверждения удаления команды необходимо ввести ваш пароль'
                })
            
            # Проверяем пароль текущего пользователя
            user = authenticate(
                username=request.user.username,
                password=password
            )
            
            if not user:
                return JsonResponse({
                    'success': False,
                    'error': 'Неверный пароль. Проверьте правильность ввода.'
                })
        
        try:
            # Выполняем все операции в транзакции
            with transaction.atomic():
                # Получаем информацию перед удалением для уведомлений
                team_name = team.name
                workspace_name = team.workspace.name
                team_members = list(team.members.all())
                tasks_count = Task.objects.filter(team=team).count()
                
                # Удаляем все задачи команды
                Task.objects.filter(team=team).delete()
                
                # Удаляем настройки доступа команды
                TeamRoleAccess.objects.filter(team=team).delete()
                
                # Удаляем всех участников команды
                TeamMembership.objects.filter(team=team).delete()
                
                # Удаляем саму команду
                team.delete()
                
                # Создаем уведомления для всех бывших участников команды
                for member in team_members:
                    if member != request.user:  # Не создаем уведомление для того, кто удалил команду
                        self.create_team_deleted_notification(
                            member, 
                            team_name, 
                            workspace_name, 
                            tasks_count,
                            request
                        )
                
                # Создаем уведомление для пользователя, который удалил команду
                self.create_deleter_notification(
                    request.user,
                    team_name,
                    workspace_name,
                    tasks_count,
                    len(team_members)
                )
                
                return JsonResponse({
                    'success': True,
                    'message': f'Команда "{team_name}" успешно удалена',
                    'redirect_url': reverse('workspace:workspace_detail', kwargs={
                        'workspace_url_hash': kwargs['workspace_url_hash']
                    }),
                    'stats': {
                        'team_name': team_name,
                        'tasks_deleted': tasks_count,
                        'members_notified': len(team_members)
                    }
                })
                
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Ошибка при удалении команды: {str(e)}", exc_info=True)
            
            return JsonResponse({
                'success': False,
                'error': 'Произошла внутренняя ошибка сервера при удалении команды',
                'debug_info': str(e) if settings.DEBUG else None
            })
    
    def create_team_deleted_notification(self, user, team_name, workspace_name, tasks_count, request):
        """Создает уведомление об удалении команды для участников"""
        workspace_url = request.build_absolute_uri(
            reverse('workspace:workspace_detail', kwargs={
                'workspace_url_hash': request.resolver_match.kwargs['workspace_url_hash']
            })
        )
        
        message = f'Команда "{team_name}" в рабочей области "{workspace_name}" была удалена'
        if tasks_count > 0:
            message += f'\nВместе с командой удалено {tasks_count} задач'
        
        Notification.objects.create(
            user=user,
            message=message,
            level='warning',
            related_url=workspace_url
        )
    
    def create_deleter_notification(self, user, team_name, workspace_name, tasks_count, members_count):
        """Создает уведомление для пользователя, который удалил команду"""
        message = f'Вы успешно удалили команду "{team_name}" из рабочей области "{workspace_name}"'
        
        details = []
        if tasks_count > 0:
            details.append(f'удалено {tasks_count} задач')
        if members_count > 0:
            details.append(f'оповещено {members_count} участников')
        
        if details:
            message += f'\n' + ', '.join(details)
        
        Notification.objects.create(
            user=user,
            message=message,
            level='info'
        )

class WorkspaceKickMemberView(LoginRequiredMixin, View):
    """Удаление пользователей из рабочей области"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        workspace = get_object_or_404(
            Workspace, 
            url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем право на управление доступом через WorkspaceRoleAccess
        role_access, created = WorkspaceRoleAccess.objects.get_or_create(workspace=workspace)
        if not role_access.has_permission(request.user, 'can_manage_access'):
            return JsonResponse({'success': False, 'error': 'No permission'})
        
        user_ids = request.POST.getlist('user_ids[]')
        if not user_ids:
            return JsonResponse({'success': False, 'error': 'No users selected'})
        
        # Не позволяем удалить самого себя
        if str(request.user.id) in user_ids:
            return JsonResponse({'success': False, 'error': 'Cannot remove yourself'})
        
        removed_users = []
        errors = []
        
        for user_id in user_ids:
            try:
                user_to_remove = User.objects.get(id=user_id)
                
                # Проверяем, что пользователь действительно в рабочей области
                membership = WorkspaceMembership.objects.filter(
                    workspace=workspace, 
                    user=user_to_remove
                ).first()
                
                if not membership:
                    errors.append(f"Пользователь {user_to_remove.username} не состоит в рабочей области")
                    continue
                
                # Проверяем права доступа для удаления
                removal_error = self.check_removal_permission(request.user, membership, user_to_remove)
                if removal_error:
                    errors.append(removal_error)
                    continue
                
                # Удаляем пользователя из рабочей области и всех его команд
                self.remove_user_from_workspace(user_to_remove, workspace)
                
                removed_users.append({
                    'id': user_to_remove.id,
                    'username': user_to_remove.username,
                    'email': user_to_remove.email
                })
                
                # Создаем уведомление для удаленного пользователя
                self.create_workspace_leave_notification(user_to_remove, workspace, request)
                
            except User.DoesNotExist:
                errors.append(f"Пользователь с ID {user_id} не найден")
                continue
        
        # Создаем уведомление для удаляющего
        if removed_users:
            self.create_kicker_notification(request.user, removed_users, workspace)
        
        return JsonResponse({
            'success': True,
            'removed_count': len(removed_users),
            'removed_users': removed_users,
            'errors': errors
        })
    
    def check_removal_permission(self, current_user, target_membership, target_user):
        """Проверяет права доступа для удаления пользователя"""
        current_membership = WorkspaceMembership.objects.get(
            workspace=target_membership.workspace,
            user=current_user
        )
        
        # Владелец может удалить кого угодно (кроме себя)
        if current_membership.role == 'owner':
            return None
        
        # Администратор может удалять только обычных участников
        if current_membership.role == 'admin':
            if target_membership.role == 'owner':
                return f"Нельзя удалить владельца рабочей области {target_user.username}"
            elif target_membership.role == 'admin':
                return f"Нельзя удалить другого администратора {target_user.username}"
            else:
                return None
        
        return "Недостаточно прав для удаления"
    
    def remove_user_from_workspace(self, user, workspace):
        """Удаляет пользователя из рабочей области и всех команд"""
        # Удаляем из рабочей области
        WorkspaceMembership.objects.filter(
            workspace=workspace, 
            user=user
        ).delete()
        
        # Удаляем из всех команд в этой рабочей области
        TeamMembership.objects.filter(
            team__workspace=workspace,
            user=user
        ).delete()
    
    def create_workspace_leave_notification(self, user, workspace, request):
        """Создает уведомление об удалении из рабочей области"""
        message = f'Вас удалили из рабочей области "{workspace.name}"'
        
        Notification.objects.create(
            user=user,
            message=message,
            level='warning'
        )
    
    def create_kicker_notification(self, kicker, removed_users, workspace):
        """Создает уведомление для пользователя, который удалил участников"""
        if len(removed_users) == 1:
            removed_user = removed_users[0]
            message = f'Вы удалили пользователя {removed_user["username"]} из рабочей области "{workspace.name}"'
        else:
            message = f'Вы удалили {len(removed_users)} пользователей из рабочей области "{workspace.name}"'
        
        Notification.objects.create(
            user=kicker,
            message=message,
            level='info'
        )

class TeamKickMemberView(LoginRequiredMixin, View):
    """Удаление пользователей из команды"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        team = get_object_or_404(
            Team, 
            url_hash=kwargs['team_url_hash'],
            workspace__url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем право на управление доступом через TeamRoleAccess
        team_access, created = TeamRoleAccess.objects.get_or_create(team=team)
        if not team_access.has_permission(request.user, 'can_manage_access'):
            return JsonResponse({'success': False, 'error': 'No permission'})
        
        user_ids = request.POST.getlist('user_ids[]')
        if not user_ids:
            return JsonResponse({'success': False, 'error': 'No users selected'})
        
        # Не позволяем удалить самого себя
        if str(request.user.id) in user_ids:
            return JsonResponse({'success': False, 'error': 'Cannot remove yourself'})
        
        removed_users = []
        errors = []
        total_tasks_updated = 0
        
        # Выполняем все операции в транзакции
        with transaction.atomic():
            for user_id in user_ids:
                try:
                    user_to_remove = User.objects.get(id=user_id)
                    
                    # Проверяем, что пользователь действительно в команде
                    membership = TeamMembership.objects.filter(
                        team=team, 
                        user=user_to_remove
                    ).first()
                    
                    if not membership:
                        errors.append(f"Пользователь {user_to_remove.username} не состоит в команде")
                        continue
                    
                    # Проверяем права доступа для удаления
                    removal_error = self.check_removal_permission(request.user, membership, user_to_remove, team)
                    if removal_error:
                        errors.append(removal_error)
                        continue
                    
                    # Получаем задачи, где пользователь назначен исполнителем в этой команде
                    user_tasks = Task.objects.filter(
                        team=team,
                        assignee=user_to_remove
                    )
                    
                    # Запоминаем количество задач для этого пользователя
                    user_tasks_count = user_tasks.count()
                    total_tasks_updated += user_tasks_count
                    
                    # Убираем пользователя из исполнителей задач
                    user_tasks.update(
                        assignee=None,
                        updated_at=timezone.now(),
                        updated_by=request.user
                    )
                    
                    # Удаляем пользователя из команды
                    membership.delete()
                    
                    removed_users.append({
                        'id': user_to_remove.id,
                        'username': user_to_remove.username,
                        'email': user_to_remove.email,
                        'tasks_updated': user_tasks_count
                    })
                    
                    # Создаем уведомление для удаленного пользователя
                    self.create_team_leave_notification(user_to_remove, team, request, user_tasks_count)
                    
                except User.DoesNotExist:
                    errors.append(f"Пользователь с ID {user_id} не найден")
                    continue
            
            # Создаем уведомление для удаляющего
            if removed_users:
                self.create_kicker_notification(request.user, removed_users, team, total_tasks_updated)
        
        if errors and not removed_users:
            return JsonResponse({
                'success': False,
                'error': 'Не удалось удалить пользователей',
                'errors': errors
            })
        
        # Получаем обновленное количество участников
        members_count = team.members.count()
        
        return JsonResponse({
            'success': True,
            'removed_count': len(removed_users),
            'removed_users': removed_users,
            'members_count': members_count,
            'tasks_updated': {
                'total': total_tasks_updated,
                'message': f'Пользователи сняты с исполнения {total_tasks_updated} задач'
            },
            'errors': errors if errors else None
        })
    
    def check_removal_permission(self, current_user, target_membership, target_user, team):
        """Проверяет права доступа для удаления пользователя"""
        try:
            current_membership = TeamMembership.objects.get(
                team=target_membership.team,
                user=current_user
            )
            
            # Лидер может удалить кого угодно (кроме себя)
            if current_membership.role == 'leader':
                # Проверяем, что пользователь не пытается удалить единственного лидера
                if target_membership.role == 'leader':
                    # Проверяем, есть ли другие лидеры в команде
                    other_leaders = TeamMembership.objects.filter(
                        team=team,
                        role='leader'
                    ).exclude(user=target_user).exists()
                    
                    if not other_leaders:
                        return f"Нельзя удалить единственного лидера команды {target_user.username}"
                return None
            
            # Администратор может удалять только обычных участников
            if current_membership.role == 'admin':
                if target_membership.role == 'leader':
                    return f"Нельзя удалить лидера команды {target_user.username}"
                elif target_membership.role == 'admin':
                    return f"Нельзя удалить другого администратора {target_user.username}"
                else:
                    return None
            
            return "Недостаточно прав для удаления"
            
        except TeamMembership.DoesNotExist:
            # Проверяем, является ли пользователь владельцем workspace
            workspace_membership = WorkspaceMembership.objects.filter(
                workspace=team.workspace,
                user=current_user,
                role='owner'
            ).first()
            
            if workspace_membership:
                # Владелец workspace может удалить кого угодно
                if target_membership.role == 'leader':
                    # Проверяем, что пользователь не пытается удалить единственного лидера
                    other_leaders = TeamMembership.objects.filter(
                        team=team,
                        role='leader'
                    ).exclude(user=target_user).exists()
                    
                    if not other_leaders:
                        return f"Нельзя удалить единственного лидера команды {target_user.username}"
                return None
            
            return "Недостаточно прав для удаления"
    
    def create_team_leave_notification(self, user, team, request, tasks_updated_count):
        """Создает уведомление об удалении из команды"""
        workspace_url = request.build_absolute_uri(
            reverse('workspace:workspace_detail', kwargs={
                'workspace_url_hash': team.workspace.url_hash
            })
        )
        
        message = f'Вас удалили из команды "{team.name}" рабочей области "{team.workspace.name}"'
        
        if tasks_updated_count > 0:
            message += f'\nВы были сняты с исполнения {tasks_updated_count} задач этой команды'
        
        Notification.objects.create(
            user=user,
            message=message,
            level='warning',
            related_url=workspace_url
        )
    
    def create_kicker_notification(self, kicker, removed_users, team, total_tasks_updated):
        """Создает уведомление для пользователя, который удалил участников"""
        if len(removed_users) == 1:
            removed_user = removed_users[0]
            message = f'Вы удалили пользователя {removed_user["username"]} из команды "{team.name}"'
            
            if removed_user['tasks_updated'] > 0:
                message += f'\nПользователь снят с исполнения {removed_user["tasks_updated"]} задач'
        else:
            message = f'Вы удалили {len(removed_users)} пользователей из команды "{team.name}"'
            
            if total_tasks_updated > 0:
                message += f'\nПользователи сняты с исполнения {total_tasks_updated} задач'
        
        Notification.objects.create(
            user=kicker,
            message=message,
            level='info'
        )

class WorkspaceChangeMemberRoleView(LoginRequiredMixin, View):
    """Изменение ролей участников рабочей области"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        workspace = get_object_or_404(
            Workspace, 
            url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем, что пользователь - владелец рабочей области
        user_membership = WorkspaceMembership.objects.filter(
            workspace=workspace,
            user=request.user
        ).first()
        
        if not user_membership or user_membership.role != 'owner':
            return JsonResponse({'success': False, 'error': 'No permission'})
        
        user_ids = request.POST.getlist('user_ids[]')
        action = request.POST.get('action')  # 'promote' or 'demote'
        
        if not user_ids:
            return JsonResponse({'success': False, 'error': 'No users selected'})
        
        if action not in ['promote', 'demote']:
            return JsonResponse({'success': False, 'error': 'Invalid action'})
        
        updated_users = []
        errors = []
        
        for user_id in user_ids:
            try:
                user_to_update = User.objects.get(id=user_id)
                
                # Проверяем, что пользователь действительно в рабочей области
                membership = WorkspaceMembership.objects.filter(
                    workspace=workspace, 
                    user=user_to_update
                ).first()
                
                if not membership:
                    errors.append(f"Пользователь {user_to_update.username} не состоит в рабочей области")
                    continue
                
                # Не позволяем изменять роль себе
                if user_to_update == request.user:
                    errors.append(f"Нельзя изменить свою собственную роль")
                    continue
                
                # Выполняем действие
                if action == 'promote':
                    if membership.role == 'member':
                        membership.role = 'admin'
                        membership.save()
                        updated_users.append({
                            'id': user_to_update.id,
                            'username': user_to_update.username,
                            'old_role': 'member',
                            'new_role': 'admin'
                        })
                    else:
                        errors.append(f"Пользователь {user_to_update.username} уже является администратором")
                
                elif action == 'demote':
                    if membership.role == 'admin':
                        membership.role = 'member'
                        membership.save()
                        updated_users.append({
                            'id': user_to_update.id,
                            'username': user_to_update.username,
                            'old_role': 'admin',
                            'new_role': 'member'
                        })
                    else:
                        errors.append(f"Пользователь {user_to_update.username} не является администратором")
                
            except User.DoesNotExist:
                errors.append(f"Пользователь с ID {user_id} не найден")
                continue
        
        # Создаем уведомления
        if updated_users:
            self.create_role_change_notifications(request.user, updated_users, workspace, action)
        
        return JsonResponse({
            'success': True,
            'updated_count': len(updated_users),
            'updated_users': updated_users,
            'errors': errors
        })
    
    def create_role_change_notifications(self, changer, updated_users, workspace, action):
        """Создает уведомления об изменении ролей"""
        for updated_user in updated_users:
            if action == 'promote':
                message = f'Вам назначена роль администратора в рабочей области "{workspace.name}"'
            else:
                message = f'Вы разжалованы до участника в рабочей области "{workspace.name}"'
            
            Notification.objects.create(
                user_id=updated_user['id'],
                message=message,
                level='info'
            )
        
        # Уведомление для того, кто изменил роли
        if len(updated_users) == 1:
            updated_user = updated_users[0]
            if action == 'promote':
                message = f'Вы назначили пользователя {updated_user["username"]} администратором'
            else:
                message = f'Вы разжаловали пользователя {updated_user["username"]} до участника'
        else:
            if action == 'promote':
                message = f'Вы назначили {len(updated_users)} пользователей администраторами'
            else:
                message = f'Вы разжаловали {len(updated_users)} пользователей до участников'
        
        Notification.objects.create(
            user=changer,
            message=message,
            level='info'
        )

class TeamChangeMemberRoleView(LoginRequiredMixin, View):
    """Изменение ролей участников команды"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        team = get_object_or_404(
            Team, 
            url_hash=kwargs['team_url_hash'],
            workspace__url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем, что пользователь - лидер команды
        user_membership = TeamMembership.objects.filter(
            team=team,
            user=request.user
        ).first()
        
        if not user_membership or user_membership.role != 'leader':
            return JsonResponse({'success': False, 'error': 'No permission'})
        
        user_ids = request.POST.getlist('user_ids[]')
        action = request.POST.get('action')  # 'promote' or 'demote'
        
        if not user_ids:
            return JsonResponse({'success': False, 'error': 'No users selected'})
        
        if action not in ['promote', 'demote']:
            return JsonResponse({'success': False, 'error': 'Invalid action'})
        
        updated_users = []
        errors = []
        
        for user_id in user_ids:
            try:
                user_to_update = User.objects.get(id=user_id)
                
                # Проверяем, что пользователь действительно в команде
                membership = TeamMembership.objects.filter(
                    team=team, 
                    user=user_to_update
                ).first()
                
                if not membership:
                    errors.append(f"Пользователь {user_to_update.username} не состоит в команде")
                    continue
                
                # Не позволяем изменять роль себе
                if user_to_update == request.user:
                    errors.append(f"Нельзя изменить свою собственную роль")
                    continue
                
                # Выполняем действие
                if action == 'promote':
                    if membership.role == 'member':
                        membership.role = 'admin'
                        membership.save()
                        updated_users.append({
                            'id': user_to_update.id,
                            'username': user_to_update.username,
                            'old_role': 'member',
                            'new_role': 'admin'
                        })
                    else:
                        errors.append(f"Пользователь {user_to_update.username} уже является администратором")
                
                elif action == 'demote':
                    if membership.role == 'admin':
                        membership.role = 'member'
                        membership.save()
                        updated_users.append({
                            'id': user_to_update.id,
                            'username': user_to_update.username,
                            'old_role': 'admin',
                            'new_role': 'member'
                        })
                    else:
                        errors.append(f"Пользователь {user_to_update.username} не является администратором")
                
            except User.DoesNotExist:
                errors.append(f"Пользователь с ID {user_id} не найден")
                continue
        
        # Создаем уведомления
        if updated_users:
            self.create_role_change_notifications(request.user, updated_users, team, action)
        
        return JsonResponse({
            'success': True,
            'updated_count': len(updated_users),
            'updated_users': updated_users,
            'errors': errors
        })
    
    def create_role_change_notifications(self, changer, updated_users, team, action):
        """Создает уведомления об изменении ролей"""
        for updated_user in updated_users:
            if action == 'promote':
                message = f'Вам назначена роль администратора в команде "{team.name}"'
            else:
                message = f'Вы разжалованы до участника в команде "{team.name}"'
            
            Notification.objects.create(
                user_id=updated_user['id'],
                message=message,
                level='info'
            )
        
        # Уведомление для того, кто изменил роли
        if len(updated_users) == 1:
            updated_user = updated_users[0]
            if action == 'promote':
                message = f'Вы назначили пользователя {updated_user["username"]} администратором команды "{team.name}"'
            else:
                message = f'Вы разжаловали пользователя {updated_user["username"]} до участника команды "{team.name}"'
        else:
            if action == 'promote':
                message = f'Вы назначили {len(updated_users)} пользователей администраторами команды "{team.name}"'
            else:
                message = f'Вы разжаловали {len(updated_users)} пользователей до участников команды "{team.name}"'
        
        Notification.objects.create(
            user=changer,
            message=message,
            level='info'
        )

class SaveWorkspaceAccessSettingsView(LoginRequiredMixin, View):
    """Сохранение настроек прав доступа для рабочей области"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        workspace = get_object_or_404(
            Workspace, 
            url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем, что пользователь имеет право управлять доступом
        role_access, created = WorkspaceRoleAccess.objects.get_or_create(workspace=workspace)
        if not role_access.has_permission(request.user, 'can_manage_access'):
            return JsonResponse({'success': False, 'error': 'No permission to manage access'})
        
        try:
            # Получаем и обновляем настройки для каждого типа прав
            permissions = [
                'can_manage_access',
                'can_edit_workspace', 
                'can_create_teams',
                'can_create_tasks',
                'can_edit_tasks',
                'can_delete_tasks',
                'can_invite_users'
            ]
            
            updated_fields = []
            
            for permission in permissions:
                permission_data = request.POST.get(permission)
                if permission_data:
                    try:
                        if permission == 'can_manage_access' and workspace.get_user_role(self.request.user) != 'owner':
                            return JsonResponse({
                            'success': False, 
                            'error': 'No permission to manage access'
                        })
                        else:
                            # Парсим JSON данные
                            roles = json.loads(permission_data)
                            # Устанавливаем новые значения
                            setattr(role_access, permission, roles)
                            updated_fields.append(permission)
                    except json.JSONDecodeError:
                        return JsonResponse({
                            'success': False, 
                            'error': f'Invalid data format for {permission}'
                        })
            
            # Сохраняем изменения
            if updated_fields:
                role_access.save(update_fields=updated_fields)
            
            return JsonResponse({
                'success': True,
                'message': 'Настройки доступа успешно сохранены',
                'updated_fields': updated_fields
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False, 
                'error': f'Ошибка при сохранении настроек: {str(e)}'
            })

class SaveTeamAccessSettingsView(LoginRequiredMixin, View):
    """Сохранение настроек прав доступа для команды"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        team = get_object_or_404(
            Team, 
            url_hash=kwargs['team_url_hash'],
            workspace__url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем, что пользователь имеет право управлять доступом в команде
        team_access, created = TeamRoleAccess.objects.get_or_create(team=team)
        if not team_access.has_permission(request.user, 'can_manage_access'):
            return JsonResponse({'success': False, 'error': 'No permission to manage access'})
        
        try:
            team_user_role = TeamMembership.objects.get(team=team, user=request.user).role
        except:
            team_user_role = None
        workspace_user_role = WorkspaceMembership.objects.get(workspace=team.workspace, user=request.user).role
        
        try:
            # Получаем и обновляем настройки для каждого типа прав
            permissions = [
                'can_manage_access',
                'can_edit_team',
                'can_invite_users',
                'can_create_tasks',
                'can_edit_tasks',
                'can_delete_tasks',
            ]
            
            updated_fields = []
            
            for permission in permissions:
                permission_data = request.POST.get(permission)
                if permission_data:
                    try:
                        if permission == 'can_manage_access' and not (team_user_role == 'leader' or workspace_user_role == 'owner'):
                            return JsonResponse({
                            'success': False, 
                            'error': 'No permission to manage access'
                        })
                        else:
                            # Парсим JSON данные
                            roles = json.loads(permission_data)
                            # Устанавливаем новые значения
                            setattr(team_access, permission, roles)
                            updated_fields.append(permission)
                    except json.JSONDecodeError:
                        return JsonResponse({
                            'success': False, 
                            'error': f'Invalid data format for {permission}'
                        })
            
            # Обновляем настройку видимости
            visibility = request.POST.get('visibility')
            if visibility in ['private', 'workspace']:
                team_access.visibility = visibility
                updated_fields.append('visibility')
            
            # Сохраняем изменения
            if updated_fields:
                team_access.save(update_fields=updated_fields)
            
            return JsonResponse({
                'success': True,
                'message': 'Настройки доступа команды успешно сохранены',
                'updated_fields': updated_fields
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False, 
                'error': f'Ошибка при сохранении настроек: {str(e)}'
            })

class GetWorkspaceAccessView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        workspace = get_object_or_404(
            Workspace, 
            url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем, что пользователь имеет доступ к рабочей области
        if not workspace.has_access(request.user):
            return JsonResponse({'success': False, 'error': 'No access to workspace'})
        
        # Получаем настройки прав доступа
        role_access, created = WorkspaceRoleAccess.objects.get_or_create(workspace=workspace)
        
        # Формируем данные для ответа
        access_data = {
            'can_manage_access': role_access.can_manage_access,
            'can_edit_workspace': role_access.can_edit_workspace,
            'can_create_teams': role_access.can_create_teams,
            'can_create_tasks': role_access.can_create_tasks,
            'can_edit_tasks': role_access.can_edit_tasks,
            'can_delete_tasks': role_access.can_delete_tasks,
            'can_invite_users': role_access.can_invite_users,
        }
        
        return JsonResponse({
            'success': True,
            'access_data': access_data
        })

class GetTeamAccessView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        team = get_object_or_404(
            Team, 
            url_hash=kwargs['team_url_hash'],
            workspace__url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем, что пользователь имеет доступ к команде
        team_access, _ = TeamRoleAccess.objects.get_or_create(team=team)
        if not team_access.is_team_visible_to_user(request.user):
            return JsonResponse({'success': False, 'error': 'No access to team'})
        
        # Формируем данные для ответа
        access_data = {
            'can_manage_access': team_access.can_manage_access,
            'can_edit_team': team_access.can_edit_team,
            'can_invite_users': team_access.can_invite_users,
            'can_create_tasks': team_access.can_create_tasks,
            'can_edit_tasks': team_access.can_edit_tasks,
            'can_delete_tasks': team_access.can_delete_tasks,
            'visibility': team_access.visibility,
        }
        
        return JsonResponse({
            'success': True,
            'access_data': access_data
        })
'''
todo:
    ⚡️ GetOutWorkspaceView

    ⚡️ WorkspaceEditView
    ⚡️ TeamEditView
    ⚡️ WorkspaceTransferOwnerView
    ⚡️ WorkspaceDeleteView
    ⚡️ TeamDeleteView
    
    ⚡️ medium important:
        * ProfileAvatar
        * WorkspaceAvatar
        * TeamAvatar

    ⚡️ after MVP:
        * tags for tasks (unique words)
        * pinned tasks
        * search for select inputs
'''