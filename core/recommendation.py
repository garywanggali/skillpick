import os
import json
import logging
import requests
from duckduckgo_search import DDGS
from .models import LearningLog
from django.conf import settings

logger = logging.getLogger(__name__)

def search_bilibili_candidates(keywords, limit=10):
    """
    使用 Bilibili API 搜索视频，返回候选列表
    """
    candidates = []
    try:
        url = "http://api.bilibili.com/x/web-interface/search/type"
        params = {
            'search_type': 'video',
            'keyword': keywords,
            'order': 'totalrank', # 综合排序
            'page': 1
        }
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if data['code'] == 0 and 'data' in data and 'result' in data['data']:
            videos = data['data']['result']
            for v in videos[:limit]:
                title = v.get('title', '').replace('<em class="keyword">', '').replace('</em>', '')
                description = v.get('description', '')[:150] # 截取部分简介
                duration = v.get('duration', '')
                play = v.get('play', 0)
                author = v.get('author', '')
                bvid = v.get('bvid')
                
                if bvid:
                    candidates.append({
                        'title': title,
                        'description': description,
                        'duration': duration,
                        'play': play,
                        'author': author,
                        'url': f"https://www.bilibili.com/video/{bvid}",
                        'bvid': bvid,
                        'provider': 'Bilibili'
                    })
    except Exception as e:
        logger.error(f"Bilibili search failed: {e}")
        print(f"Bilibili search failed: {e}")
    
    return candidates

def call_llm_to_select(topic, last_log, candidates):
    """
    调用大模型（OpenAI 兼容接口）从候选中选择最佳视频
    """
    api_key = getattr(settings, 'OPENAI_API_KEY', None) or os.environ.get('OPENAI_API_KEY')
    api_base = getattr(settings, 'OPENAI_API_BASE', 'https://api.openai.com/v1')
    model = getattr(settings, 'OPENAI_MODEL', 'gpt-3.5-turbo')

    if not api_key:
        print("Warning: No OPENAI_API_KEY found. Skipping AI selection.")
        return None

    # 构建 Prompt
    user_context = f"""
    User Topic: {topic.title}
    Current Level: {topic.get_current_level_display()}
    Description: {topic.description}
    Last Study Feedback: {last_log.feedback if last_log else "None"}
    """
    
    # 简化候选列表以减少 Token
    candidates_simple = []
    for i, c in enumerate(candidates):
        candidates_simple.append({
            'id': i,
            'title': c['title'],
            'description': c['description'],
            'duration': c['duration'],
            'play': c['play'],
            'author': c['author']
        })
    
    candidates_str = json.dumps(candidates_simple, ensure_ascii=False)

    prompt = f"""
    You are an expert personalized tutor. The user is learning a specific topic.
    
    User Profile:
    {user_context}

    Task:
    Analyze the following video candidates from Bilibili.
    Select the SINGLE BEST video that matches the user's current level and specific needs.
    If the user is a beginner, avoid advanced or obscure content.
    If the user has specific feedback, prioritize content that addresses it.
    
    Candidates:
    {candidates_str}

    Return ONLY a JSON object with the following format (do not wrap in markdown):
    {{
        "selected_id": <int>,
        "reason": "<string, explain why this video is best for the user in Chinese, max 50 words>"
    }}
    """

    try:
        print(f"Calling LLM ({model})...")
        response = requests.post(
            f"{api_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2
            },
            timeout=15
        )
        
        if response.status_code == 200:
            resp_json = response.json()
            content = resp_json['choices'][0]['message']['content']
            # 清理可能的 Markdown 标记
            content = content.replace('```json', '').replace('```', '').strip()
            result = json.loads(content)
            
            idx = result.get('selected_id')
            if idx is not None and isinstance(idx, int) and 0 <= idx < len(candidates):
                selection = candidates[idx]
                selection['reason'] = result.get('reason', 'AI 智能推荐')
                return selection
        else:
            print(f"LLM API Error: {response.status_code} - {response.text}")
            
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        print(f"LLM call failed: {e}")
        
    return None

def get_ai_video_recommendation(topic):
    """
    基于 Topic 和学习记录，智能推荐一个视频。
    """
    # 1. 获取上次学习反馈
    last_log = LearningLog.objects.filter(topic=topic).order_by('-created_at').first()
    
    # 2. 构建搜索关键词
    keywords = f"{topic.title} {topic.get_current_level_display()} 教程"
    if last_log and last_log.feedback:
        # 提取反馈中的关键名词作为补充
        keywords += f" {last_log.feedback[:10]}"
    
    # 3. 获取候选视频 (Bilibili)
    print(f"Searching Bilibili for: {keywords}")
    candidates = search_bilibili_candidates(keywords)
    
    if not candidates:
        # 兜底：尝试 DDG
        try:
            results = DDGS().videos(keywords=keywords, region="cn-zh", max_results=1)
            if results:
                res = results[0]
                return {
                    'title': res.get('title'),
                    'url': res.get('content'),
                    'reason': "由于 B站 搜索无结果，为您推荐全网相关视频。"
                }
        except:
            pass
        return None

    # 4. 使用 LLM 选择最佳视频
    selection = call_llm_to_select(topic, last_log, candidates)
    
    # 5. 降级策略 (如果没有 LLM Key 或调用失败)
    if not selection:
        print("LLM selection failed or skipped, falling back to rule-based selection.")
        # 简单规则：选择播放量最高且时长适中（假设 > 5分钟）的
        # 这里 B站 API 返回的 duration 可能是 "mm:ss" 格式，也可能是秒数，处理比较麻烦，简单按播放量降序
        # B站 API 返回的 play 可能是数字也可能是字符串
        def parse_play(p):
            if isinstance(p, int): return p
            if isinstance(p, str) and p.isdigit(): return int(p)
            return 0
            
        candidates.sort(key=lambda x: parse_play(x.get('play', 0)), reverse=True)
        selection = candidates[0]
        selection['reason'] = f"根据热度为您推荐，该视频播放量较高 ({selection['play']})，深受社区认可。"

    return {
        'title': selection['title'],
        'url': selection['url'],
        'reason': selection['reason']
    }
