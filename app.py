from flask import Flask, request, Response
import requests
from datetime import datetime
from functools import wraps
import random

app = Flask(__name__)

# ========================
# 限流装饰器
# ========================
def rate_limit(max_calls=200, period=10):
    def decorator(f):
        calls = []
        @wraps(f)
        def wrapped(*args, **kwargs):
            nonlocal calls
            now = datetime.now().timestamp()
            calls[:] = [t for t in calls if t > now - period]
            if len(calls) >= max_calls:
                return {"error": "Rate limit exceeded"}, 429
            calls.append(now)
            return f(*args, **kwargs)
        return wrapped
    return decorator

# ========================
# 获取图片主函数
# ========================
@app.route('/image.jpg')
@rate_limit(max_calls=10, period=60)
def get_image():
    # 提取参数
    work_name = request.args.get('work_name')
    character_name = request.args.get('character_name')
    width = request.args.get('width', type=int)
    select_mode = request.args.get('select_mode', 'default')  # 支持 default / random / score

    tags = request.args.getlist('tags[]')
    # 如果只有一个元素，那么检查是否有逗号分割，我们在内部展开
    if len(tags) == 1 and ',' in tags[0]:
        tags = [tag.strip() for tag in tags[0].split(',') if tag.strip()]

    print(f"Received request: work_name={work_name}, character_name={character_name}, tags={tags}, width={width}, select_mode={select_mode}")

    # 构造标签
    danbooru_tags = []
    if work_name:
        danbooru_tags.append(f"copyright:{work_name}")
    if character_name:
        danbooru_tags.append(f"character:{character_name}")
    danbooru_tags.extend(tags)

    # 构造 Danbooru 请求参数
    params = {
        "search[tags_match]": " ".join(danbooru_tags),
        "limit": 1,
    }

    # 设置排序方式
    if select_mode == "random":
        params["search[order]"] = "random"
    elif select_mode == "score":
        params["search[order]"] = "score_desc"  # 按评分降序排列
    elif select_mode == "fav_count":
        params["search[order]"] = "fav_count" 
    elif select_mode == "up_score":
        params["search[order]"] = "up_score" 
    elif select_mode == "rank":
        params["search[order]"] = "rank"
    else:
        params["search[order]"] = "id_desc"  # 默认按ID降序（即最新）

    # 宽度范围筛选
    if width:
        min_width = width - 100
        max_width = width + 100
        params["search[image_width]"] = f"{min_width}..{max_width}"

    # 请求头
    headers = {
        "User-Agent": "fast-danbooru-proxy/1.0",
        "Referer": "https://danbooru.donmai.us/" 
    }

    # 请求 Danbooru API
    danbooru_url = "https://danbooru.donmai.us/posts.json" 
    try:
        response = requests.get(danbooru_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        posts = response.json()
        if not posts:
            return {"error": "No matching image found"}, 404
        post = posts[0]
    except (requests.RequestException, ValueError, IndexError) as e:
        return {"error": "Failed to fetch from Danbooru", "details": str(e)}, 500

    # 选择图片变体（支持宽度匹配）
    variants = post["media_asset"]["variants"]
    selected = None

    if width:
        candidates = [
            v for v in variants
            if width - 100 <= v["width"] <= width + 100
        ]
        if candidates:
            selected = max(candidates, key=lambda x: x["width"])
        else:
            selected = min(variants, key=lambda x: abs(x["width"] - width))
    else:
        selected = next((v for v in variants if v["type"] == "sample"), variants[0])

    # 下载图片内容
    try:
        img_response = requests.get(selected["url"], headers=headers, stream=True, timeout=10)
        img_response.raise_for_status()
    except requests.RequestException as e:
        return {"error": "Failed to download image", "details": str(e)}, 500

    # 返回图片内容
    content_type = img_response.headers.get('Content-Type', 'image/jpeg')
    return Response(img_response.content, content_type=content_type)

# ========================
# 启动应用
# ========================
if __name__ == '__main__':
    app.run(debug=True)