"""
MiniCPM模型服务
负责MiniCPM模型的加载、管理和使用
"""
import logging
import traceback
import torch
from fastapi import HTTPException
from transformers import AutoModel, AutoTokenizer
import librosa
from app.services.memory_cache import MemoryCache

# 配置日志
logger = logging.getLogger(__name__)

# 全局变量存储MiniCPM模型和相关组件
model = None 
tokenizer = None
loading = False
device = "auto" if torch.cuda.is_available() else "cpu"

# 初始化缓存
cache = MemoryCache()

def load_model():
    """
    加载MiniCPM-o-2_6模型，只在第一次调用时初始化
    """
    global model, tokenizer, loading, device
    
    # 避免并发初始化
    if loading:
        return False
        
    if model is not None and tokenizer is not None:
        return True
        
    try:
        loading = True
        logger.info("开始加载MiniCPM-o模型...")
        
        # 加载MiniCPM-o-2_6模型
        model_name = "openbmb/MiniCPM-o-2_6"

        from accelerate import load_checkpoint_and_dispatch, init_empty_weights, infer_auto_device_map
        with init_empty_weights():
            model = AutoModel.from_pretrained(
                model_name, trust_remote_code=True, 
                attn_implementation='sdpa', torch_dtype=torch.bfloat16,
                init_vision=False, init_audio=True, init_tts=True)
        
        device_map = infer_auto_device_map(model, max_memory={0: "10GB", 1: "10GB"},
            no_split_module_classes=['SiglipVisionTransformer', 'Qwen2DecoderLayer'])
        device_id = device_map["llm.model.embed_tokens"]
        device_map["llm.lm_head"] = device_id # first and last layer should be in same device
        device_map["vpm"] = device_id
        device_map["resampler"] = device_id
        device_id2 = device_map["llm.model.layers.26"]
        device_map["llm.model.layers.8"] = device_id2
        device_map["llm.model.layers.9"] = device_id2
        device_map["llm.model.layers.10"] = device_id2
        device_map["llm.model.layers.11"] = device_id2
        device_map["llm.model.layers.12"] = device_id2
        device_map["llm.model.layers.13"] = device_id2
        device_map["llm.model.layers.14"] = device_id2
        device_map["llm.model.layers.15"] = device_id2
        device_map["llm.model.layers.16"] = device_id2
        # print(device_map)


        model_path = "./minicpm"
        model = load_checkpoint_and_dispatch(model, model_path, dtype=torch.bfloat16, device_map=device_map)
        tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)

        model.init_tts()
        model.tts.to(device_id)
        model.tts.float()

        model.eval()

        logger.info(f"MiniCPM-o模型已加载到{device_id}, {device_id2}")
        loading = False
        return True
    except Exception as e:
        logger.error(f"加载MiniCPM-o模型失败: {str(e)}")
        logger.error(f"错误详情: {traceback.format_exc()}")
        loading = False
        return False

async def voice_chat(audio_input, ref_audio, output_audio_path, session_id, max_new_tokens=128, temperature=0.3):
    """
    使用MiniCPM模型进行语音对话，并保存聊天记录到缓存。
    """
    if not load_model():
        raise HTTPException(status_code=500, detail="无法加载MiniCPM-o模型")
    
    try:
        # ref_audio, _ = librosa.load(ref_audio, sr=16000, mono=True)
        # sys_prompt = model.get_sys_prompt(ref_audio=None, mode='audio_roleplay', language='zh')
        # print("sys_prompt: ", sys_prompt)

        # 获取历史聊天记录
        history = cache.get_messages(session_id)

        user_audio, _ = librosa.load(audio_input, sr=16000, mono=True)
        user_question = {'role': 'user', 'content': [user_audio]}
        # msgs.extend(history)  # 将历史记录添加到当前消息中
        msgs = history + [user_question]

        params = {
            'sampling': True,
            'top_p': 0.8,
            'top_k': 100,
            'temperature': 0.7,
            'repetition_penalty': 1.05,
            "max_new_tokens": 2048
        }
        res = model.chat(
            image=None,
            msgs=msgs,
            tokenizer=tokenizer,
            # generate_audio=True,
            # use_tts_template=True,
            # output_audio_path=output_audio_path,
            **params
        )

        # 将当前对话添加到缓存
        cache.add_message(session_id, user_question)
        cache.add_message(session_id, {'role': 'assistant', 'content': res})
        
        return res
    except Exception as e:
        logger.error(f"生成语音回复失败: {str(e)}")
        logger.error(f"错误详情: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"生成语音回复失败: {str(e)}")

def get_model_status():
    """
    获取MiniCPM模型的加载状态
    """
    global model, tokenizer, loading
    
    if loading:
        status = "loading"
    elif model is not None and tokenizer is not None:
        status = "ready"
    else:
        status = "not_loaded"
    
    return {
        "status": status,
        "device": device,
        "gpu_available": torch.cuda.is_available(),
        "model": "openbmb/MiniCPM-o-2_6",
        "capabilities": [
            "端到端语音对话",
            "语音输入到语音输出",
            "可配置声音特性",
            "流式文本响应"
        ]
    }