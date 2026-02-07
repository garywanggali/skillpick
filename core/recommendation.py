from duckduckgo_search import DDGS
from .models import LearningLog
import logging
import requests

logger = logging.getLogger(__name__)

def search_bilibili(keywords):
    """
    使用 Bilibili API 搜索视频，返回第一个视频的详细信息
    """
    try:
        url = "http://api.bilibili.com/x/web-interface/search/type"
        params = {
            'search_type': 'video',
            'keyword': keywords
        }
        # 伪装 User-Agent，防止被拦截
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
        }
        
        # 设置超时时间
        response = requests.get(url, params=params, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        # 解析返回结果
        if data['code'] == 0 and 'data' in data and 'result' in data['data']:
            videos = data['data']['result']
            if videos:
                # 获取第一个视频
                video = videos[0]
                
                # 处理标题中的高亮标签
                title = video.get('title', '').replace('<em class="keyword">', '').replace('</em>', '')
                bvid = video.get('bvid')
                
                if bvid:
                    return {
                        'title': title,
                        'url': f"https://www.bilibili.com/video/{bvid}",
                        'provider': 'Bilibili'
                    }
    except Exception as e:
        logger.error(f"Bilibili search failed: {e}")
        print(f"Bilibili search failed: {e}")
    
    return None

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
        feedback_snippet = last_log.feedback[:20]
        keywords += f" {feedback_snippet}"
        reason += f"，以及你上次提到的'{feedback_snippet}...'"
    
    reason += "，为你推荐以下视频："

    # 3. 优先尝试 Bilibili 搜索 (针对中文内容更精准，且不易被墙)
    print(f"Searching Bilibili for: {keywords}")
    bili_rec = search_bilibili(keywords)
    if bili_rec:
        bili_rec['reason'] = reason
        return bili_rec

    # 4. 如果 Bilibili 失败，尝试 DuckDuckGo
    print(f"Searching DDG for: {keywords}")
    try:
        results = DDGS().videos(
            keywords=keywords,
            region="cn-zh", # 优先中文结果
            safesearch="on",
            max_results=5
        )
        
        if results:
            first_result = results[0]
            return {
                'title': first_result.get('title', '未知标题'),
                'url': first_result.get('content', '#'),
                'reason': reason
            }
            
    except Exception as e:
        logger.error(f"DDG Search failed: {e}")
        print(f"DDG Search failed: {e}")

    # 兜底返回
    return None
