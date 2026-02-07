from django.db import models
from django.contrib.auth.models import User

class Topic(models.Model):
    LEVEL_CHOICES = [
        ('beginner', '入门'),
        ('intermediate', '进阶'),
        ('advanced', '精通'),
    ]
    
    PRIORITY_CHOICES = [
        ('high', '高'),
        ('medium', '中'),
        ('low', '低'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    current_level = models.CharField(max_length=50, choices=LEVEL_CHOICES, default='beginner')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium', help_text="优先级越高，被推荐的概率越大")
    description = models.TextField(blank=True, help_text="具体想学什么，比如'咖啡拉花'")
    is_archived = models.BooleanField(default=False, help_text="是否暂存（不想学了）")
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
    recommended_video_duration = models.CharField(max_length=50, blank=True, null=True, help_text="视频时长")
    recommended_reason = models.TextField(blank=True, null=True, help_text="AI推荐理由")

    class Meta:
        unique_together = ['user', 'date']

    def __str__(self):
        return f"{self.user.username} - {self.date} - {self.topic.title}"

class TopicRecommendationCache(models.Model):
    """
    全局缓存：针对特定主题关键词和等级的 AI 推荐结果。
    避免重复调用搜索 API 和 LLM。
    """
    topic_keyword = models.CharField(max_length=200, db_index=True) # 例如 "Python 入门"
    level = models.CharField(max_length=50)
    
    video_title = models.CharField(max_length=500)
    video_url = models.URLField(max_length=500)
    video_duration = models.CharField(max_length=50, blank=True, null=True)
    reason = models.TextField(help_text="AI推荐理由")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # 针对同一关键词和等级，只保留一份最新的缓存
        # 但考虑到不同人可能搜同一个词，这里不强制 unique，查询时取最新的即可
        indexes = [
            models.Index(fields=['topic_keyword', 'level']),
        ]

    def __str__(self):
        return f"Cache: {self.topic_keyword} ({self.level})"

class DailyPopupRecord(models.Model):
    """
    记录用户每日弹窗状态
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField(auto_now_add=True)
    action = models.CharField(max_length=20, choices=[('accepted', '接受'), ('rejected', '拒绝')])
    
    class Meta:
        unique_together = ['user', 'date']
    
    def __str__(self):
        return f"{self.user.username} - {self.date} - {self.action}"
