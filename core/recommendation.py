import os
import json
import logging
import requests
from duckduckgo_search import DDGS
from .models import LearningLog
from django.conf import settings

logger = logging.getLogger(__name__)

def search_candidates_from_ddg(keywords, limit=5):
    """
    使用 DuckDuckGo 搜索视频（包含 YouTube, Bilibili 等）
    """
    candidates = []
    try:
        print(f"Searching DDG for: {keywords}")
        # region="cn-zh" 优先中文结果，safesearch="off" 避免过度过滤
        results = DDGS().videos(keywords=keywords, region="cn-zh", safesearch="off", max_results=limit)
        
        if results:
            for r in results:
                candidates.append({
                    'title': r.get('title', 'No Title'),
                    'description': r.get('description', '')[:150],
                    'duration': r.get('duration', 'N/A'),
                    'play': r.get('views', 0), # DDG 返回的是 views
                    'author': r.get('publisher', 'Unknown'),
                    'url': r.get('content', '#'),
                    'provider': 'DuckDuckGo'
                })
    except Exception as e:
        print(f"DDG Search failed: {e}")
        logger.error(f"DDG Search failed: {e}")
        
    return candidates

def search_bilibili_candidates(keywords, limit=5):
    """
    使用 Bilibili API 搜索视频，返回候选列表
    """
    candidates = []
    try:
        print(f"Searching Bilibili API for: {keywords}")
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
        # response.raise_for_status() # B站有时返回412，不抛出异常以便继续尝试其他源
        
        if response.status_code == 200:
            data = response.json()
            if data['code'] == 0 and 'data' in data and 'result' in data['data']:
                videos = data['data']['result']
                for v in videos[:limit]:
                    title = v.get('title', '').replace('<em class="keyword">', '').replace('</em>', '')
                    bvid = v.get('bvid')
                    if bvid:
                        candidates.append({
                            'title': title,
                            'description': v.get('description', '')[:150],
                            'duration': v.get('duration', ''),
                            'play': v.get('play', 0),
                            'author': v.get('author', ''),
                            'url': f"https://www.bilibili.com/video/{bvid}",
                            'provider': 'Bilibili'
                        })
        else:
            print(f"Bilibili API returned status: {response.status_code}")

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
            'desc': c['description'],
            'stats': f"Duration: {c['duration']}, Views: {c['play']}",
            'source': c['provider']
        })
    
    candidates_str = json.dumps(candidates_simple, ensure_ascii=False)

    prompt = f"""
    You are an expert personalized tutor. 
    
    User Profile:
    {user_context}

    Task:
    Analyze the following video candidates (from Bilibili/YouTube etc).
    Select the SINGLE BEST video that matches the user's current level and specific needs.
    
    Selection Criteria:
    1. Relevance: Must match the topic and level.
    2. Quality: Prefer high views or good descriptions.
    3. Accessibility: Bilibili is preferred for Chinese users, but high-quality YouTube content is also acceptable.
    
    Candidates:
    {candidates_str}

    Return ONLY a JSON object (no markdown):
    {{
        "selected_id": <int>,
        "reason": "<string, explain why this video is best for the user in Chinese, max 50 words>"
    }}
    """

    try:
        print(f"Calling LLM ({model}) with {len(candidates)} candidates...")
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
            timeout=20
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
                print(f"LLM Selected: {selection['title']}")
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
        keywords += f" {last_log.feedback[:10]}"
    
    # 3. 获取候选视频 (混合源：Bilibili API + DDG)
    candidates = []
    
    # 尝试 Bilibili API
    bili_candidates = search_bilibili_candidates(keywords, limit=5)
    candidates.extend(bili_candidates)
    
    # 尝试 DDG (作为补充或兜底)
    # 如果 B站返回少于 3 个，或者作为多样性补充，都调用 DDG
    if len(candidates) < 5:
        ddg_candidates = search_candidates_from_ddg(keywords, limit=5)
        candidates.extend(ddg_candidates)
    
    if not candidates:
        print("No candidates found from any source.")
        return None

    # 4. 使用 LLM 选择最佳视频
    selection = call_llm_to_select(topic, last_log, candidates)
    
    # 5. 降级策略
    if not selection:
        print("LLM selection failed, falling back to rule-based.")
        # 简单规则：优先 Bilibili，然后按播放量
        # 归一化播放量逻辑略复杂，这里简单按列表顺序（通常搜索引擎已经排好序了）
        selection = candidates[0]
        selection['reason'] = "根据热度为您推荐，该视频在全网搜索中排名靠前。"

    return {
        'title': selection['title'],
        'url': selection['url'],
        'reason': selection['reason']
    }
