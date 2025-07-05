from flask import Flask, request, Response
import requests
from datetime import datetime
from functools import wraps
import random
import time
import threading
import queue
import argparse
import sys
import logging

# ========================
# 全局配置
# ========================
DEBUG_MODE = False
REQUEST_INTERVAL = 15  # 默认请求间隔
request_queue = queue.Queue()
processing_thread = None

app = Flask(__name__)

# ========================
# 日志配置
# ========================
def setup_logging():
    if DEBUG_MODE:
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
    else:
        logging.basicConfig(level=logging.WARNING)

def debug_log(message):
    """调试模式下输出日志"""
    if DEBUG_MODE:
        print(f"[DEBUG] {datetime.now().strftime('%H:%M:%S')} - {message}")
        logging.debug(message)

# ========================
# 请求排队处理器
# ========================
class RequestProcessor:
    def __init__(self, interval=REQUEST_INTERVAL):
        self.interval = interval
        self.queue = queue.Queue()
        self.running = False
        self.thread = None
    
    def start(self):
        """启动请求处理线程"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._process_requests, daemon=True)
            self.thread.start()
            debug_log(f"Request processor started with interval: {self.interval}s")
    
    def stop(self):
        """停止请求处理线程"""
        self.running = False
        if self.thread:
            self.thread.join()
            debug_log("Request processor stopped")
    
    def _process_requests(self):
        """处理队列中的请求"""
        while self.running:
            try:
                if not self.queue.empty():
                    request_data = self.queue.get(timeout=1)
                    debug_log(f"Processing queued request: {request_data['id']}")
                    self._execute_request(request_data)
                    time.sleep(self.interval)
                else:
                    time.sleep(0.1)  # 短暂等待避免CPU占用过高
            except queue.Empty:
                continue
            except Exception as e:
                debug_log(f"Error processing request: {str(e)}")
    
    def _execute_request(self, request_data):
        """执行具体的请求处理"""
        try:
            result = fetch_danbooru_image(request_data['params'])
            request_data['result_callback'](result)
        except Exception as e:
            error_result = {"error": "Request processing failed", "details": str(e)}, 500
            request_data['result_callback'](error_result)
    
    def add_request(self, params, result_callback):
        """添加请求到队列"""
        request_id = f"req_{int(time.time() * 1000)}"
        request_data = {
            'id': request_id,
            'params': params,
            'result_callback': result_callback,
            'timestamp': datetime.now()
        }
        self.queue.put(request_data)
        debug_log(f"Request {request_id} added to queue. Queue size: {self.queue.qsize()}")
        return request_id

# 全局请求处理器
processor = RequestProcessor(REQUEST_INTERVAL)
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
                debug_log(f"Rate limit exceeded for {f.__name__}")
                return {"error": "Rate limit exceeded"}, 429
            calls.append(now)
            debug_log(f"Rate limit check passed for {f.__name__}. Calls: {len(calls)}/{max_calls}")
            return f(*args, **kwargs)
        return wrapped
    return decorator

# ========================
# 核心业务函数
# ========================
def fetch_danbooru_image(params):
    """从Danbooru获取图片的核心函数"""
    work_name = params.get('work_name')
    character_name = params.get('character_name')
    width = params.get('width')
    select_mode = params.get('select_mode', 'default')
    tags = params.get('tags', [])
    
    debug_log(f"Processing request: work_name={work_name}, character_name={character_name}, tags={tags}, width={width}, select_mode={select_mode}")

    # 构造标签
    danbooru_tags = []
    if work_name:
        danbooru_tags.append(f"copyright:{work_name}")
    if character_name:
        danbooru_tags.append(f"character:{character_name}")
    danbooru_tags.extend(tags)

    # 构造 Danbooru 请求参数
    api_params = {
        "search[tags_match]": " ".join(danbooru_tags),
        "limit": 1,
    }

    # 设置排序方式
    if select_mode == "random":
        api_params["search[order]"] = "random"
    elif select_mode == "score":
        api_params["search[order]"] = "score_desc"
    elif select_mode == "fav_count":
        api_params["search[order]"] = "fav_count"
    elif select_mode == "up_score":
        api_params["search[order]"] = "up_score"
    elif select_mode == "rank":
        api_params["search[order]"] = "rank"
    else:
        api_params["search[order]"] = "id_desc"

    # 宽度范围筛选
    if width:
        min_width = width - 100
        max_width = width + 100
        api_params["search[image_width]"] = f"{min_width}..{max_width}"

    # 请求头
    headers = {
        "User-Agent": "fast-danbooru-proxy/1.0",
        "Referer": "https://danbooru.donmai.us/"
    }

    # 请求 Danbooru API
    danbooru_url = "https://danbooru.donmai.us/posts.json"
    try:
        debug_log(f"Requesting Danbooru API with tags: {danbooru_tags}")
        response = requests.get(danbooru_url, params=api_params, headers=headers, timeout=10)
        
        debug_log(f"Danbooru API URL: {response.url}")
        response.raise_for_status()
        posts = response.json()
        
        if not posts:
            debug_log("No matching image found")
            return {"error": "No matching image found"}, 404
        
        post = posts[0]
        debug_log(f"Found post ID: {post.get('id', 'unknown')}")
        
    except (requests.RequestException, ValueError, IndexError) as e:
        debug_log(f"Failed to fetch from Danbooru: {str(e)}")
        return {"error": "Failed to fetch from Danbooru", "details": str(e)}, 500

    # 选择图片变体
    variants = post["media_asset"]["variants"]
    selected = None

    if width:
        candidates = [
            v for v in variants
            if width - 100 <= v["width"] <= width + 100
        ]
        if candidates:
            selected = max(candidates, key=lambda x: x["width"])
            debug_log(f"Selected variant by width match: {selected['width']}x{selected['height']}")
        else:
            selected = min(variants, key=lambda x: abs(x["width"] - width))
            debug_log(f"Selected closest variant: {selected['width']}x{selected['height']}")
    else:
        selected = next((v for v in variants if v["type"] == "sample"), variants[0])
        debug_log(f"Selected default variant: {selected['width']}x{selected['height']}")

    # 下载图片内容
    try:
        debug_log(f"Downloading image from: {selected['url']}")
        img_response = requests.get(selected["url"], headers=headers, stream=True, timeout=10)
        img_response.raise_for_status()
        debug_log(f"Image downloaded successfully, size: {len(img_response.content)} bytes")
    except requests.RequestException as e:
        debug_log(f"Failed to download image: {str(e)}")
        return {"error": "Failed to download image", "details": str(e)}, 500

    # 返回图片内容
    content_type = img_response.headers.get('Content-Type', 'image/jpeg')
    return Response(img_response.content, content_type=content_type)

# ========================
# 获取图片主函数（重构为异步队列处理）
# ========================
@app.route('/image.jpg')
@rate_limit(max_calls=10, period=60)
def get_image():
    # 提取参数
    work_name = request.args.get('work_name')
    character_name = request.args.get('character_name')
    width = request.args.get('width', type=int)
    select_mode = request.args.get('select_mode', 'default')
    
    tags = request.args.getlist('tags[]')
    # 如果只有一个元素，检查是否有逗号分割
    if len(tags) == 1 and ',' in tags[0]:
        tags = [tag.strip() for tag in tags[0].split(',') if tag.strip()]

    debug_log(f"Received request: work_name={work_name}, character_name={character_name}, tags={tags}, width={width}, select_mode={select_mode}")

    # 构造参数字典
    params = {
        'work_name': work_name,
        'character_name': character_name,
        'width': width,
        'select_mode': select_mode,
        'tags': tags
    }

    # 创建结果容器
    result_container = {'result': None, 'event': threading.Event()}
    
    def result_callback(result):
        result_container['result'] = result
        result_container['event'].set()

    # 添加请求到队列
    request_id = processor.add_request(params, result_callback)
    debug_log(f"Request {request_id} submitted to queue")

    # 等待处理结果（设置超时避免无限等待）
    if result_container['event'].wait(timeout=30):  # 30秒超时
        debug_log(f"Request {request_id} completed")
        return result_container['result']
    else:
        debug_log(f"Request {request_id} timed out")
        return {"error": "Request timeout"}, 408

# ========================
# 健康检查和状态接口
# ========================
@app.route('/health')
def health_check():
    """健康检查接口"""
    return {
        "status": "healthy",
        "queue_size": processor.queue.qsize(),
        "debug_mode": DEBUG_MODE,
        "request_interval": REQUEST_INTERVAL
    }

@app.route('/status')
def status():
    """状态查询接口"""
    return {
        "queue_size": processor.queue.qsize(),
        "debug_mode": DEBUG_MODE,
        "request_interval": REQUEST_INTERVAL,
        "processor_running": processor.running
    }

# ========================
# 命令行参数解析和启动应用
# ========================
def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='Fast Danbooru Proxy Server')
    parser.add_argument('--debug', action='store_true', 
                       help='Enable debug mode with detailed logging')
    parser.add_argument('--interval', type=float, default=REQUEST_INTERVAL,
                       help='Request processing interval in seconds (default: 0.3)')
    parser.add_argument('--host', type=str, default='127.0.0.1',
                       help='Host to bind the server (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=5000,
                       help='Port to bind the server (default: 5000)')
    return parser.parse_args()

def main():
    """主函数"""
    global DEBUG_MODE, REQUEST_INTERVAL, processor
    
    args = parse_arguments()
    
    # 设置全局配置
    DEBUG_MODE = args.debug
    REQUEST_INTERVAL = args.interval
    
    # 重新创建处理器以应用新的间隔设置
    processor = RequestProcessor(REQUEST_INTERVAL)
    
    # 配置日志
    setup_logging()
    
    debug_log(f"Starting Fast Danbooru Proxy Server")
    debug_log(f"Debug mode: {DEBUG_MODE}")
    debug_log(f"Request interval: {REQUEST_INTERVAL}s")
    debug_log(f"Server will run on {args.host}:{args.port}")
    
    # 启动请求处理器
    processor.start()
    
    try:
        # 启动Flask应用
        app.run(host=args.host, port=args.port, debug=DEBUG_MODE)
    except KeyboardInterrupt:
        debug_log("Received interrupt signal, shutting down...")
    finally:
        # 停止请求处理器
        processor.stop()
        debug_log("Server shutdown complete")

if __name__ == '__main__':
    main()