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
User = get_user_model()
from .models import Workspace, WorkspaceMembership, Team, TeamMembership, Task, IndividualInvitation
from .forms import WorkspaceCreateForm, TeamCreateForm, TaskCreateForm, MassInvitationForm, IndividualInvitationForm
from user_profile.models import UserProfile, Notification


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
        messages.success(self.request, 'Рабочая область успешно создана!')
        return super().form_valid(form)


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
        
        context['teams'] = Team.objects.filter(workspace=workspace)
        
        # Проверяем права пользователя через WorkspaceMembership
        user_membership = WorkspaceMembership.objects.filter(
            workspace=workspace, 
            user=self.request.user
        ).first()
        
        # Если пользователь владелец или администратор - показываем все задачи
        if user_membership and user_membership.role in ['owner', 'admin']:
            context['tasks'] = Task.objects.filter(workspace=workspace)
        else:
            # Иначе показываем только задачи команд, в которых состоит пользователь
            user_teams = Team.objects.filter(
                workspace=workspace, 
                members=self.request.user
            )
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


class TeamCreateView(LoginRequiredMixin, CreateView):
    model = Team
    form_class = TeamCreateForm
    template_name = 'workspace/team_create.html'

    def dispatch(self, request, *args, **kwargs):
        self.workspace = get_object_or_404(
            Workspace, 
            url_hash=kwargs['workspace_url_hash']
        )
        if not self.workspace.has_access(request.user):
            from django.http import Http404
            raise Http404("У вас нет доступа к этой рабочей области")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.workspace = self.workspace
        response = super().form_valid(form)
        
        # Добавляем создателя в команду с ролью лидера
        from .models import TeamMembership
        TeamMembership.objects.create(
            team=self.object,
            user=self.request.user,
            role='leader'
        )
        
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
        user_membership = TeamMembership.objects.filter(
            team=team, 
            user=self.request.user
        ).first()
        
        context['tasks'] = Task.objects.filter(team=team)
        context['is_team_member'] = team.members.filter(id=self.request.user.id).exists()
        context['team_members'] = team_members
        context['workspace_members'] = available_users
        context['team_members_users'] = [member.user for member in team_members]
        context['user_membership'] = user_membership  # Добавляем информацию о текущем пользователе
        
        return context


class TaskListView(LoginRequiredMixin, ListView):
    model = Task
    template_name = 'workspace/task_list.html'
    context_object_name = 'tasks'
    paginate_by = 20

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
        queryset = Task.objects.filter(workspace=self.workspace)
        
        # Фильтрация по команде через GET параметр
        team_filter = self.request.GET.get('team')
        if team_filter:
            queryset = queryset.filter(team__url_hash=team_filter)
        
        # Права доступа
        user_membership = WorkspaceMembership.objects.filter(
            workspace=self.workspace, 
            user=self.request.user
        ).first()
        
        if user_membership and user_membership.role in ['owner', 'admin']:
            return queryset.select_related('team', 'assignee', 'reporter')
        else:
            user_teams = Team.objects.filter(
                workspace=self.workspace, 
                members=self.request.user
            )
            return queryset.filter(
                Q(team__in=user_teams) | Q(team__isnull=True)
            ).select_related('team', 'assignee', 'reporter')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['workspace'] = self.workspace
        context['teams'] = Team.objects.filter(workspace=self.workspace)
        
        # Добавляем выбранную команду для фильтрации
        selected_team = self.request.GET.get('team')
        if selected_team:
            context['selected_team'] = get_object_or_404(Team, url_hash=selected_team)
        
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
        if not self.workspace.has_access(request.user):
            from django.http import Http404
            raise Http404("У вас нет доступа к этой рабочей области")
        
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['workspace'] = self.workspace
        kwargs['user'] = self.request.user
        
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
            
        return kwargs

    def form_valid(self, form):
        # Устанавливаем workspace и reporter перед сохранением
        form.instance.workspace = self.workspace
        form.instance.reporter = self.request.user
            
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
        
        # Добавляем team_from_get в контекст для шаблона
        team_from_get = self.request.GET.get('team')
        if team_from_get:
            try:
                context['team'] = Team.objects.get(
                    url_hash=team_from_get,
                    workspace=self.workspace
                )
            except Team.DoesNotExist:
                context['team'] = None
        else:
            context['team'] = None
            
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

    def get_queryset(self):
        user_membership = WorkspaceMembership.objects.filter(
            workspace=self.workspace, 
            user=self.request.user
        ).first()
        
        if user_membership and user_membership.role in ['owner', 'admin']:
            return Task.objects.filter(workspace=self.workspace)
        else:
            user_teams = Team.objects.filter(
                workspace=self.workspace, 
                members=self.request.user
            )
            return Task.objects.filter(
                workspace=self.workspace
            ).filter(
                Q(team__in=user_teams) | Q(team__isnull=True)
            )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['workspace'] = self.workspace
        return context


class CreateMassInvitationView(LoginRequiredMixin, View):
    """Обновление массового приглашения"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        workspace = get_object_or_404(
            Workspace, 
            url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем, что пользователь - владелец или администратор workspace
        user_role = workspace.get_user_role(request.user)
        if user_role not in ['owner', 'admin']:
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
        
        # Проверяем, что пользователь - владелец или администратор workspace
        user_role = workspace.get_user_role(request.user)
        if user_role not in ['owner', 'admin']:
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
        
        # Проверяем, что пользователь - владелец или администратор workspace
        user_role = workspace.get_user_role(request.user)
        if user_role not in ['owner', 'admin']:
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
        
        # Проверяем, что пользователь - лидер или администратор команды
        user_membership = TeamMembership.objects.filter(
            team=team,
            user=request.user
        ).first()
        
        if not user_membership or user_membership.role not in ['leader', 'admin']:
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

class WorkspaceKickMemberView(LoginRequiredMixin, View):
    """Удаление пользователей из рабочей области"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        workspace = get_object_or_404(
            Workspace, 
            url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем, что пользователь - владелец или администратор рабочей области
        user_membership = WorkspaceMembership.objects.filter(
            workspace=workspace,
            user=request.user
        ).first()
        
        if not user_membership or user_membership.role not in ['owner', 'admin']:
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
                removal_error = self.check_removal_permission(user_membership, membership, user_to_remove)
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
    
    def check_removal_permission(self, user_membership, target_membership, target_user):
        """Проверяет права доступа для удаления пользователя"""
        # Владелец может удалить кого угодно (кроме себя)
        if user_membership.role == 'owner':
            return None
        
        # Администратор может удалять только обычных участников
        if user_membership.role == 'admin':
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
        
        # Проверяем, что пользователь - лидер или администратор команды
        user_membership = TeamMembership.objects.filter(
            team=team,
            user=request.user
        ).first()
        
        if not user_membership or user_membership.role not in ['leader', 'admin']:
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
                
                # Проверяем, что пользователь действительно в команде
                membership = TeamMembership.objects.filter(
                    team=team, 
                    user=user_to_remove
                ).first()
                
                if not membership:
                    errors.append(f"Пользователь {user_to_remove.username} не состоит в команде")
                    continue
                
                # Проверяем права доступа для удаления
                removal_error = self.check_removal_permission(user_membership, membership, user_to_remove)
                if removal_error:
                    errors.append(removal_error)
                    continue
                
                # Удаляем пользователя из команды
                membership.delete()
                
                removed_users.append({
                    'id': user_to_remove.id,
                    'username': user_to_remove.username,
                    'email': user_to_remove.email
                })
                
                # Создаем уведомление для удаленного пользователя
                self.create_team_leave_notification(user_to_remove, team, request)
                
            except User.DoesNotExist:
                errors.append(f"Пользователь с ID {user_id} не найден")
                continue
        
        # Создаем уведомление для удаляющего
        if removed_users:
            self.create_kicker_notification(request.user, removed_users, team)
        
        return JsonResponse({
            'success': True,
            'removed_count': len(removed_users),
            'removed_users': removed_users,
            'errors': errors
        })
    
    def check_removal_permission(self, user_membership, target_membership, target_user):
        """Проверяет права доступа для удаления пользователя"""
        # Лидер может удалить кого угодно (кроме себя)
        if user_membership.role == 'leader':
            return None
        
        # Администратор может удалять только обычных участников
        if user_membership.role == 'admin':
            if target_membership.role == 'leader':
                return f"Нельзя удалить лидера команды {target_user.username}"
            elif target_membership.role == 'admin':
                return f"Нельзя удалить другого администратора {target_user.username}"
            else:
                return None
        
        return "Недостаточно прав для удаления"
    
    def create_team_leave_notification(self, user, team, request):
        """Создает уведомление об удалении из команды"""
        workspace_url = request.build_absolute_uri(
            reverse('workspace:workspace_detail', kwargs={
                'workspace_url_hash': team.workspace.url_hash
            })
        )
        
        message = f'Вас удалили из команды "{team.name}" рабочей области "{team.workspace.name}"'
        
        Notification.objects.create(
            user=user,
            message=message,
            level='warning',
            related_url=workspace_url
        )
    
    def create_kicker_notification(self, kicker, removed_users, team):
        """Создает уведомление для пользователя, который удалил участников"""
        if len(removed_users) == 1:
            removed_user = removed_users[0]
            message = f'Вы удалили пользователя {removed_user["username"]} из команды "{team.name}"'
        else:
            message = f'Вы удалили {len(removed_users)} пользователей из команды "{team.name}"'
        
        Notification.objects.create(
            user=kicker,
            message=message,
            level='info'
        )
'''
todo:
    WorkspaceChangeMemberRoleView
    TeamChangeMemberRoleView
    WorkspaceEditView
    TeamEditView

    tags for tasks (unique words)
    search for tasks
    pinned tasks
edit:
    get_queryset in TaskListView – add filters:
        * asigned (to me/to user if admin rules)
        * status
        * deadline
        * category
        * pinned
'''