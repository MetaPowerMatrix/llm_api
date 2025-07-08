"""
DeepSeek大模型服务
负责DeepSeek模型的加载、管理和使用
"""
import os
import logging
import traceback
import torch
from fastapi import HTTPException
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from typing import List, Dict, Any
import uuid
from vllm import AsyncLLMEngine, SamplingParams
from vllm.engine.arg_utils import AsyncEngineArgs

# 配置日志
logger = logging.getLogger(__name__)

# 全局变量存储加载的DeepSeek模型和tokenizer
model = None
tokenizer = None
loading = False
device = "auto" if torch.cuda.is_available() else "cpu"

# 在全局变量部分新增v3模型相关变量
model_v3 = None
tokenizer_v3 = None
loading_v3 = False

def load_model():
    """
    加载DeepSeek-R1模型和tokenizer，只在第一次调用时初始化
    """
    global model, tokenizer, loading, device

    # 避免并发初始化
    if loading:
        return False
        
    if model is not None and tokenizer is not None:
        return True
        
    try:
        loading = True
        logger.info("开始加载DeepSeek-R1模型...")
        
        # 使用绝对路径加载本地模型
        model_path = "/data/api-secretgarden/models"
        
        logger.info(f"加载模型路径: {model_path}")
        
        # 获取 GPU 信息
        n_gpus = torch.cuda.device_count()
        logger.info(f"可用 GPU 数量: {n_gpus}")
        
        # 使用量化配置减少内存占用
        quantization_config = BitsAndBytesConfig(
            load_in_8bit=True,
            llm_int8_threshold=6.0,
            llm_int8_has_fp16_weight=False
        )
        
        # 首先加载tokenizer
        tokenizer = AutoTokenizer.from_pretrained(
            model_path, 
            trust_remote_code=True,
            local_files_only=True
        )
        
        # 加载模型，使用多 GPU 和量化减少内存占用
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            trust_remote_code=True,
            device_map=device,  # 自动分配到可用 GPU
            quantization_config=quantization_config,
            local_files_only=True
        )
        
        logger.info(f"DeepSeek-R1模型已加载到多个 GPU")
        loading = False
        return True
    except Exception as e:
        logger.error(f"加载DeepSeek-R1模型失败: {str(e)}")
        logger.error(f"错误详情: {traceback.format_exc()}")
        loading = False
        return False

# 新增v3模型加载函数
async def load_model_v3():
    """
    使用vLLM加载DeepSeek-V3-0324模型
    """
    global model_v3, tokenizer_v3, loading_v3

    if model_v3 is not None:
        return True

    try:
        loading_v3 = True
        logger.info("使用vLLM加载DeepSeek-V3-0324模型...")

        # vLLM引擎配置（根据官方推荐参数）
        engine_args = AsyncEngineArgs(
            model="/data/api-secretgarden/unsloth",  # 替换为转换后的BF16权重路径
            tokenizer="deepseek-ai/deepseek-v3",
            trust_remote_code=True,
            tensor_parallel_size=4,  # 根据GPU数量调整
            dtype="bfloat16",
            max_model_len=8192,
            gpu_memory_utilization=0.9,
            enforce_eager=True  # 兼容DeepSeek特殊算子
        )

        # 初始化异步引擎
        model_v3 = AsyncLLMEngine.from_engine_args(engine_args)
        
        # 加载独立tokenizer用于模板处理
        tokenizer_v3 = AutoTokenizer.from_pretrained(
            "deepseek-ai/deepseek-v3",
            trust_remote_code=True
        )
        
        logger.info("DeepSeek-V3-0324模型(vLLM)加载完成")
        return True
    except Exception as e:
        logger.error(f"vLLM加载失败: {str(e)}\n{traceback.format_exc()}")
        loading_v3 = False
        return False

async def chat_with_model(prompt: str, history: List[Dict[str, str]] = None, max_length: int = 2048, 
                         temperature: float = 0.7, top_p: float = 0.9) -> Dict[str, Any]:
    """
    与DeepSeek模型进行对话
    """
    if not load_model():
        raise HTTPException(status_code=500, detail="无法加载DeepSeek-R1模型")
    
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
            
            # 解码输出
            full_response = tokenizer.batch_decode(outputs, skip_special_tokens=True)[0]
            
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

# 新增v3对话函数
async def chat_with_v30324(
    prompt: str, 
    history: List[Dict[str, str]] = None,
    max_tokens: int = 2048,
    temperature: float = 0.7,
    top_p: float = 0.9,
    repetition_penalty: float = 1.1
) -> Dict[str, Any]:
    """
    使用vLLM进行异步推理
    """
    if not await load_model_v3():
        raise HTTPException(status_code=500, detail="模型加载失败")

    try:
        # 构建消息历史
        messages = []
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        # 生成对话模板
        input_text = tokenizer_v3.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )

        # 配置采样参数
        sampling_params = SamplingParams(
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            repetition_penalty=repetition_penalty,
            skip_special_tokens=True
        )

        # 创建异步生成任务
        result_generator = model_v3.generate(
            input_text, 
            sampling_params,
            request_id=str(uuid.uuid4())
        )

        # 流式获取结果
        full_output = ""
        async for output in result_generator:
            full_output = output.outputs[0].text

        # 构造返回结果
        return {
            "response": full_output.strip(),
            "history": messages + [{"role": "assistant", "content": full_output.strip()}]
        }

    except Exception as e:
        logger.error(f"vLLM推理失败: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="推理服务异常")

def get_model_status():
    """
    获取所有模型状态
    """
    global model, model_v3
    # if model is None:
    #     model = load_model()
    if model_v3 is None:
        model_v3 = load_model_v3()

    print(f"model: {model}, model_v3: {model_v3}")

    return {
        "deepseek-r1": {
            "status": "ready" if model else "not_loaded",
            "device": device
        },
        "deepseek-v3": {
            "status": "ready" if model_v3 else "not_loaded",
            "device": device
        }
    }