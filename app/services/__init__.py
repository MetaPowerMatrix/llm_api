"""
服务初始化模块
"""
import os
import logging
from app.config import settings

logger = logging.getLogger(__name__)

def init_services():
    """初始化服务，确保必要的目录存在"""
    try:
        # 确保音频和IMU数据目录存在
        os.makedirs(settings.AUDIO_DIR, exist_ok=True)
        os.makedirs(settings.IMU_DIR, exist_ok=True)
        os.makedirs(settings.PROCESSED_DIR, exist_ok=True)

        logger.info("服务目录初始化完成")
        
        if not settings.DEEPSEEK_API_KEY:
            logger.warning("未配置DeepSeek API密钥，大模型对话功能将不可用")
        
    except Exception as e:
        logger.error(f"初始化服务目录失败: {e}")
        raise