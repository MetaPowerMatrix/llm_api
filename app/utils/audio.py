import os
import wave
import random
import logging

logger = logging.getLogger(__name__)

async def save_raw_to_wav(raw_data, wav_file_path=None):
    """将原始PCM数据保存为WAV文件"""
    if wav_file_path is None:
        # 创建临时文件目录
        temp_dir = os.environ.get("TEMP_AUDIO_DIR", "/tmp/secretgarden")
        os.makedirs(temp_dir, exist_ok=True)
        wav_file_path = f"{temp_dir}/temp_{id(raw_data)}.wav"
        
    try:
        with wave.open(wav_file_path, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(raw_data)
        return wav_file_path
    except Exception as e:
        logger.error(f"保存WAV文件失败: {str(e)}")
        return None

async def get_touch_audio_data(amount: float = None, touch_dir: str = "/data/app/audio/touch"):
    """
    获取触摸事件音频数据，从指定目录中随机选择一个WAV文件
    
    参数:
        amount: 触摸压力值，可以用于选择不同的音频（目前未使用）
        touch_dir: 触摸音频文件目录
        
    返回:
        bytes: 音频数据，如果出错则返回None
    """
    try:
        # 检查目录是否存在
        if not os.path.exists(touch_dir):
            logger.error(f"触摸音频目录不存在: {touch_dir}")
            return None
            
        touch_files = [f for f in os.listdir(touch_dir) if f.lower().endswith('.wav')]
        if not touch_files:
            logger.error(f"触摸音频目录中没有WAV文件: {touch_dir}")
            return None
            
        # 随机选择一个音频文件
        random_file = random.choice(touch_files)
        touch_file_path = os.path.join(touch_dir, random_file)
        
        logger.info(f"选择触摸音频文件: {touch_file_path}")
        
        # 读取wav音频文件为pcm数据
        with wave.open(touch_file_path, "rb") as audio_file:
            audio_data = audio_file.readframes(audio_file.getnframes())
        
        return audio_data
        
    except Exception as e:
        logger.error(f"获取触摸音频数据时出错: {str(e)}")
        return None 