from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks, Body
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import os
from app.config import settings
import shutil
from datetime import datetime
import json
import logging
import uuid
import requests
import hashlib
import tempfile
import librosa
import soundfile as sf
from base64 import b64encode
from dotenv import load_dotenv

# 导入模型服务
from app.services.whisper_service import transcribe_audio, get_model_status as get_whisper_status, load_model as load_whisper_model
from app.services.qwen_service import get_model_status as get_qwen_status, chat_with_model as qwen_chat
from app.services.uncensored_service import chat_with_uncensored as uncensored_chat, get_uncensored_status as get_uncensored_status

# 配置日志
logger = logging.getLogger(__name__)

router = APIRouter()

# 加载.env文件
load_dotenv()

@router.post("/speech-to-text")
async def speech_to_text(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    language: Optional[str] = Form("zh")
):
    try:
        if file.content_type is not None:
            if not file.content_type.startswith('audio/'):
                filename = file.filename.lower()
                audio_extensions = ['.wav', '.mp3', '.ogg', '.flac', '.m4a', '.aac']
                is_audio = any(filename.endswith(ext) for ext in audio_extensions)
                
                if not is_audio:
                    raise HTTPException(status_code=400, detail="只接受音频文件")
        else:
            # 当 content_type 为 None 时，检查文件扩展名
            filename = file.filename.lower() if file.filename else ""
            audio_extensions = ['.wav', '.mp3', '.ogg', '.flac', '.m4a', '.aac']
            is_audio = any(filename.endswith(ext) for ext in audio_extensions)
            
            if not is_audio:
                raise HTTPException(status_code=400, detail="只接受音频文件且未提供内容类型")
        
        # 创建临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            content = await file.read()
            if not content:
                raise HTTPException(status_code=400, detail="上传的文件为空")
                
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        # 进行语音转文字
        transcription = await transcribe_audio(temp_file_path, language)
        
        # 在后台任务中删除临时文件
        background_tasks.add_task(os.unlink, temp_file_path)
        
        return {
            "code": 0,
            "message": "语音转文字成功",
            "data": {
                "transcription": transcription,
                "language": language
            }
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"处理语音文件失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理语音文件失败: {str(e)}")

@router.get("/speech-to-text/status")
async def speech_to_text_status(background_tasks: BackgroundTasks):
    status_info = get_whisper_status()
    
    if status_info["status"] == "not_loaded":
        background_tasks.add_task(load_whisper_model)
        status_info["status"] = "loading"
    
    return status_info


@router.post("/chat/qwen")
async def chat_with_qwen(request: ChatRequest):
    """
    与Qwen-QwQ-32B模型进行对话
    """
    try:
        # 调用qwen_service中的chat_with_model函数
        result = await qwen_chat(
            prompt=request.prompt,
            history=request.history,
            max_length=request.max_length,
            temperature=request.temperature,
            top_p=request.top_p
        )
        
        return {
            "code": 0,
            "message": "对话成功",
            "data": result
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Qwen对话生成失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Qwen对话生成失败: {str(e)}")

@router.get("/qwen/status")
async def qwen_status(background_tasks: BackgroundTasks):
    """
    检查Qwen模型加载状态
    """
    status_info = get_qwen_status()
    
    # 尝试触发模型加载（如果尚未加载）
    if status_info["status"] == "not_loaded":
        from app.services.qwen_service import load_model
        background_tasks.add_task(load_model)
        status_info["status"] = "loading"
    
    return status_info

@router.post("/chat/uncensored")
async def chat_with_uncensored(request: ChatRequest):
    """
    与Gryphe/MythoMax-L2-13b模型进行对话
    """
    try:
        # 调用uncensored_service中的chat_with_uncensored函数
        result = await uncensored_chat(
            prompt=request.prompt,
        )

        return {
            "code": 0,
            "message": "对话成功",
            "data": result
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Gryphe/MythoMax-L2-13b对话生成失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Gryphe/MythoMax-L2-13b对话生成失败: {str(e)}")
    
@router.get("/uncensored/status")
async def uncensored_status(background_tasks: BackgroundTasks):
    """
    检查Gryphe/MythoMax-L2-13b模型加载状态
    """
    status_info = get_uncensored_status()

    # 尝试触发模型加载（如果尚未加载）
    if status_info["status"] == "not_loaded":
        from app.services.uncensored_service import load_uncensored_model
        background_tasks.add_task(load_uncensored_model)
        status_info["status"] = "loading"

    return status_info
