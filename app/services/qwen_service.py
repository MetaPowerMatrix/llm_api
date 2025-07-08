"""
Qwen模型服务
负责Qwen模型的加载、管理和使用
"""
import os
import logging
import traceback
import torch
from fastapi import HTTPException
from transformers import AutoModelForCausalLM, AutoTokenizer
from typing import List, Dict, Any

# 配置日志
logger = logging.getLogger(__name__)

# 全局变量
model = None
tokenizer = None
loading = False
device = "auto" if torch.cuda.is_available() else "cpu"

def load_model():
    """
    加载Qwen-QwQ-32B模型和tokenizer，只在第一次调用时初始化
    """
    global model, tokenizer, loading, device

    model_name = "Qwen/QwQ-32B"

    # 避免并发初始化
    if loading:
        return False
        
    if model is not None and tokenizer is not None:
        return True
    
    try:
        loading = True
        logger.info("开始加载Qwen-QwQ-32B模型...")

        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype="auto",
            device_map=device
        )
        tokenizer = AutoTokenizer.from_pretrained(model_name)

        logger.info(f"Qwen-QwQ-32B模型已加载到{device.upper()}")
        loading = False
        return True
    except Exception as e:
        logger.error(f"加载Qwen-QwQ-32B模型失败: {str(e)}")
        logger.error(f"错误详情: {traceback.format_exc()}")
        loading = False
        return False

def get_model_status():
    """
    获取Qwen模型的加载状态
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
        "model": "Qwen/QwQ-32B"
    }

async def chat_with_model(prompt: str, history: List[Dict[str, str]] = None, max_length: int = 2048, 
                         temperature: float = 0.7, top_p: float = 0.9) -> Dict[str, Any]:
    """
    与Qwen模型进行对话
    """
    if not load_model():
        raise HTTPException(status_code=500, detail="无法加载Qwen模型")
    
    try:
        # 处理历史记录格式
        messages = []
        
        # 如果有历史消息，添加到对话中
        if history:
            for msg in history:
                if "role" in msg and "content" in msg:
                    messages.append({"role": msg["role"], "content": msg["content"]})
        
        # 添加当前用户的消息
        messages.append({"role": "user", "content": prompt})
        
        # 生成回复
        with torch.no_grad():
            # 准备输入
            input_text = tokenizer.apply_chat_template(
                messages, 
                tokenize=False, 
                add_generation_prompt=True
            )
            
            # 编码输入
            inputs = tokenizer(input_text, return_tensors="pt").to("cuda")
            
            # 生成回复
            outputs = model.generate(
                **inputs,
                max_length=max_length,
                temperature=temperature,
                top_p=top_p,
                do_sample=True,
                pad_token_id=tokenizer.eos_token_id
            )

            generated_ids = [
                output_ids[len(input_ids):] for input_ids, output_ids in zip(inputs.input_ids, outputs)
            ]

            
            # 解码输出
            full_response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
            
            # 提取模型的回复（去除输入部分）
            assistant_response = full_response[len(input_text):].strip()
            
            # 更新历史
            new_history = history.copy() if history else []
            new_history.append({"role": "user", "content": prompt})
            new_history.append({"role": "assistant", "content": assistant_response})
            
            return {
                "response": assistant_response,
                "history": new_history
            }
            
    except Exception as e:
        logger.error(f"对话生成失败: {str(e)}")
        logger.error(f"错误详情: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"对话生成失败: {str(e)}")