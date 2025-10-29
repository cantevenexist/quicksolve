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

from .models import Workspace, Team, Task, IndividualInvitation
from .forms import WorkspaceCreateForm, TeamCreateForm, TaskCreateForm, MassInvitationForm, IndividualInvitationForm
from user_profile.models import UserProfile


class WorkspaceIndexView(LoginRequiredMixin, ListView):
    template_name = 'workspace/workspace_index.html'
    context_object_name = 'workspaces'

    def get_queryset(self):
        return Workspace.objects.filter(
            Q(user=self.request.user) | Q(access_users=self.request.user)
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
            Q(user=self.request.user) | Q(access_users=self.request.user)
        ).distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        workspace = self.get_object()
        
        context['teams'] = Team.objects.filter(workspace=workspace)
        
        if workspace.user == self.request.user:
            context['tasks'] = Task.objects.filter(workspace=workspace)
        else:
            user_teams = Team.objects.filter(
                workspace=workspace, 
                members=self.request.user
            )
            context['tasks'] = Task.objects.filter(
                workspace=workspace, 
                team__in=user_teams
            )
        
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
        self.object.members.add(self.request.user)
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
            Q(user=self.request.user) | Q(access_users=self.request.user)
        )
        return Team.objects.filter(
            workspace__url_hash=self.kwargs['workspace_url_hash'],
            workspace__in=user_workspaces
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        team = self.get_object()
        context['tasks'] = Task.objects.filter(team=team)
        context['is_team_member'] = team.members.filter(id=self.request.user.id).exists()
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
        if self.workspace.user == self.request.user:
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
        if self.workspace.user == self.request.user:
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
        
        # Проверяем, что пользователь - администратор workspace
        if workspace.user != request.user and request.user not in workspace.access_users.all():
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
        
        # Проверяем, что пользователь - администратор workspace
        if workspace.user != request.user and request.user not in workspace.access_users.all():
            return JsonResponse({'success': False, 'error': 'No permission'})
        
        identifiers = request.POST.get('identifiers', '').strip()
        if not identifiers:
            return JsonResponse({'success': False, 'error': 'No identifiers provided'})
        
        # Разделяем идентификаторы по пробелам
        identifier_list = [id.strip() for id in identifiers.split() if id.strip()]
        
        created_invitations = []
        errors = []
        
        for identifier in identifier_list:
            # Определяем тип идентификатора (email или код)
            if '@' in identifier:
                # Это email
                invitation = IndividualInvitation(
                    workspace=workspace,
                    created_by=request.user,
                    email=identifier
                )
            else:
                # Это уникальный код
                try:
                    profile = UserProfile.objects.get(unique_code=identifier)
                    invitation = IndividualInvitation(
                        workspace=workspace,
                        created_by=request.user,
                        unique_code=identifier
                    )
                except UserProfile.DoesNotExist:
                    errors.append(f"Пользователь с кодом {identifier} не найден")
                    continue
            
            invitation.save()
            created_invitations.append(invitation)
            
            # Отправляем уведомление
            self.send_invitation_notification(invitation, request)
        
        return JsonResponse({
            'success': True,
            'created_count': len(created_invitations),
            'errors': errors
        })
    
    def send_invitation_notification(self, invitation, request):
        """Отправляет уведомление о приглашении"""
        invitation_url = request.build_absolute_uri(
            reverse('workspace:accept_invitation', kwargs={'token': invitation.invitation_token})
        )
        
        if invitation.email:
            # Отправка на email
            subject = f'Приглашение в рабочую область {invitation.workspace.name}'
            message = f'''
            Вас пригласили присоединиться к рабочей области "{invitation.workspace.name}".
            
            Для принятия приглашения перейдите по ссылке:
            {invitation_url}
            
            Если у вас нет аккаунта, зарегистрируйтесь и используйте эту же ссылку.
            '''
            
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [invitation.email],
                fail_silently=True,
            )
        
        # TODO: Добавить отправку уведомления в системе
        # (зависит от вашей системы уведомлений)


class ToggleAllInvitationsView(LoginRequiredMixin, View):
    """Включение/выключение массового приглашения"""
    
    def post(self, request, *args, **kwargs):
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Invalid request'})
        
        workspace = get_object_or_404(
            Workspace, 
            url_hash=kwargs['workspace_url_hash']
        )
        
        # Проверяем, что пользователь - администратор workspace
        if workspace.user != request.user and request.user not in workspace.access_users.all():
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
        print(f"DEBUG: Handling individual invitation for {invitation.email or invitation.unique_code}")  # Для отладки
        
        # Проверяем, соответствует ли пользователь приглашению
        if not self.user_matches_invitation(request.user, invitation):
            messages.error(request, 'Это приглашение предназначено для другого пользователя')
            return redirect('workspace:workspace_index')
        
        # Добавляем пользователя в workspace
        invitation.workspace.access_users.add(request.user)
        invitation.status = 'accepted'
        invitation.accepted_at = timezone.now()
        invitation.save()
        
        messages.success(request, f'Вы успешно присоединились к рабочей области {invitation.workspace.name}')
        return redirect('workspace:workspace_detail', workspace_url_hash=invitation.workspace.url_hash)
    
    def handle_mass_invitation(self, request, workspace):
        """Обрабатывает массовое приглашение"""
        print(f"DEBUG: Handling mass invitation for {workspace.name}")  # Для отладки
        
        # Добавляем пользователя в участники
        workspace.access_users.add(request.user)
        workspace.mass_invitation_current_uses += 1
        workspace.save()
        
        messages.success(request, f'Вы успешно присоединились к рабочей области {workspace.name}')
        return redirect('workspace:workspace_detail', workspace_url_hash=workspace.url_hash)
    
    def user_matches_invitation(self, user, invitation):
        """Проверяет, соответствует ли пользователь приглашению"""
        # Если приглашение по email - проверяем email
        if invitation.email and invitation.email == user.email:
            return True
        
        # Если приглашение по коду - проверяем код
        if invitation.unique_code:
            try:
                user_profile = UserProfile.objects.get(user=user)
                if user_profile.unique_code == invitation.unique_code:
                    return True
            except UserProfile.DoesNotExist:
                pass
        
        return False