from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('topic/add/', views.TopicCreateView.as_view(), name='topic_add'),
    path('topic/<int:pk>/edit/', views.TopicUpdateView.as_view(), name='topic_edit'),
    path('daily/', views.daily_pick, name='daily_pick'),
    path('log/<int:topic_id>/', views.log_progress, name='log_progress'),
    path('refresh-rec/', views.refresh_recommendation, name='refresh_rec'),
]
