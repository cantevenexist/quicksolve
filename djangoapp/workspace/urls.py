from django.urls import path
from . import views

app_name = 'workspace'

urlpatterns = [
    # === WORKSPACES ===
    path('', views.WorkspaceIndexView.as_view(), name='workspace_index'),
    path('create/', views.WorkspaceCreateView.as_view(), name='workspace_create'),
    path('<str:workspace_url_hash>/', views.WorkspaceDetailView.as_view(), name='workspace_detail'),
    path('<str:workspace_url_hash>/edit/', views.WorkspaceEditView.as_view(), name='workspace_edit'),
    path('<str:workspace_url_hash>/delete/', views.WorkspaceDeleteView.as_view(), name='workspace_delete'),
    path('<str:workspace_url_hash>/transfer-owner/', views.WorkspaceTransferOwnerRoleView.as_view(), name='workspace_transfer_owner'),
    
    # === TEAMS ===
    path('<str:workspace_url_hash>/team/create/', views.TeamCreateView.as_view(), name='team_create'),
    path('<str:workspace_url_hash>/team/<str:team_url_hash>/', views.TeamDetailView.as_view(), name='team_detail'),
    path('<str:workspace_url_hash>/teams/<str:team_url_hash>/edit/', views.TeamEditView.as_view(), name='team_edit'),
    path('<str:workspace_url_hash>/teams/<str:team_url_hash>/delete/', views.TeamDeleteView.as_view(), name='team_delete'),
    path('<str:workspace_url_hash>/team/<str:team_url_hash>/join/', views.TeamJoinView.as_view(), name='team_join'),
    path('<str:workspace_url_hash>/team/<str:team_url_hash>/leave/', views.TeamLeaveView.as_view(), name='team_leave'),
    path('<str:workspace_url_hash>/teams/<str:team_url_hash>/transfer-leader/', views.TeamTransferLeaderRoleView.as_view(), name='team_transfer_leader'),

    # === TASKS ===
    path('<str:workspace_url_hash>/tasks/', views.TaskListView.as_view(), name='task_list'),
    path('<str:workspace_url_hash>/task/create/', views.TaskCreateView.as_view(), name='task_create'),
    path('<str:workspace_url_hash>/task/<str:task_url_hash>/', views.TaskDetailView.as_view(), name='task_detail'),

    # === INVITATIONS ===
    path('<str:workspace_url_hash>/invitations/mass/create/', views.CreateMassInvitationView.as_view(), name='create_mass_invitation'),
    path('<str:workspace_url_hash>/invitations/individual/create/', views.CreateIndividualInvitationsView.as_view(), name='create_individual_invitations'),
    path('<str:workspace_url_hash>/invitations/toggle-all/', views.ToggleAllInvitationsView.as_view(), name='toggle_all_invitations'),
    path('invitations/accept/<str:token>/', views.AcceptInvitationView.as_view(), name='accept_invitation'),
    path('<str:workspace_url_hash>/team/<str:team_url_hash>/invite-members/', views.TeamInviteMemberView.as_view(), name='team_invite_members'),
    
    # === KICK MEMBER ===
    path('<str:workspace_url_hash>/kick-members/', views.WorkspaceKickMemberView.as_view(), name='workspace_kick_members'),
    path('<str:workspace_url_hash>/team/<str:team_url_hash>/kick-members/', views.TeamKickMemberView.as_view(), name='team_kick_members'),

    # === CHANGE MEMBER ROLE ===
    path('<str:workspace_url_hash>/change-member-role/', views.WorkspaceChangeMemberRoleView.as_view(), name='workspace_change_member_role'),
    path('<str:workspace_url_hash>/team/<str:team_url_hash>/change-member-role/', views.TeamChangeMemberRoleView.as_view(), name='team_change_member_role'),
    
    # === ACCESS SETTINGS ===
    path('<str:workspace_url_hash>/access-settings/save/', views.SaveWorkspaceAccessSettingsView.as_view(), name='save_workspace_access_settings'),
    path('<str:workspace_url_hash>/access-settings/get/', views.GetWorkspaceAccessView.as_view(), name='get_workspace_access_settings'),
    path('<str:workspace_url_hash>/team/<str:team_url_hash>/access-settings/save/', views.SaveTeamAccessSettingsView.as_view(), name='save_team_access_settings'),
    path('<str:workspace_url_hash>/<str:team_url_hash>/access-settings/get/', views.GetTeamAccessView.as_view(), name='get_team_access_settings'),
]