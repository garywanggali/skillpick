from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView, CreateView, UpdateView
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from .models import Topic, LearningLog, DailyRecommendation
import random
from django import forms
from django.utils import timezone
from datetime import date
from .recommendation import get_ai_video_recommendation
from django.db import IntegrityError
from django.http import JsonResponse
from django.views.decorators.http import require_POST

# Forms
class TopicForm(forms.ModelForm):
    class Meta:
        model = Topic
        fields = ['title', 'current_level', 'description']
        labels = {
            'title': '想学什么',
            'current_level': '当前水平',
            'description': '具体描述',
        }

class LogForm(forms.ModelForm):
    class Meta:
        model = LearningLog
        fields = ['duration_minutes', 'feedback']
        labels = {
            'duration_minutes': '学习时长(分钟)',
            'feedback': '学习心得',
        }

# Views
class RegisterView(CreateView):
    form_class = UserCreationForm
    template_name = 'core/register.html'
    success_url = reverse_lazy('dashboard')

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        return response

class DashboardView(LoginRequiredMixin, ListView):
    model = Topic
    template_name = 'core/dashboard.html'
    context_object_name = 'topics'

    def get_queryset(self):
        # 默认只显示未归档的主题
        return Topic.objects.filter(user=self.request.user, is_archived=False).order_by('-last_studied', '-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # 获取归档的主题
        context['archived_topics'] = Topic.objects.filter(user=self.request.user, is_archived=True).order_by('-created_at')
        
        # 获取今日推荐
        today = date.today()
        recommendation = DailyRecommendation.objects.filter(user=self.request.user, date=today).first()
        
        if recommendation:
            context['daily_topic'] = recommendation.topic
            context['recommendation'] = recommendation
            # 获取上次学习记录
            context['last_log'] = LearningLog.objects.filter(topic=recommendation.topic).order_by('-created_at').first()
            
            # 兼容旧数据：如果没有 AI 推荐，回退到 Bilibili 搜索
            if not recommendation.recommended_video_url:
                level_display = recommendation.topic.get_current_level_display()
                search_query = f"{recommendation.topic.title} {level_display} 教程"
                context['video_url'] = f"https://search.bilibili.com/all?keyword={search_query}"
        else:
            # 如果没有推荐，且有未归档主题，标记需要生成，由前端 AJAX 触发
            if self.get_queryset().exists():
                context['need_generation'] = True
            
        return context

@login_required
@require_POST
def generate_recommendation_api(request):
    """
    异步生成推荐 API
    """
    today = date.today()
    
    # Check if already exists
    if DailyRecommendation.objects.filter(user=request.user, date=today).exists():
        return JsonResponse({'status': 'exists'})
        
    topics = Topic.objects.filter(user=request.user, is_archived=False)
    if not topics.exists():
        return JsonResponse({'status': 'no_topics'})
        
    selected_topic = random.choice(list(topics))
    
    # 耗时操作：多源搜索 + LLM
    ai_rec = get_ai_video_recommendation(selected_topic)
    
    try:
        DailyRecommendation.objects.create(
            user=request.user,
            topic=selected_topic,
            date=today,
            recommended_video_title=ai_rec['title'] if ai_rec else None,
            recommended_video_url=ai_rec['url'] if ai_rec else None,
            recommended_reason=ai_rec['reason'] if ai_rec else None
        )
        return JsonResponse({'status': 'created'})
    except IntegrityError:
        return JsonResponse({'status': 'exists'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

class TopicCreateView(LoginRequiredMixin, CreateView):
    model = Topic
    form_class = TopicForm
    template_name = 'core/topic_form.html'
    success_url = reverse_lazy('dashboard')

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = '添加新主题'
        return context

class TopicUpdateView(LoginRequiredMixin, UpdateView):
    model = Topic
    form_class = TopicForm
    template_name = 'core/topic_form.html'
    success_url = reverse_lazy('dashboard')

    def get_queryset(self):
        # 确保只能编辑自己的主题
        return Topic.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = '编辑主题'
        return context

@login_required
def daily_pick(request):
    # 尝试获取今日推荐
    today = date.today()
    recommendation = DailyRecommendation.objects.filter(user=request.user, date=today).first()
    
    if recommendation:
        selected_topic = recommendation.topic
    else:
        # 如果没有推荐（可能还没访问 Dashboard，或者没有 Topics），尝试生成
        topics = Topic.objects.filter(user=request.user)
        if not topics.exists():
            return redirect('topic_add')
        
        selected_topic = random.choice(list(topics))
        
        # 调用 AI 推荐服务
        ai_rec = get_ai_video_recommendation(selected_topic)

        try:
            recommendation = DailyRecommendation.objects.create(
                user=request.user,
                topic=selected_topic,
                date=today,
                recommended_video_title=ai_rec['title'] if ai_rec else None,
                recommended_video_url=ai_rec['url'] if ai_rec else None,
                recommended_reason=ai_rec['reason'] if ai_rec else None
            )
        except IntegrityError:
            # 如果并发请求导致已存在，则重新获取
            recommendation = DailyRecommendation.objects.filter(user=request.user, date=today).first()
            selected_topic = recommendation.topic
    
    # 准备上下文
    context = {
        'topic': selected_topic,
        'recommendation': recommendation,
        'form': LogForm(),
        'last_log': LearningLog.objects.filter(topic=selected_topic).order_by('-created_at').first()
    }

    # 兼容旧逻辑的 video_url
    if not recommendation.recommended_video_url:
        level_display = selected_topic.get_current_level_display()
        search_query = f"{selected_topic.title} {level_display} 教程"
        context['search_query'] = search_query
        context['video_url'] = f"https://search.bilibili.com/all?keyword={search_query}"

    return render(request, 'core/daily_pick.html', context)

@login_required
def log_progress(request, topic_id):
    topic = get_object_or_404(Topic, id=topic_id, user=request.user)
    if request.method == 'POST':
        form = LogForm(request.POST)
        if form.is_valid():
            log = form.save(commit=False)
            log.topic = topic
            log.save()
            
            topic.last_studied = timezone.now()
            topic.save()
            
            return redirect('dashboard')
    else:
        form = LogForm()
    
    return render(request, 'core/log_form.html', {'form': form, 'topic': topic})

@login_required
def refresh_recommendation(request):
    """
    仅用于调试：删除今日推荐记录，触发重新生成
    """
    today = date.today()
    DailyRecommendation.objects.filter(user=request.user, date=today).delete()
    return redirect('dashboard')

@login_required
def toggle_archive_topic(request, pk):
    topic = get_object_or_404(Topic, pk=pk, user=request.user)
    if request.method == 'POST':
        topic.is_archived = not topic.is_archived
        topic.save()
    return redirect('dashboard')

@login_required
def delete_topic(request, pk):
    topic = get_object_or_404(Topic, pk=pk, user=request.user)
    if request.method == 'POST':
        topic.delete()
    return redirect('dashboard')
