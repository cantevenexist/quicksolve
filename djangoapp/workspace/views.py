from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.contrib import messages
from .models import Workspace, Team, Task
from .forms import WorkspaceCreateForm, TeamCreateForm, TaskCreateForm

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