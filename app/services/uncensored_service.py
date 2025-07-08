import logging
import traceback
import torch
from fastapi import HTTPException
from transformers import AutoTokenizer, LlamaForCausalLM, BitsAndBytesConfig
import json

# 配置日志
logger = logging.getLogger(__name__)

# 全局变量
model = None
tokenizer = None
loading = False
device = "auto" if torch.cuda.is_available() else "cpu"

# 检查Gryphe/MythoMax-L2-13b模型加载状态
def get_uncensored_status():
    """
    检查Gryphe/MythoMax-L2-13b模型加载状态
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
        "model": "Gryphe/MythoMax-L2-13b"
    }

def load_uncensored_model():
    """
    加载Gryphe/MythoMax-L2-13b模型
    """
    global model, tokenizer, loading, device

    # model_name = "Gryphe/MythoMax-L2-13b"
    model_name = "Austism/chronos-hermes-13b"

    # 避免并发初始化
    if loading:
        return False

    if model is not None and tokenizer is not None:
        return True

    try:
        loading = True
        logger.info("开始加载Gryphe/MythoMax-L2-13b模型...")

        # 使用量化配置减少内存占用
        quantization_config = BitsAndBytesConfig(
            load_in_8bit=True,
            llm_int8_threshold=6.0,
            llm_int8_has_fp16_weight=False
        )

        model = LlamaForCausalLM.from_pretrained(
            model_name,
            trust_remote_code=True,
            device_map=device,
            quantization_config=quantization_config
        )
        tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            trust_remote_code=True,
            device_map=device
        )

        logger.info(f"Gryphe/MythoMax-L2-13b模型已加载到{device.upper()}")
        loading = False
        return True
    except Exception as e:
        logger.error(f"加载Gryphe/MythoMax-L2-13b模型失败: {str(e)}")
        logger.error(f"错误详情: {traceback.format_exc()}")
        loading = False
        return False

async def chat_with_uncensored(prompt: str):
    """
    与Gryphe/MythoMax-L2-13b模型进行对话（异步版本）
    """
    global model, tokenizer, device

    if not load_uncensored_model():
        raise HTTPException(status_code=500, detail="无法加载Gryphe/MythoMax-L2-13b模型")

    # 将输入移动到CUDA设备
    prompt = generate_prompt(prompt)
    print("final instruction: ", prompt)
    inputs = tokenizer(prompt, return_tensors="pt")
    inputs = inputs.to("cuda")
    
    # 生成回复
    generate_ids = model.generate(
        inputs.input_ids, 
        max_new_tokens=350, 
        do_sample=True, 
        repetition_penalty=1.4, 
        temperature=0.35, 
        top_p=0.75, 
        top_k=40
    )
    result = tokenizer.batch_decode(generate_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]

    # 只返回### 角色消息:后的内容
    result = result.split("### 角色消息:")[1].strip()

    return {
        "response": result,
        "history": []
    }

def generate_prompt(text, character_json_path="/data/app/character.json"):
    with open(character_json_path, 'r') as f:
        character_data = json.load(f)

    name = character_data.get('name', '')
    background = character_data.get('description', '')
    personality = character_data.get('personality', '')
    circumstances = character_data.get('world_scenario', '')
    common_greeting = character_data.get('first_mes', '')
    past_dialogue = character_data.get('mes_example', '')
    past_dialogue_formatted = past_dialogue

    return f"""### Instruction:
扮演一个角色, 角色描述如下:
{"你的名字是: " + name + "." if name else ""}
{"你的背景故事和历史是: " + background if background else ""}
{"你的性格是: " + personality if personality else ""}
{"你的当前处境和情况是: " + circumstances if circumstances else ""}
{"你的常用问候是: " + common_greeting if common_greeting else ""}
记住, 你总是保持角色. 你就是你描述的以上角色.
{past_dialogue_formatted}

总是用新的和独特的话语, 不要重复在聊天历史中说过的话, 请使用中文回复.

用中文和你的角色性格相符的话回答以下消息，记住，请使用中文回复:
### 用户消息:
{text}
### 角色消息:
{name}:"""