import asyncio
import os
import time
import logging
import urllib.parse
import aiohttp
import re
import json
from typing import List, Tuple, Type, Optional, Dict, Any
from src.chat.message_receive.message import MessageRecv
from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseCommand,
    ComponentInfo,
    ConfigField,
)

# 为模块级独立函数创建logger
logger = logging.getLogger("plugin.doubao_video_generator")
_utils_logger = logging.getLogger("plugin.doubao_video_generator.utils")


class ProgressBar:
    """进度条显示类"""
    
    def __init__(self, total_size: int, description: str = "下载进度", bar_length: int = 30):
        self.total_size = total_size
        self.description = description
        self.bar_length = bar_length
        self.current_size = 0
        self.last_update = 0
        self.update_interval = 0.1  # 100ms更新一次，避免过于频繁
        
    def update(self, downloaded: int):
        """更新进度"""
        self.current_size = downloaded
        current_time = time.time()
        
        # 控制更新频率，避免过于频繁的日志输出
        if current_time - self.last_update < self.update_interval:
            return
            
        self.last_update = current_time
        
        # 计算进度百分比
        if self.total_size > 0:
            percentage = (downloaded / self.total_size) * 100
        else:
            percentage = 0
            
        # 计算进度条填充长度
        filled_length = int(self.bar_length * downloaded // self.total_size) if self.total_size > 0 else 0
        
        # 构建进度条
        bar = '█' * filled_length + '░' * (self.bar_length - filled_length)
        
        # 格式化文件大小显示
        downloaded_mb = downloaded / (1024 * 1024)
        total_mb = self.total_size / (1024 * 1024) if self.total_size > 0 else 0
        
        # 输出进度条
        print(f"\r{self.description}: [{bar}] {percentage:5.1f}% ({downloaded_mb:6.1f}MB/{total_mb:6.1f}MB)", end='', flush=True)
        
    def finish(self):
        """完成进度条显示"""
        # 确保显示100%
        self.update(self.total_size)
        print()  # 换行


class DoubaoVideoInfo:
    """豆包视频信息"""
    
    def __init__(self, task_id: str, video_url: Optional[str] = None, duration: Optional[int] = None):
        self.task_id = task_id
        self.video_url = video_url
        self.duration = duration


class VideoMetadataManager:
    """视频元数据管理器"""
    
    def __init__(self, plugin_dir: str):
        self.metadata_file = os.path.join(plugin_dir, "videos", "metadata.json")
        self.videos_dir = os.path.join(plugin_dir, "videos")
        os.makedirs(self.videos_dir, exist_ok=True)
        
    def _load_metadata(self) -> List[Dict[str, Any]]:
        """加载元数据"""
        if os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载元数据失败: {str(e)}")
                return []
        return []
    
    def _save_metadata(self, metadata: List[Dict[str, Any]]):
        """保存元数据"""
        try:
            with open(self.metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存元数据失败: {str(e)}")
    
    def get_next_video_number(self) -> int:
        """获取下一个视频编号"""
        metadata = self._load_metadata()
        if not metadata:
            return 1
        return max(item["id"] for item in metadata) + 1
    
    def add_video_metadata(self, video_id: int, prompt: str, model_id: str, original_filename: str):
        """添加视频元数据"""
        metadata = self._load_metadata()
        new_item = {
            "id": video_id,
            "prompt": prompt,
            "model_id": model_id,
            "original_filename": original_filename,
            "created_at": time.time(),
            "filename": f"{video_id}.mp4"
        }
        metadata.append(new_item)
        self._save_metadata(metadata)
    
    def get_video_by_id(self, video_id: int) -> Optional[Dict[str, Any]]:
        """通过ID获取视频元数据"""
        metadata = self._load_metadata()
        for item in metadata:
            if item["id"] == video_id:
                return item
        return None
    
    def get_video_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """通过名称获取视频元数据"""
        metadata = self._load_metadata()
        for item in metadata:
            if name in item["prompt"] or name in item["original_filename"]:
                return item
        return None
    
    def get_all_videos(self) -> List[Dict[str, Any]]:
        """获取所有视频元数据"""
        metadata = self._load_metadata()
        # 按创建时间倒序排序
        return sorted(metadata, key=lambda x: x["created_at"], reverse=True)


class VideoGenerateCommand(BaseCommand):
    """视频生成命令"""
    command_name: str = "video_generate"
    command_description: str = "使用豆包API生成视频"
    command_pattern: str = r"^/video\s+(?:(?P<model_id>[\w-]+)\s+)?(?P<prompt>.+)$"
    
    async def execute(self) -> Tuple[bool, Optional[str], int]:
        """执行视频生成命令"""
        prompt = self.matched_groups.get("prompt", "").strip()
        specified_model_id = self.matched_groups.get("model_id")
        if not prompt:
            await self.send_text("请输入视频描述，例如：/video 一只可爱的小猫在玩球 或 /video doubao-seedance-1-5-pro-251215 一只可爱的小猫在玩球")
            return True, "缺少视频描述", 1
        
        # 验证配置
        config_validation = self._validate_config()
        if not config_validation["valid"]:
            await self.send_text(f"配置错误: {'; '.join(config_validation['errors'])}")
            return True, "配置错误", 1
        
        # 获取配置
        api_key = self.get_config("api.api_key", "")
        api_base = self.get_config("api.api_base", "https://ark.cn-beijing.volces.com")
        # 如果命令中指定了模型，则使用指定的模型，否则使用配置文件中的默认模型
        model_id = specified_model_id or self.get_config("api.model_id", "doubao-seedance-1-0-pro-250528")
        max_wait_time = int(self.get_config("settings.max_wait_time", 600))
        poll_interval = int(self.get_config("settings.poll_interval", 30))
        
        if not api_key:
            await self.send_text("请先配置API密钥")
            return True, "未配置API密钥", 1
        
        # 记录日志
        logger.info(f"开始生成视频，prompt: {prompt[:50]}..., model: {model_id}")
        await self.send_text(f"🎬 正在生成视频：{prompt}...")
        await self.send_text(f"🔧 使用模型：{model_id}")
        
        # 创建视频生成任务
        task_id = await self._create_video_task(api_key, api_base, model_id, prompt)
        if not task_id:
            await self.send_text("创建视频生成任务失败，请检查配置或稍后重试")
            return True, "创建视频任务失败", 1
        
        await self.send_text(f"🔄 视频生成中，任务ID：{task_id}，请稍候...")
        
        # 轮询任务状态
        video_url = await self._poll_task_status(api_key, api_base, task_id, max_wait_time, poll_interval)
        if not video_url:
            await self.send_text("视频生成失败或超时，请稍后重试")
            return True, "视频生成失败", 1
        
        # 发送视频链接
        await self._send_video_result(video_url, prompt, model_id)
        
        logger.info(f"视频生成完成，task_id: {task_id}")
        return True, "视频生成完成", 1
    
    def _validate_config(self) -> Dict[str, Any]:
        """验证配置参数的有效性"""
        validation_result = {
            "valid": True,
            "warnings": [],
            "errors": [],
            "recommendations": []
        }
        
        # 检查API密钥
        api_key = self.get_config("api.api_key", "")
        if not api_key:
            validation_result["warnings"].append("未配置API密钥，将无法生成视频")
        else:
            if len(api_key) < 10:
                validation_result["errors"].append("API密钥长度异常，可能配置错误")
                validation_result["valid"] = False
        
        # 检查API基础地址
        api_base = self.get_config("api.api_base", "")
        if api_base:
            if not api_base.startswith("http"):
                validation_result["errors"].append("API基础地址格式错误，必须以http或https开头")
                validation_result["valid"] = False
        
        # 检查模型ID
        model_id = self.get_config("api.model_id", "")
        if not model_id:
            validation_result["errors"].append("未配置模型ID")
            validation_result["valid"] = False
        
        # 检查超时配置
        max_wait_time = int(self.get_config("settings.max_wait_time", 600))
        if max_wait_time < 60:
            validation_result["warnings"].append("最大等待时间过短，可能导致视频生成未完成就超时")
        
        # 记录验证结果
        if validation_result["warnings"]:
            logger.debug(f"配置警告: {validation_result['warnings']}")
        if validation_result["errors"]:
            logger.error(f"配置错误: {validation_result['errors']}")
        
        return validation_result
    
    async def _create_video_task(self, api_key: str, api_base: str, model_id: str, prompt: str) -> Optional[str]:
        """创建视频生成任务"""
        try:
            # 构建视频生成参数
            video_params = {
                "ratio": self.get_config("video.ratio", "16:9"),
                "duration": int(self.get_config("video.duration", 5)),
                "watermark": bool(self.get_config("video.watermark", False)),
                "return_last_frame": bool(self.get_config("video.return_last_frame", False)),
                "generate_audio": bool(self.get_config("video.generate_audio", True)),
                "draft": bool(self.get_config("video.draft", False))
            }
            
            # 构建请求体
            payload = {
                "model": model_id,
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    }
                ],
                "ratio": video_params["ratio"],
                "duration": video_params["duration"],
                "watermark": video_params["watermark"],
                "return_last_frame": video_params["return_last_frame"],
                "generate_audio": video_params["generate_audio"],
                "draft": video_params["draft"]
            }
            
            # 构建请求头
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            
            # 构建请求URL
            # 确保api_base不包含尾部斜杠
            base = api_base.rstrip('/')
            # 如果api_base已经包含/api/v3，则直接使用，否则添加
            if '/api/v3' in base:
                url = f"{base}/contents/generations/tasks"
            else:
                url = f"{base}/api/v3/contents/generations/tasks"
            
            # 发送HTTP请求
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        resp_data = await response.json()
                        task_id = resp_data.get("id")
                        logger.info(f"视频生成任务创建成功，task_id: {task_id}")
                        return task_id
                    else:
                        error_text = await response.text()
                        logger.error(f"创建视频任务失败，状态码: {response.status}, 错误信息: {error_text}")
        except Exception as e:
            logger.error(f"创建视频任务失败: {str(e)}", exc_info=True)
        return None
    
    async def _poll_task_status(self, api_key: str, api_base: str, task_id: str, max_wait_time: int, poll_interval: int) -> Optional[str]:
        """轮询任务状态"""
        start_time = time.time()
        
        logger.info(f"开始轮询任务状态，task_id: {task_id}, max_wait_time: {max_wait_time}s, poll_interval: {poll_interval}s")
        
        while time.time() - start_time < max_wait_time:
            await asyncio.sleep(poll_interval)  # 按配置的间隔查询
            
            try:
                # 构建请求头
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}"
                }
                
                # 构建请求URL
                # 确保api_base不包含尾部斜杠
                base = api_base.rstrip('/')
                # 如果api_base已经包含/api/v3，则直接使用，否则添加
                if '/api/v3' in base:
                    url = f"{base}/contents/generations/tasks/{task_id}"
                else:
                    url = f"{base}/api/v3/contents/generations/tasks/{task_id}"
                
                # 发送HTTP请求
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            resp_data = await response.json()
                            status = resp_data.get("status")
                            
                            if status == "succeeded":
                                # 获取视频下载链接
                                # 根据API响应示例，视频URL在content.video_url字段中
                                video_url = resp_data.get("content", {}).get("video_url") or \
                                            resp_data.get("content", {}).get("url") or \
                                            resp_data.get("content", {}).get("download_url") or \
                                            resp_data.get("video_url") or \
                                            resp_data.get("url") or \
                                            resp_data.get("download_url")
                                logger.info(f"视频生成成功，task_id: {task_id}, video_url: {video_url}")
                                # 记录完整的响应数据，帮助调试
                                logger.debug(f"API响应数据: {resp_data}")
                                # 确保返回的视频URL不为空
                                if video_url:
                                    return video_url
                                else:
                                    logger.error(f"视频生成成功但未返回视频URL, task_id: {task_id}")
                                    return None
                            elif status == "failed":
                                error_msg = resp_data.get("error", {}).get("message", "未知错误")
                                logger.error(f"视频生成失败, task_id: {task_id}, error: {error_msg}")
                                return None
                            elif status in ["queued", "running"]:
                                # 只在控制台显示进度，不发送消息避免打扰
                                elapsed_time = int(time.time() - start_time)
                                logger.info(f"任务状态: {status}, task_id: {task_id}, 已耗时: {elapsed_time}s")
                                continue
                            else:
                                logger.error(f"未知任务状态: {status}, task_id: {task_id}")
                                return None
                        else:
                            error_text = await response.text()
                            logger.error(f"查询任务状态失败，状态码: {response.status}, 错误信息: {error_text}")
            except Exception as e:
                logger.error(f"查询任务状态异常, task_id: {task_id}, error: {str(e)}")
            
            # 检查是否超时
            if time.time() - start_time >= max_wait_time:
                logger.error(f"视频生成超时, task_id: {task_id}")
                return None
        
        return None
    
    async def _send_video_result(self, video_url: str, prompt: str, model_id: str):
        """发送视频生成结果"""
        try:
            # 直接下载并发送视频
            await self.send_text("📥 正在下载视频...")
            video_path = await self._auto_download_video(video_url, prompt, model_id)
            
            if video_path:
                await self.send_text("📤 正在发送视频...")
                # 尝试通过Napcat API发送视频
                napcat_sent = await self._send_video_via_napcat(video_path)
                video_sent = napcat_sent
                
                # 如果Napcat发送失败，尝试其他方法
                if not napcat_sent:
                    # 尝试直接发送视频（内置方法）
                    if hasattr(self, 'send_video'):
                        await self.send_video(video_path)
                        await self.send_text("✅ 视频发送成功！")
                        video_sent = True
                    # 尝试使用send_file方法（可能的方法名）
                    elif hasattr(self, 'send_file'):
                        await self.send_file(video_path)
                        await self.send_text("✅ 视频发送成功！")
                        video_sent = True
                    # 尝试使用upload_video方法（可能的方法名）
                    elif hasattr(self, 'upload_video'):
                        await self.upload_video(video_path)
                        await self.send_text("✅ 视频发送成功！")
                        video_sent = True
                elif napcat_sent:
                    await self.send_text("✅ 视频发送成功！")
                
                # 如果都不支持，回退到发送链接
                if not video_sent:
                    await self.send_text(f"🎬 视频生成完成！下载链接：{video_url}")
                
                # 根据配置决定是否保留视频文件
                keep_files = self.get_config("settings.keep_video_files", True)
                if not keep_files and os.path.exists(video_path):
                    os.remove(video_path)
                    logger.debug(f"已删除视频文件: {video_path}")
                elif keep_files:
                    logger.debug(f"已保留视频文件: {video_path}")
            else:
                # 如果下载失败，发送链接
                await self.send_text(f"🎬 视频生成完成！下载链接：{video_url}")
                logger.error("视频下载失败，回退到发送链接")
                
        except Exception as e:
            logger.error(f"发送视频异常: {str(e)}")
            # 发送失败时回退到发送链接
            await self.send_text(f"🎬 视频生成完成！下载链接：{video_url}")
            await self.send_text("发送视频失败，已发送下载链接")
    
    async def _auto_download_video(self, video_url: str, prompt: str, model_id: str) -> Optional[str]:
        """自动下载视频到本地"""
        try:
            import aiohttp
            
            # 获取插件目录
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            
            # 初始化元数据管理器
            metadata_manager = VideoMetadataManager(plugin_dir)
            
            # 生成原始文件名（用于记录）
            timestamp = int(time.time())
            safe_prompt = re.sub(r'[\\/:*?"<>|]', '_', prompt[:20]) if prompt else "video"
            original_filename = f"豆包_{safe_prompt}_{timestamp}.mp4"
            
            # 获取下一个视频编号
            video_id = metadata_manager.get_next_video_number()
            filename = f"{video_id}.mp4"
            
            # 获取下载目录
            download_dir = self.get_config("settings.download_dir", "")
            if not download_dir:
                download_dir = metadata_manager.videos_dir
            
            filepath = os.path.join(download_dir, filename)
            
            logger.info(f"开始下载视频，URL: {video_url[:50]}..., 保存到: {filepath}")
            
            # 下载视频
            async with aiohttp.ClientSession() as session:
                async with session.get(video_url) as response:
                    if response.status == 200:
                        total_size = int(response.headers.get("Content-Length", 0))
                        progress_bar = ProgressBar(total_size, description="视频下载进度")
                        
                        with open(filepath, "wb") as f:
                            downloaded = 0
                            async for chunk in response.content.iter_chunked(8192):
                                f.write(chunk)
                                downloaded += len(chunk)
                                progress_bar.update(downloaded)
                        
                        progress_bar.finish()
                        logger.info(f"视频下载完成，保存到: {filepath}")
                        
                        # 保存元数据
                        metadata_manager.add_video_metadata(video_id, prompt, model_id, original_filename)
                        
                        return filepath
                    else:
                        error_text = await response.text()
                        logger.error(f"下载视频失败，状态码: {response.status}, 错误信息: {error_text}")
                        return None
        except Exception as e:
            logger.error(f"自动下载视频失败: {str(e)}", exc_info=True)
            return None
    
    async def _send_video_via_napcat(self, video_path: str) -> bool:
        """通过Napcat API发送视频
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            是否发送成功
        """
        try:
            # 获取配置的端口和token
            port = self.get_config("napcat.port", 8090)
            token = self.get_config("napcat.token", "")
            
            # 检查文件是否存在
            if not os.path.exists(video_path):
                logger.error(f"视频文件不存在: {video_path}")
                return False
            
            # 构造本地文件路径，使用file://协议
            file_uri = f"file://{video_path}"
            
            logger.debug(f"Napcat video send - file path: {video_path}")
            logger.debug(f"Napcat video send - send URI: {file_uri}")
            
            # 从message对象获取聊天上下文
            chat_id = None
            is_group = False
            
            # 检查是否有message属性
            if not hasattr(self, 'message'):
                logger.error("缺少message属性，无法获取聊天上下文")
                return False
            
            message = self.message
            
            # 从message_info获取群聊或私聊信息
            if hasattr(message, 'message_info'):
                message_info = message.message_info
                
                # 检查是否为群聊
                if hasattr(message_info, 'group_info') and message_info.group_info:
                    group_info = message_info.group_info
                    if hasattr(group_info, 'group_id') and group_info.group_id:
                        chat_id = str(group_info.group_id)
                        is_group = True
                
                # 如果不是群聊，获取用户ID
                if not chat_id and hasattr(message_info, 'user_info') and message_info.user_info:
                    user_info = message_info.user_info
                    if hasattr(user_info, 'user_id') and user_info.user_id:
                        chat_id = str(user_info.user_id)
                        is_group = False
            
            # 如果还是无法获取，从chat_stream获取
            if not chat_id and hasattr(message, 'chat_stream') and message.chat_stream:
                chat_stream = message.chat_stream
                if hasattr(chat_stream, 'group_info') and chat_stream.group_info:
                    group_info = chat_stream.group_info
                    if hasattr(group_info, 'group_id') and group_info.group_id:
                        chat_id = str(group_info.group_id)
                        is_group = True
                elif hasattr(chat_stream, 'user_info') and chat_stream.user_info:
                    user_info = chat_stream.user_info
                    if hasattr(user_info, 'user_id') and user_info.user_id:
                        chat_id = str(user_info.user_id)
                        is_group = False
            
            if not chat_id:
                logger.error("无法确定聊天ID，无法发送视频")
                return False
            
            # 构造请求
            if is_group:
                api_url = f"http://localhost:{port}/send_group_msg"
                request_data = {
                    "group_id": chat_id,
                    "message": [
                        {
                            "type": "video",
                            "data": {
                                "file": file_uri
                            }
                        }
                    ]
                }
            else:
                api_url = f"http://localhost:{port}/send_private_msg"
                request_data = {
                    "user_id": chat_id,
                    "message": [
                        {
                            "type": "video",
                            "data": {
                                "file": file_uri
                            }
                        }
                    ]
                }
            
            # 构造请求头
            headers = {
                "Content-Type": "application/json"
            }
            
            # 添加token到请求头和请求体
            if token:
                request_data["token"] = token
                headers["Authorization"] = f"Bearer {token}"
            
            logger.debug(f"Sending video via Napcat API: {api_url}")
            logger.debug(f"Request headers: {headers}")
            logger.debug(f"Request data: {request_data}")
            
            # 发送API请求
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=request_data, headers=headers, timeout=300) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.debug(f"Video sent successfully via Napcat: {result}")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to send video via Napcat: HTTP {response.status}, {error_text}")
                        logger.debug(f"Response headers: {response.headers}")
                        return False
                        
        except asyncio.TimeoutError:
            logger.error("Video sending via Napcat timeout")
            return False
        except Exception as e:
            logger.error(f"Video sending via Napcat error: {e}")
            return False


class VideoListCommand(BaseCommand):
    """视频列表命令"""
    command_name: str = "video_list"
    command_description: str = "查看所有生成的豆包视频"
    command_pattern: str = r"^/豆包视频列表$"
    
    async def execute(self) -> Tuple[bool, Optional[str], int]:
        """执行视频列表命令"""
        try:
            # 获取插件目录
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            
            # 初始化元数据管理器
            metadata_manager = VideoMetadataManager(plugin_dir)
            
            # 获取所有视频元数据
            videos = metadata_manager.get_all_videos()
            
            if not videos:
                await self.send_text("📁 还没有生成任何豆包视频")
                return True, "没有视频文件", 1
            
            # 生成视频列表
            reply = "📋 豆包视频列表\n"
            reply += "列表: "
            
            # 构建视频列表，格式：1.mp4，一只猫在草地里玩耍
            for video in videos:
                reply += f"{video['filename']}，{video['prompt']}，"
            
            # 移除最后一个逗号
            if reply.endswith("，"):
                reply = reply[:-1]
            
            await self.send_text(reply)
            return True, "显示视频列表", 1
            
        except Exception as e:
            logger.error(f"获取视频列表失败: {str(e)}")
            await self.send_text("📛 获取视频列表失败，请稍后重试")
            return True, "获取视频列表失败", 1


class ModelListCommand(BaseCommand):
    """模型列表命令"""
    command_name: str = "model_list"
    command_description: str = "查看支持的豆包视频生成模型"
    command_pattern: str = r"^/豆包模型列表$"
    
    async def execute(self) -> Tuple[bool, Optional[str], int]:
        """执行模型列表命令"""
        try:
            # 支持的模型列表
            supported_models = [
                "doubao-seedance-1-0-pro-250528",
                "doubao-seedance-1-5-pro-251215",
                "doubao-seedance-1-0-lite-i2v-250428"
            ]
            
            # 生成模型列表
            reply = "📋 支持的豆包视频生成模型\n"
            reply += "列表: "
            for i, model in enumerate(supported_models, 1):
                reply += f"{i}. {model}，"
            
            # 移除最后一个逗号
            if reply.endswith("，"):
                reply = reply[:-1]
            
            await self.send_text(reply)
            return True, "显示模型列表", 1
            
        except Exception as e:
            logger.error(f"获取模型列表失败: {str(e)}")
            await self.send_text("📛 获取模型列表失败，请稍后重试")
            return True, "获取模型列表失败", 1


class ModelSelectCommand(BaseCommand):
    """模型选择命令"""
    command_name: str = "model_select"
    command_description: str = "选择要使用的豆包视频生成模型"
    command_pattern: str = r"^/选择模型\s+(?P<model_index>\d+)$"
    
    async def execute(self) -> Tuple[bool, Optional[str], int]:
        """执行模型选择命令"""
        try:
            model_index = self.matched_groups.get("model_index", "").strip()
            if not model_index:
                await self.send_text("❌ 请输入要选择的模型编号，例如：/选择模型 1")
                return True, "缺少模型编号", 1
            
            # 支持的模型列表
            supported_models = [
                "doubao-seedance-1-0-pro-250528",
                "doubao-seedance-1-5-pro-251215",
                "doubao-seedance-1-0-lite-i2v-250428"
            ]
            
            # 解析模型索引
            try:
                index = int(model_index) - 1  # 转换为0-based索引
                if 0 <= index < len(supported_models):
                    selected_model = supported_models[index]
                    
                    # 获取插件实例，修改配置并保存
                    try:
                        from src.plugin_system.core.plugin_manager import plugin_manager
                        
                        # 获取插件实例
                        plugin_instance = plugin_manager.get_plugin_instance("doubao_video_generator")
                        if plugin_instance:
                            # 修改插件配置
                            if "api" not in plugin_instance.config:
                                plugin_instance.config["api"] = {}
                            plugin_instance.config["api"]["model_id"] = selected_model
                            
                            # 保存配置到文件
                            config_file_path = os.path.join(plugin_instance.plugin_dir, plugin_instance.config_file_name)
                            plugin_instance._save_config_to_file(plugin_instance.config, config_file_path)
                            
                            await self.send_text(f"✅ 已选择模型: {selected_model}")
                            await self.send_text(f"✅ 配置已自动更新！")
                        else:
                            # 如果无法获取插件实例，提示用户手动修改
                            await self.send_text(f"✅ 已选择模型: {selected_model}")
                            await self.send_text(f"请手动修改配置文件中的model_id为: {selected_model}")
                            await self.send_text(f"配置文件位置: plugins/doubao_video_generator/config.toml")
                    except Exception as e:
                        logger.error(f"自动更新配置失败: {str(e)}")
                        # 失败时回退到手动修改提示
                        await self.send_text(f"✅ 已选择模型: {selected_model}")
                        await self.send_text(f"自动更新配置失败，请手动修改配置文件中的model_id为: {selected_model}")
                        await self.send_text(f"配置文件位置: plugins/doubao_video_generator/config.toml")
                    
                    return True, f"选择模型: {selected_model}", 1
                else:
                    await self.send_text(f"❌ 无效的模型编号，支持的范围是1-{len(supported_models)}")
                    return True, "无效的模型编号", 1
            except ValueError:
                await self.send_text(f"❌ 请输入有效的数字编号，支持的范围是1-{len(supported_models)}")
                return True, "无效的模型编号", 1
            
        except Exception as e:
            logger.error(f"选择模型失败: {str(e)}")
            await self.send_text("📛 选择模型失败，请稍后重试")
            return True, "选择模型失败", 1


class VideoPlayCommand(BaseCommand):
    """播放视频命令"""
    command_name: str = "video_play"
    command_description: str = "播放指定的豆包视频"
    command_pattern: str = r"^/播放豆包\s*(?P<video_identifier>.+)?$"
    
    async def execute(self) -> Tuple[bool, Optional[str], int]:
        """执行播放视频命令"""
        try:
            video_identifier = self.matched_groups.get("video_identifier", "").strip()
            if not video_identifier:
                await self.send_text("❌ 请输入要播放的视频编号或名称，例如：/播放豆包 1 或 /播放豆包 一只猫在草地里玩耍")
                return True, "缺少视频标识符", 1
            
            # 获取插件目录
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            
            # 初始化元数据管理器
            metadata_manager = VideoMetadataManager(plugin_dir)
            
            # 确定videos目录
            videos_dir = metadata_manager.videos_dir
            
            # 查找匹配的视频
            video_metadata = None
            
            # 尝试将标识符解析为数字ID
            try:
                video_id = int(video_identifier)
                video_metadata = metadata_manager.get_video_by_id(video_id)
            except ValueError:
                # 如果不是数字，按名称查找
                video_metadata = metadata_manager.get_video_by_name(video_identifier)
            
            if not video_metadata:
                await self.send_text(f"❌ 未找到视频: '{video_identifier}'")
                return True, "未找到匹配视频", 1
            
            # 获取视频文件路径
            file_path = os.path.join(videos_dir, video_metadata["filename"])
            
            # 检查文件是否存在
            if not os.path.exists(file_path):
                await self.send_text(f"❌ 视频文件不存在: {video_metadata['filename']}")
                return True, "视频文件不存在", 1
            
            await self.send_text(f"📤 正在发送视频: {video_metadata['filename']} - {video_metadata['prompt']}")
            
            # 尝试发送视频
            video_sent = False
            
            # 尝试通过Napcat API发送视频
            napcat_sent = await self._send_video_via_napcat(file_path)
            
            # 如果Napcat发送失败，尝试其他方法
            if not napcat_sent:
                # 尝试直接发送视频（内置方法）
                if hasattr(self, 'send_video'):
                    await self.send_video(file_path)
                    await self.send_text("✅ 视频发送成功！")
                    video_sent = True
                # 尝试使用send_file方法（可能的方法名）
                elif hasattr(self, 'send_file'):
                    await self.send_file(file_path)
                    await self.send_text("✅ 视频发送成功！")
                    video_sent = True
                # 尝试使用upload_video方法（可能的方法名）
                elif hasattr(self, 'upload_video'):
                    await self.upload_video(file_path)
                    await self.send_text("✅ 视频发送成功！")
                    video_sent = True
            elif napcat_sent:
                await self.send_text("✅ 视频发送成功！")
                video_sent = True
            
            if not video_sent:
                await self.send_text(f"📁 视频文件路径：{file_path}")
                await self.send_text("❌ 无法直接发送视频，请手动查看")
            
            return True, "播放视频", 1
            
        except Exception as e:
            logger.error(f"播放视频失败: {str(e)}")
            await self.send_text("📛 播放视频失败，请稍后重试")
            return True, "播放视频失败", 1
    
    async def _send_video_via_napcat(self, video_path: str) -> bool:
        """通过Napcat API发送视频
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            是否发送成功
        """
        try:
            # 获取配置的端口和token
            port = self.get_config("napcat.port", 8090)
            token = self.get_config("napcat.token", "")
            
            # 检查文件是否存在
            if not os.path.exists(video_path):
                logger.error(f"视频文件不存在: {video_path}")
                return False
            
            # 构造本地文件路径，使用file://协议
            file_uri = f"file://{video_path}"
            
            logger.debug(f"Napcat video send - file path: {video_path}")
            logger.debug(f"Napcat video send - send URI: {file_uri}")
            
            # 从message对象获取聊天上下文
            chat_id = None
            is_group = False
            
            # 检查是否有message属性
            if not hasattr(self, 'message'):
                logger.error("缺少message属性，无法获取聊天上下文")
                return False
            
            message = self.message
            
            # 从message_info获取群聊或私聊信息
            if hasattr(message, 'message_info'):
                message_info = message.message_info
                
                # 检查是否为群聊
                if hasattr(message_info, 'group_info') and message_info.group_info:
                    group_info = message_info.group_info
                    if hasattr(group_info, 'group_id') and group_info.group_id:
                        chat_id = str(group_info.group_id)
                        is_group = True
                
                # 如果不是群聊，获取用户ID
                if not chat_id and hasattr(message_info, 'user_info') and message_info.user_info:
                    user_info = message_info.user_info
                    if hasattr(user_info, 'user_id') and user_info.user_id:
                        chat_id = str(user_info.user_id)
                        is_group = False
            
            # 如果还是无法获取，从chat_stream获取
            if not chat_id and hasattr(message, 'chat_stream') and message.chat_stream:
                chat_stream = message.chat_stream
                if hasattr(chat_stream, 'group_info') and chat_stream.group_info:
                    group_info = chat_stream.group_info
                    if hasattr(group_info, 'group_id') and group_info.group_id:
                        chat_id = str(group_info.group_id)
                        is_group = True
                elif hasattr(chat_stream, 'user_info') and chat_stream.user_info:
                    user_info = chat_stream.user_info
                    if hasattr(user_info, 'user_id') and user_info.user_id:
                        chat_id = str(user_info.user_id)
                        is_group = False
            
            if not chat_id:
                logger.error("无法确定聊天ID，无法发送视频")
                return False
            
            # 构造请求
            if is_group:
                api_url = f"http://localhost:{port}/send_group_msg"
                request_data = {
                    "group_id": chat_id,
                    "message": [
                        {
                            "type": "video",
                            "data": {
                                "file": file_uri
                            }
                        }
                    ]
                }
            else:
                api_url = f"http://localhost:{port}/send_private_msg"
                request_data = {
                    "user_id": chat_id,
                    "message": [
                        {
                            "type": "video",
                            "data": {
                                "file": file_uri
                            }
                        }
                    ]
                }
            
            # 构造请求头
            headers = {
                "Content-Type": "application/json"
            }
            
            # 添加token到请求头和请求体
            if token:
                request_data["token"] = token
                headers["Authorization"] = f"Bearer {token}"
            
            logger.debug(f"Sending video via Napcat API: {api_url}")
            logger.debug(f"Request headers: {headers}")
            logger.debug(f"Request data: {request_data}")
            
            # 发送API请求
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=request_data, headers=headers, timeout=300) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.debug(f"Video sent successfully via Napcat: {result}")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to send video via Napcat: HTTP {response.status}, {error_text}")
                        logger.debug(f"Response headers: {response.headers}")
                        return False
                        
        except asyncio.TimeoutError:
            logger.error("Video sending via Napcat timeout")
            return False
        except Exception as e:
            logger.error(f"Video sending via Napcat error: {e}")
            return False


@register_plugin
class DoubaoVideoHttpPlugin(BasePlugin):
    # 插件基本信息
    plugin_name = "doubao_video_generator"
    plugin_description = "使用豆包API生成视频，支持多种视频参数配置"
    plugin_author = "MaiBot"
    plugin_version = "2.0.0"
    enable_plugin = True
    dependencies: List[str] = []
    python_dependencies: List[str] = []
    config_file_name = "config.toml"
    
    # 配置schema
    config_schema = {
        "api": {
            "api_key": ConfigField(
                description="豆包API密钥，从火山方舟控制台获取",
                type="string",
                default="",
                required=True
            ),
            "api_base": ConfigField(
                description="API基础地址，默认火山方舟北京区域",
                type="string",
                default="https://ark.cn-beijing.volces.com/api/v3"
            ),
            "model_id": ConfigField(
                description="视频生成模型ID",
                type="string",
                default="doubao-seedance-1-0-pro-250528"
            )
        },
        "video": {
            "ratio": ConfigField(
                description="视频宽高比，可选值：16:9, 4:3, 1:1, 9:16, 3:4, adaptive",
                type="string",
                default="16:9"
            ),
            "duration": ConfigField(
                description="视频时长（秒），不同模型支持的范围不同",
                type="integer",
                default=5
            ),
            "watermark": ConfigField(
                description="是否添加水印",
                type="boolean",
                default=False
            ),
            "return_last_frame": ConfigField(
                description="是否返回视频尾帧图像",
                type="boolean",
                default=False
            ),
            "generate_audio": ConfigField(
                description="是否生成音频",
                type="boolean",
                default=True
            ),
            "draft": ConfigField(
                description="是否生成样片（快速预览）",
                type="boolean",
                default=False
            )
        },
        "settings": {
            "max_wait_time": ConfigField(
                description="最大等待时间（秒）",
                type="integer",
                default=600
            ),
            "poll_interval": ConfigField(
                description="状态查询间隔（秒）",
                type="integer",
                default=30
            ),
            "auto_download": ConfigField(
                description="是否自动下载视频到本地",
                type="boolean",
                default=True
            ),
            "download_dir": ConfigField(
                description="视频下载目录",
                type="string",
                default=""
            ),
            "keep_video_files": ConfigField(
                description="是否保留下载的视频文件",
                type="boolean",
                default=True
            )
        },
        "napcat": {
            "port": ConfigField(
                description="Napcat API端口",
                type="integer",
                default=8090
            ),
            "token": ConfigField(
                description="Napcat API Token",
                type="string",
                default="my_napcat_token_123"
            )
        }
    }
    
    def __init__(self, plugin_dir: str):
        super().__init__(plugin_dir)
        logger.info("DoubaoVideoHttpPlugin 已初始化")
    
    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """获取插件包含的组件列表"""
        return [
            (VideoGenerateCommand.get_command_info(), VideoGenerateCommand),
            (VideoListCommand.get_command_info(), VideoListCommand),
            (VideoPlayCommand.get_command_info(), VideoPlayCommand),
            (ModelListCommand.get_command_info(), ModelListCommand),
            (ModelSelectCommand.get_command_info(), ModelSelectCommand)
        ]
    
    async def on_enable(self):
        """插件启用时执行"""
        logger.info("DoubaoVideoHttpPlugin 已启用")
    
    async def on_disable(self):
        """插件禁用时执行"""
        logger.info("DoubaoVideoHttpPlugin 已禁用")
