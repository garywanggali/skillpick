from duckduckgo_search import DDGS
from .models import LearningLog
import logging

logger = logging.getLogger(__name__)

def get_ai_video_recommendation(topic):
    """
    基于 Topic 和学习记录，智能推荐一个视频。
    返回字典: {
        'title': str,
        'url': str,
        'reason': str
    }
    """
    # 1. 获取上次学习反馈
    last_log = LearningLog.objects.filter(topic=topic).order_by('-created_at').first()
    
    # 2. 构建搜索关键词
    keywords = f"{topic.title} {topic.get_current_level_display()} 教程"
    reason = f"根据你正在学习的'{topic.title}' ({topic.get_current_level_display()})"
    
    if last_log and last_log.feedback:
        # 简单提取反馈中的关键词（取前20个字作为附加搜索词）
        # 这里可以使用更复杂的 NLP，但在本地纯 Python 环境下，直接拼接是最高效的
        feedback_snippet = last_log.feedback[:20]
        keywords += f" {feedback_snippet}"
        reason += f"，以及你上次提到的'{feedback_snippet}...'"
    
    reason += "，为你推荐以下视频："

    # 3. 调用 DuckDuckGo 搜索视频
    print(f"Searching videos for: {keywords}")
    try:
        results = DDGS().videos(
            keywords=keywords,
            region="cn-zh", # 优先中文结果
            safesearch="on",
            max_results=5
        )
        
        # 4. 简单筛选策略：直接返回第一个结果
        # 实际应用中可以加入更复杂的筛选逻辑，比如时长过滤、来源过滤等
        if results:
            first_result = results[0]
            return {
                'title': first_result.get('title', '未知标题'),
                'url': first_result.get('content', '#'), # DDG videos 返回的 content 通常是视频链接
                'reason': reason
            }
            
    except Exception as e:
        logger.error(f"Search failed: {e}")
        print(f"Search failed: {e}")

    # 兜底返回
    return None
