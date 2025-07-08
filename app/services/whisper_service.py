"""
Whisper语音转文字服务
负责Whisper模型的加载、管理和使用
"""
import os
import logging
import traceback
import torch
import librosa
from fastapi import HTTPException
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

# 配置日志
logger = logging.getLogger(__name__)

# 全局变量存储加载的Whisper模型和处理器
whisper_model = None
whisper_processor = None
model_loading = False

def load_model():
    """
    加载Whisper模型和处理器，只在第一次调用时初始化，支持多 GPU
    """
    global whisper_model, whisper_processor, model_loading
    
    logger.info("准备加载Whisper模型...")

    # 避免并发初始化
    if model_loading:
        return False
        
    if whisper_model is not None and whisper_processor is not None:
        return True
        
    try:
        model_loading = True
        logger.info("开始加载Whisper模型...")
        
        # 加载模型
        model_id = "openai/whisper-large-v3"
        
        # 获取 GPU 信息
        # n_gpus = torch.cuda.device_count()
        n_gpus = 1
        logger.info(f"可用 GPU 数量: {n_gpus}")
        
        # 确定设备和数据类型
        device_map = "cuda:0" if n_gpus >= 1 else "cpu"
        torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        
        # 加载处理器
        whisper_processor = AutoProcessor.from_pretrained(
            model_id,
            local_files_only=False
        )
        
        # 如果有多个 GPU 可用，考虑使用量化配置减少内存占用
        if n_gpus > 1:
            from transformers import BitsAndBytesConfig
            
            quantization_config = BitsAndBytesConfig(
                load_in_8bit=True,
                llm_int8_threshold=6.0,
                llm_int8_has_fp16_weight=False
            )
            
            whisper_model = AutoModelForSpeechSeq2Seq.from_pretrained(
                model_id, 
                device_map=device_map,
                quantization_config=quantization_config,
                low_cpu_mem_usage=True, 
                use_safetensors=True,
                local_files_only=False
            )
        else:
            # 单 GPU 或 CPU 加载
            whisper_model = AutoModelForSpeechSeq2Seq.from_pretrained(
                model_id, 
                torch_dtype=torch_dtype,
                device_map=device_map,
                low_cpu_mem_usage=True, 
                use_safetensors=True,
                local_files_only=False
            )
        
        # 使模型处于评估模式
        whisper_model.eval()
        
        logger.info(f"Whisper模型已加载，设备映射: {device_map}, 数据类型: {torch_dtype}")
        model_loading = False
        return True
    except Exception as e:
        logger.error(f"加载Whisper模型失败: {str(e)}")
        # 记录更详细的错误信息
        logger.error(f"错误详情: {traceback.format_exc()}")
        model_loading = False
        return False

async def transcribe_audio(audio_file_path, language="zh"):
    """
    使用Whisper模型进行语音转文字
    """
    # 确保模型已加载
    if not load_model():
        raise HTTPException(status_code=500, detail="无法加载Whisper模型")
    
    try:
        # 读取音频文件
        audio_array, sampling_rate = librosa.load(audio_file_path, sr=16000)
        
        # 处理音频
        inputs = whisper_processor(
            audio_array, 
            sampling_rate=16000, 
            return_tensors="pt",
            return_attention_mask=True  # 确保返回注意力掩码
        )
        
        # 将输入移至GPU并转换为正确的数据类型（如果可用）
        if torch.cuda.is_available():
            # 确保数据类型匹配模型
            dtype = whisper_model.dtype  # 获取模型的数据类型
            inputs = {k: v.to("cuda:0").to(dtype) for k, v in inputs.items()}
        
        # 使用模型生成转录
        with torch.no_grad():
            # 只设置语言，不使用forced_decoder_ids
            generation_config = {
                "language": language,  # 设置语言
                "task": "transcribe"   # 设置任务类型为转录
            }
            
            # 生成转录
            predicted_ids = whisper_model.generate(
                **inputs,
                **generation_config
            )
        
        # 解码预测的token为文本
        transcription = whisper_processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]
        
        return transcription
    except Exception as e:
        logger.error(f"语音转文字失败: {str(e)}")
        # 记录更详细的错误信息
        logger.error(f"错误详情: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"语音转文字失败: {str(e)}")

def get_model_status():
    """
    获取Whisper模型的加载状态
    """
    global whisper_model, whisper_processor, model_loading
    
    if model_loading:
        status = "loading"
    elif whisper_model is not None and whisper_processor is not None:
        status = "ready"
    else:
        status = "not_loaded"
    
    return {
        "status": status,
        "gpu_available": torch.cuda.is_available(),
        "model": "openai/whisper-large-v3"
    }