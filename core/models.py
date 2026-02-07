from django.db import models
from django.contrib.auth.models import User

class Topic(models.Model):
    LEVEL_CHOICES = [
        ('beginner', '入门'),
        ('intermediate', '进阶'),
        ('advanced', '精通'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    current_level = models.CharField(max_length=50, choices=LEVEL_CHOICES, default='beginner')
    description = models.TextField(blank=True, help_text="具体想学什么，比如'咖啡拉花'")
    created_at = models.DateTimeField(auto_now_add=True)
    last_studied = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.title

class LearningLog(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE)
    date = models.DateField(auto_now_add=True)
    duration_minutes = models.IntegerField(default=15)
    feedback = models.TextField(blank=True, help_text="学习心得")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.topic.title} - {self.date}"

class DailyRecommendation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE)
    date = models.DateField(auto_now_add=True)
    
    # 新增字段：具体推荐视频信息
    recommended_video_title = models.CharField(max_length=500, blank=True, null=True)
    recommended_video_url = models.URLField(max_length=500, blank=True, null=True)
    recommended_reason = models.TextField(blank=True, null=True, help_text="AI推荐理由")

    class Meta:
        unique_together = ['user', 'date']

    def __str__(self):
        return f"{self.user.username} - {self.date} - {self.topic.title}"
