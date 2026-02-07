import warnings
# 忽略 DuckDuckGo 的 RuntimeWarning
warnings.filterwarnings("ignore", category=RuntimeWarning, module="duckduckgo_search")

import os
import json
import logging
import requests
import re
import urllib.parse
from duckduckgo_search import DDGS
from .models import LearningLog
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from .models import LearningLog, TopicRecommendationCache

logger = logging.getLogger(__name__)

# 精选视频库 (最后防线)
HARDCODED_VIDEOS = {
    'python': {'title': 'Python 教程 - 廖雪峰', 'url': 'https://www.bilibili.com/video/BV1wD4y1o7AS'},
    'java': {'title': 'Java 零基础教程 - 韩顺平', 'url': 'https://www.bilibili.com/video/BV1fh411y7R8'},
    '英语': {'title': '英语口语天天练', 'url': 'https://www.bilibili.com/video/BV154411u7Uf'},
    '健身': {'title': '帕梅拉 10分钟全身燃脂', 'url': 'https://www.bilibili.com/video/BV1pK411p7d6'},
    '足球': {'title': '足球基础教学 - 停球与传球', 'url': 'https://www.bilibili.com/video/BV1Cx411q7t5'},
    'default': {'title': 'Bilibili 热门教程', 'url': 'https://www.bilibili.com/v/technology/computer/'}
}

def search_candidates_from_ddg(keywords, limit=5):
    """
    使用 DuckDuckGo 搜索视频
    """
    candidates = []
    try:
        print(f"Searching DDG for: {keywords}")
        results = DDGS().videos(keywords=keywords, region="cn-zh", safesearch="off", max_results=limit)
        
        if results:
            for r in results:
                candidates.append({
                    'title': r.get('title', 'No Title'),
                    'description': r.get('description', '')[:150],
                    'duration': r.get('duration', 'N/A'),
                    'play': r.get('views', 0),
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
    使用 Bilibili API 搜索视频，返回候选列表。
    如果 API 失败 (412)，尝试 HTML 解析。
    """
    candidates = []
    
    # 1. 尝试 API
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
                return candidates # 如果 API 成功，直接返回
        else:
            print(f"Bilibili API returned status: {response.status_code}")

    except Exception as e:
        logger.error(f"Bilibili API search failed: {e}")
        print(f"Bilibili API search failed: {e}")

    # 2. 如果 API 失败，尝试 HTML 解析 (Bilibili Web Scraper)
    try:
        print(f"Attempting Bilibili HTML Scrape for: {keywords}")
        url = "https://search.bilibili.com/all"
        params = {'keyword': keywords}
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36',
            'Referer': 'https://www.bilibili.com/'
        }
        response = requests.get(url, params=params, headers=headers, timeout=5)
        
        if response.status_code == 200:
            matches = re.finditer(r'//www\.bilibili\.com/video/(?P<bvid>BV[a-zA-Z0-9]+)', response.text)
            seen_bvids = set()
            
            for match in matches:
                bvid = match.group('bvid')
                if bvid not in seen_bvids:
                    seen_bvids.add(bvid)
                    candidates.append({
                        'title': f"Bilibili Video {bvid} (Parsed)",
                        'description': 'Parsed from search page',
                        'duration': 'N/A',
                        'play': 0,
                        'author': 'Bilibili',
                        'url': f"https://www.bilibili.com/video/{bvid}",
                        'provider': 'Bilibili (Web)'
                    })
                    if len(candidates) >= limit: break
    except Exception as e:
        print(f"Bilibili HTML Scrape failed: {e}")

    return candidates

def search_zhihu_candidates(keywords, limit=3):
    """
    搜索知乎视频和回答
    """
    print(f"Searching Zhihu for: {keywords}")
    candidates = []
    try:
        url = "https://www.zhihu.com/api/v4/search_v3"
        params = {
            't': 'general',
            'q': keywords,
            'correction': 1,
            'offset': 0,
            'limit': limit * 2
        }
        # 修复编码问题
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36',
            'Referer': 'https://www.zhihu.com/search?type=content&q=' + urllib.parse.quote(keywords)
        }
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        
        if resp.status_code == 200:
            data = resp.json()
            if 'data' in data:
                for item in data['data']:
                    obj = item.get('object', {})
                    type_ = item.get('type')
                    
                    title = ""
                    desc = ""
                    url = ""
                    
                    if type_ == 'zvideo': # 视频
                        title = obj.get('title', '')
                        desc = obj.get('description', '')
                        url = f"https://www.zhihu.com/zvideo/{obj.get('id')}"
                    elif type_ == 'search_result' and 'title' in obj: # 通用结果
                        title = obj.get('title', '').replace('<em>', '').replace('</em>', '')
                        desc = obj.get('content', '')[:100]
                        if 'id' in obj:
                            url = f"https://www.zhihu.com/question/{obj.get('question', {}).get('id')}/answer/{obj.get('id')}"
                    
                    if title and url:
                        candidates.append({
                            'title': title,
                            'description': desc,
                            'duration': 'N/A',
                            'play': obj.get('voteup_count', 0),
                            'author': obj.get('author', {}).get('name', ''),
                            'url': url,
                            'provider': 'Zhihu'
                        })
                        if len(candidates) >= limit: break
    except Exception as e:
        print(f"Zhihu Search failed: {e}")
        
    return candidates

def search_sohu_candidates(keywords, limit=3):
    """
    搜索搜狐视频 (HTML解析)
    """
    print(f"Searching Sohu for: {keywords}")
    candidates = []
    try:
        url = "https://so.tv.sohu.com/mts"
        params = {'wd': keywords}
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
        }
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        
        if resp.status_code == 200:
            pattern = r'<a href="(?P<url>//tv\.sohu\.com/v/[^"]+)"[^>]*title="(?P<title>[^"]+)"'
            matches = re.finditer(pattern, resp.text)
            
            for match in matches:
                url = match.group('url')
                if url.startswith('//'): url = 'https:' + url
                
                candidates.append({
                    'title': match.group('title'),
                    'description': '搜狐视频搜索结果',
                    'duration': 'N/A',
                    'play': 0,
                    'author': 'Sohu',
                    'url': url,
                    'provider': 'Sohu'
                })
                if len(candidates) >= limit: break
        else:
            print(f"Sohu returned status: {resp.status_code}")
            
    except Exception as e:
        print(f"Sohu Search failed: {e}")
        
    return candidates

def search_360_candidates(keywords, limit=3):
    """
    搜索360视频 (聚合源)
    """
    print(f"Searching 360 Video for: {keywords}")
    candidates = []
    try:
        url = "https://video.so.com/v"
        params = {'q': keywords}
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
        }
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        
        if resp.status_code == 200:
            links = re.findall(r'<a[^>]+href="([^"]+)"[^>]+title="([^"]+)"[^>]*>', resp.text)
            
            for link, title in links:
                if 'video.so.com/view' in link or 'v.qq.com' in link or 'iqiyi.com' in link:
                     candidates.append({
                        'title': title,
                        'description': '360视频聚合搜索',
                        'duration': 'N/A',
                        'play': 0,
                        'author': '360',
                        'url': link if link.startswith('http') else 'https:'+link,
                        'provider': '360 Video'
                    })
                if len(candidates) >= limit: break
                
    except Exception as e:
        print(f"360 Search failed: {e}")
        
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

    user_context = f"""
    User Topic: {topic.title}
    Current Level: {topic.get_current_level_display()}
    Description: {topic.description}
    Last Study Feedback: {last_log.feedback if last_log else "None"}
    """
    
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
    Analyze the following video candidates.
    Select the SINGLE BEST video that matches the user's current level and specific needs.
    
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
    优先查询缓存，缓存未命中则调用搜索+LLM，并写入缓存。
    """
    # 1. 尝试从缓存获取
    last_log = LearningLog.objects.filter(topic=topic).order_by('-created_at').first()
    keywords = f"{topic.title} {topic.get_current_level_display()} 教程"
    if last_log and last_log.feedback:
        keywords += f" {last_log.feedback[:10]}"
    
    # Check Cache
    cache = TopicRecommendationCache.objects.filter(
        topic_keyword=keywords,
        level=topic.current_level,
        created_at__gte=timezone.now() - timedelta(days=30)
    ).order_by('-created_at').first()
    
    if cache:
        print(f"Cache HIT for: {keywords}")
        return {
            'title': cache.video_title,
            'url': cache.video_url,
            'reason': cache.reason
        }
    
    print(f"Cache MISS for: {keywords}. Starting Multi-Source Search...")

    # 3. 获取候选视频 (多源并行)
    candidates = []
    
    # Source A: Bilibili API & Web
    bili = search_bilibili_candidates(keywords, limit=5)
    print(f"[Source: Bilibili] Found {len(bili)} videos")
    candidates.extend(bili)
    
    # Source B: Zhihu
    if len(candidates) < 5:
        zhihu = search_zhihu_candidates(keywords, limit=3)
        print(f"[Source: Zhihu] Found {len(zhihu)} videos")
        candidates.extend(zhihu)

    # Source C: Sohu
    if len(candidates) < 5:
        sohu = search_sohu_candidates(keywords, limit=3)
        print(f"[Source: Sohu] Found {len(sohu)} videos")
        candidates.extend(sohu)

    # Source D: 360
    if len(candidates) < 5:
        so360 = search_360_candidates(keywords, limit=3)
        print(f"[Source: 360] Found {len(so360)} videos")
        candidates.extend(so360)

    # Source E: DDG
    if len(candidates) < 3:
        ddg = search_candidates_from_ddg(keywords, limit=3)
        print(f"[Source: DDG] Found {len(ddg)} videos")
        candidates.extend(ddg)
    
    print(f"Total Candidates Collected: {len(candidates)}")

    # 4. Fallback Logic
    if not candidates:
        print("No candidates found. Trying Hardcoded Fallback...")
        # 4.1 Hardcoded Fallback
        for key, video in HARDCODED_VIDEOS.items():
            if key in topic.title.lower():
                print(f"Hardcoded Fallback HIT: {key}")
                candidates.append({
                    'title': video['title'],
                    'description': '系统精选推荐',
                    'duration': 'N/A',
                    'play': 999999,
                    'author': 'System',
                    'url': video['url'],
                    'provider': 'System Fallback'
                })
                break
        
        # 4.2 If still empty, use Blind LLM
        if not candidates:
            print("No candidates found. Using Blind LLM Fallback.")
            return call_llm_for_blind_suggestion(topic, last_log)

    # 5. 使用 LLM 选择最佳视频
    selection = call_llm_to_select(topic, last_log, candidates)
    
    # 6. 降级策略
    if not selection:
        print("LLM selection failed, falling back to rule-based.")
        selection = candidates[0]
        selection['reason'] = "根据热度为您推荐，该视频在全网搜索中排名靠前。"

    # 7. 写入缓存
    if selection:
        try:
            TopicRecommendationCache.objects.create(
                topic_keyword=keywords,
                level=topic.current_level,
                video_title=selection['title'],
                video_url=selection['url'],
                reason=selection['reason']
            )
            print("Recommendation cached successfully.")
        except Exception as e:
            print(f"Failed to cache recommendation: {e}")

    return {
        'title': selection['title'],
        'url': selection['url'],
        'reason': selection['reason']
    }

def call_llm_for_blind_suggestion(topic, last_log):
    """
    当无法搜索到视频时，让 LLM 生成纯文本建议和搜索词
    """
    api_key = getattr(settings, 'OPENAI_API_KEY', None) or os.environ.get('OPENAI_API_KEY')
    api_base = getattr(settings, 'OPENAI_API_BASE', 'https://api.openai.com/v1')
    model = getattr(settings, 'OPENAI_MODEL', 'gpt-3.5-turbo')
    
    if not api_key:
        return None
        
    user_context = f"Topic: {topic.title}, Level: {topic.get_current_level_display()}, Last Feedback: {last_log.feedback if last_log else 'None'}"
    
    prompt = f"""
    You are a tutor. The user wants to learn: {user_context}.
    We cannot find specific videos right now.
    
    Please provide:
    1. A short study advice (Chinese).
    2. A precise search query they can use on Bilibili.
    
    Return JSON:
    {{
        "advice": "...",
        "search_query": "..."
    }}
    """
    
    try:
        response = requests.post(
            f"{api_base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.5},
            timeout=15
        )
        if response.status_code == 200:
            res = response.json()['choices'][0]['message']['content']
            res = res.replace('```json', '').replace('```', '').strip()
            data = json.loads(res)
            
            return {
                'title': f"建议搜索：{data.get('search_query')}",
                'url': f"https://search.bilibili.com/all?keyword={data.get('search_query')}",
                'reason': f"暂时无法自动获取视频链接。AI 建议：{data.get('advice')}"
            }
    except Exception as e:
        print(f"Blind LLM failed: {e}")
        
    return None