"""
WebSocket路由模块

提供两个主要的WebSocket接口：

1. /proxy - 前端客户端和AI后端的通信代理
   - 支持前端客户端(client_type: "frontend")
   - 支持AI后端(client_type: "ai_backend")
   
2. /call - FreeSwitch呼叫和AI后端的通信代理（独立系统）
   - 支持FreeSwitch客户端(client_type: "freeswitch")
   - 支持AI后端(client_type: "ai_backend")
   
/call接口使用示例：

AI后端连接：
```javascript
const ws = new WebSocket("ws://localhost:8000/ws/call");
ws.send(JSON.stringify({"client_type": "ai_backend"}));
```

FreeSwitch客户端连接：
```javascript
const ws = new WebSocket("ws://localhost:8000/ws/call");
ws.send(JSON.stringify({
    "client_type": "freeswitch",
    "call_id": "optional-custom-call-id",
    "audio_config": {
        "audioDataType": "raw",  // 支持: raw, wav, mp3, ogg
        "sampleRate": 8000,      // 音频采样率
        "channels": 1,           // 声道数
        "bitDepth": 16          // 位深度
    }
}));
```

返回的音频数据格式：
```json
{
    "type": "streamAudio",
    "data": {
        "audioDataType": "raw",
        "sampleRate": 8000,
        "channels": 1,
        "bitDepth": 16,
        "audioData": "base64编码的音频数据"
    }
}
```
"""

import json
import logging
import base64
from typing import Dict, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import uuid
import asyncio
from app.utils.audio import save_raw_to_wav, get_touch_audio_data

router = APIRouter()
logger = logging.getLogger(__name__)

# 音频数据缓冲字典，用于存储每个客户端的音频片段
audio_buffers = {}
# 录音会话标识
recording_sessions = {}

# 前端客户端连接管理
frontend_clients: Dict[str, WebSocket] = {}
# AI后端连接管理
ai_backend: Optional[WebSocket] = None
# 前端会话ID到客户端映射
session_to_client: Dict[str, str] = {}
# 客户端ID到会话ID映射
client_to_session: Dict[str, str] = {}
# 会话音频数据缓冲
session_audio_buffers: Dict[str, bytearray] = {}

# /call接口独立的连接管理
call_freeswitch_clients: Dict[str, WebSocket] = {}
call_ai_backend: Optional[WebSocket] = None
call_to_client: Dict[str, str] = {}
client_to_call: Dict[str, str] = {}
call_audio_buffers: Dict[str, bytearray] = {}
# FreeSwitch客户端音频格式配置
call_audio_configs: Dict[str, dict] = {}


@router.websocket("/proxy")
async def proxy_websocket_endpoint(websocket: WebSocket):
    """
    WebSocket代理端点
    连接双方：
    1. 前端客户端 - 发送音频数据，接收AI处理后的结果
    2. AI后端 - 接收前端发送的音频数据，处理后返回结果
    """
    await websocket.accept()
    
    try:
        # 等待连接标识消息
        init_message = await websocket.receive_text()
        logger.info(f"初始化消息: {init_message}")
        init_data = json.loads(init_message)
        
        if "client_type" not in init_data:
            await websocket.send_text(json.dumps({
                "type": "error",
                "content": "缺少客户端类型标识"
            }))
            await websocket.close()
            return
            
        client_type = init_data["client_type"]
        
        if client_type == "ai_backend":
            # 处理AI后端连接
            global ai_backend
            
            # 如果已有AI后端连接，拒绝新连接
            if ai_backend is not None:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": "已存在AI后端连接"
                }))
                await websocket.close()
                return
                
            # 设置全局AI后端连接
            ai_backend = websocket
            logger.info("AI后端已连接")
            
            # 向AI后端发送确认消息
            await websocket.send_text(json.dumps({
                "type": "status",
                "content": "连接成功"
            }))
            
            try:
                # 监听来自AI后端的消息
                while True:
                    try:
                        # 在接收消息前记录日志
                        logger.info(f"准备接收来自AI后端的消息")
                        message = await websocket.receive()
                        
                        # 检查消息类型
                        if "text" in message:
                            # 解析JSON消息
                            try:
                                data = json.loads(message["text"])
                                
                                if "type" in data and data.get("type") == "heartbeat":
                                    # 回复心跳确认
                                    await ai_backend.send_text(json.dumps({"type": "heartbeat_ack"}))
                                    # logger.info("收到心跳，回复心跳确认")
                                elif "session_id" in data and "type" in data and data.get("type") == "text":
                                    session_id = str(uuid.UUID(data["session_id"]))
                                    
                                    # 查找对应的前端客户端
                                    if session_id in session_to_client:
                                        client_id = session_to_client[session_id]
                                        
                                        if client_id in frontend_clients:
                                            frontend_ws = frontend_clients[client_id]
                                            
                                            # 转发消息给前端
                                            await frontend_ws.send_text(json.dumps({
                                                "type": "text",
                                                "content": data["content"]
                                            }))
                                            logger.info(f"已将AI消息转发至前端客户端 {client_id}")
                                        else:
                                            logger.warning(f"找不到客户端ID: {client_id}")
                                    else:
                                        logger.warning(f"找不到会话ID: {session_id}")
                                else:
                                    logger.warning("AI后端消息缺少session_id或type")
                                    
                            except json.JSONDecodeError:
                                logger.error("无法解析AI后端发送的JSON消息")
                        
                        elif "bytes" in message:
                            # 处理二进制数据（音频）
                            binary_data = message["bytes"]
                            
                            # 从二进制数据中提取会话ID（前8字节）
                            if len(binary_data) > 16:
                                # 提取会话ID（会话ID是UUID格式，存储在前16字节）
                                session_id_bytes = binary_data[:16]
                                audio_data = binary_data[16:]
                                
                                try:
                                    # 将字节转换为UUID字符串
                                    session_id = str(uuid.UUID(bytes=session_id_bytes))
                                    logger.info(f"接收到AI后端音频数据: {len(audio_data)} 字节, 会话ID: {session_id}")
                                        
                                    # 查找对应的前端客户端
                                    if session_id in session_to_client:
                                        client_id = session_to_client[session_id]
                                        
                                        if client_id in frontend_clients:
                                            frontend_ws = frontend_clients[client_id]
                                            
                                            # 直接转发音频数据到前端
                                            await frontend_ws.send_bytes(audio_data)
                                            # logger.info(f"已将AI处理的音频数据转发至前端客户端 {client_id}")
                                        else:
                                            logger.warning(f"找不到客户端ID: {client_id}")
                                    else:
                                        logger.warning(f"转发音频数据失败,找不到会话ID: {session_id}")
                                except ValueError:
                                    logger.error("无法解析会话ID")
                            else:
                                logger.error("音频数据格式不正确")
                    except WebSocketDisconnect:
                        logger.info("AI后端断开连接")
                        break
            except Exception as e:
                logger.error(f"AI后端连接错误: {str(e)}")
            finally:
                # 清理AI后端连接
                ai_backend = None
                logger.info("AI后端连接已关闭")
                
        elif client_type == "frontend":
            client_id = f"client_{id(websocket)}"
            session_id = str(uuid.uuid4())
            
            # 记录映射关系
            frontend_clients[client_id] = websocket
            session_to_client[session_id] = client_id
            client_to_session[client_id] = session_id
            
            # 初始化音频缓冲区
            session_audio_buffers[session_id] = bytearray()
            
            logger.info(f"前端客户端已连接: ID={client_id}, 会话ID={session_id}")
            
            # 向前端发送会话信息
            await websocket.send_text(json.dumps({
                "type": "session_info",
                "content": {
                    "session_id": session_id,
                    "client_id": client_id
                }
            }))
            
            try:
                # 监听来自前端的消息
                while True:
                    try:
                        logger.debug(f"准备接收来自前端客户端{client_id}的消息")
                        message = await websocket.receive()
                        
                        # 检查消息类型
                        if "bytes" in message:
                            # 接收音频数据块
                            audio_data = message["bytes"]
                            
                            # 将音频数据添加到缓冲区
                            session_audio_buffers[session_id].extend(audio_data)
                            
                            # 检查缓冲区大小是否超过32k
                            if len(session_audio_buffers[session_id]) >= 32768:  # 32k = 32 * 1024
                                if ai_backend is not None:
                                    # 发送累积的音频数据
                                    complete_audio_data = bytes(session_audio_buffers[session_id])
                                    session_id_bytes = uuid.UUID(session_id).bytes
                                    data_with_session = session_id_bytes + complete_audio_data

                                    await ai_backend.send_bytes(data_with_session)
                                    
                                    # 清空缓冲区
                                    session_audio_buffers[session_id] = bytearray()
                                    logger.info(f"发送音频数据: {len(complete_audio_data)} 字节, 会话ID: {session_id}")
                                else:
                                    logger.warning("AI后端未连接，无法发送音频数据")
                            
                        elif "text" in message:
                            try:
                                data = json.loads(message["text"])
                                
                                if "command" in data:
                                    command = data["command"]
                                    
                                    if command == "audio_complete":
                                        pass
                                        # 前端发送完所有音频数据
                                        if len(session_audio_buffers[session_id]) > 0:
                                            if ai_backend is None:
                                                await websocket.send_text(json.dumps({
                                                    "type": "error",
                                                    "content": "AI后端未连接，无法处理请求"
                                                }))
                                                continue
                                            
                                            # 转发音频数据到AI后端
                                            # 创建包含会话ID的二进制数据包
                                            # 会话ID转为二进制
                                            complete_audio_data = bytes(session_audio_buffers[session_id])
                                            session_id_bytes = uuid.UUID(session_id).bytes
                                            data_with_session = session_id_bytes + complete_audio_data

                                            # 发送音频数据
                                            await ai_backend.send_bytes(data_with_session)
                                            
                                            # 清空缓冲区，准备下一次录音
                                            session_audio_buffers[session_id] = bytearray()
                                            
                                        else:
                                            await websocket.send_text(json.dumps({
                                                "type": "error",
                                                "content": "没有接收到音频数据"
                                            }))
                                    elif command == "touch":
                                        # 触摸事件处理
                                        amount = data.get("amount", 1.0)  # 获取触摸压力值，默认为1.0
                                        
                                        # 获取音频数据
                                        audio_data = await get_touch_audio_data(amount)
                                        
                                        if audio_data:
                                            # 发送音频数据，分块发送
                                            chunk_size = 5120  # 大约5KB
                                            for i in range(0, len(audio_data), chunk_size):
                                                audio_chunk = audio_data[i:i+chunk_size]
                                                await websocket.send_bytes(audio_chunk)
                                                await asyncio.sleep(0.05)  # 短暂延迟，控制发送速率
                                            logger.info(f"触摸音频发送完成，总大小: {len(audio_data)} 字节")
                                        else:
                                            await websocket.send_text(json.dumps({
                                                "type": "error",
                                                "content": "无法加载触摸音效"
                                            }))
                            except json.JSONDecodeError:
                                logger.error("无法解析前端发送的JSON消息")
                    except WebSocketDisconnect:
                        logger.info(f"前端客户端断开连接: {client_id}")
                        break
            except Exception as e:
                logger.error(f"前端客户端连接错误: {str(e)}")
            finally:
                # 清理前端客户端资源
                if client_id in frontend_clients:
                    del frontend_clients[client_id]
                
                if client_id in client_to_session:
                    session_id = client_to_session[client_id]
                    
                    # 清理会话相关资源
                    if session_id in session_to_client:
                        del session_to_client[session_id]
                    
                    if session_id in session_audio_buffers:
                        del session_audio_buffers[session_id]
                        
                    del client_to_session[client_id]
                
                logger.info(f"前端客户端资源已清理: {client_id}")
                logger.debug(f"删除会话映射: 会话ID={session_id}")
        else:
            # 未知客户端类型
            await websocket.send_text(json.dumps({
                "type": "error",
                "content": f"未知的客户端类型: {client_type}"
            }))
            await websocket.close()
            
    except WebSocketDisconnect:
        logger.info("WebSocket连接断开")
    except json.JSONDecodeError:
        logger.error("无法解析客户端初始化消息")
        await websocket.close()
    except Exception as e:
        import sys
        exc_type, exc_obj, exc_tb = sys.exc_info()
        line_number = exc_tb.tb_lineno
        logger.error(f"WebSocket代理错误: {str(e)}, 出错行号: {line_number}")
        await websocket.close()


@router.websocket("/call")
async def call_websocket_endpoint(websocket: WebSocket):
    """
    WebSocket呼叫端点 - 专门处理FreeSwitch呼叫
    连接双方：
    1. FreeSwitch客户端 - 发送呼叫音频数据，接收AI处理后的音频结果
    2. AI后端 - 接收呼叫音频数据，处理后返回音频结果
    """
    await websocket.accept()
    
    try:
        # 等待连接标识消息
        init_message = await websocket.receive_text()
        logger.info(f"呼叫初始化消息: {init_message}")
        init_data = json.loads(init_message)
        
        if "client_type" not in init_data:
            await websocket.send_text(json.dumps({
                "type": "error",
                "content": "缺少客户端类型标识"
            }))
            await websocket.close()
            return
            
        client_type = init_data["client_type"]
        
        if client_type == "ai_backend":
            # 处理AI后端连接（专门用于呼叫处理）
            global call_ai_backend
            
            # 如果已有AI后端连接，拒绝新连接
            if call_ai_backend is not None:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": "呼叫处理AI后端已存在连接"
                }))
                await websocket.close()
                return
                
            # 设置呼叫处理AI后端连接
            call_ai_backend = websocket
            logger.info("呼叫处理AI后端已连接")
            
            # 向AI后端发送确认消息
            await websocket.send_text(json.dumps({
                "type": "status",
                "content": "呼叫处理AI后端连接成功"
            }))
            
            try:
                # 监听来自AI后端的消息
                while True:
                    try:
                        logger.debug("准备接收来自呼叫AI后端的消息")
                        message = await websocket.receive()
                        
                        # 检查消息类型
                        if "text" in message:
                            # 解析JSON消息
                            try:
                                data = json.loads(message["text"])
                                
                                if "type" in data and data.get("type") == "heartbeat":
                                    # 回复心跳确认
                                    await call_ai_backend.send_text(json.dumps({"type": "heartbeat_ack"}))
                                elif "call_id" in data and "type" in data and data.get("type") == "text":
                                    call_id = str(uuid.UUID(data["call_id"]))
                                    
                                    # 查找对应的FreeSwitch客户端
                                    if call_id in call_to_client:
                                        client_id = call_to_client[call_id]
                                        
                                        if client_id in call_freeswitch_clients:
                                            freeswitch_ws = call_freeswitch_clients[client_id]
                                            
                                            # 转发消息给FreeSwitch
                                            await freeswitch_ws.send_text(json.dumps({
                                                "type": "text",
                                                "call_id": call_id,
                                                "content": data["content"]
                                            }))
                                            logger.info(f"已将AI消息转发至FreeSwitch客户端 {client_id}")
                                        else:
                                            logger.warning(f"找不到FreeSwitch客户端ID: {client_id}")
                                    else:
                                        logger.warning(f"找不到呼叫ID: {call_id}")
                                else:
                                    logger.warning("呼叫AI后端消息缺少call_id或type")
                                    
                            except json.JSONDecodeError:
                                logger.error("无法解析呼叫AI后端发送的JSON消息")
                        
                        elif "bytes" in message:
                            # 处理二进制数据（音频）
                            binary_data = message["bytes"]
                            
                            # 从二进制数据中提取呼叫ID（前16字节）
                            if len(binary_data) > 16:
                                # 提取呼叫ID（呼叫ID是UUID格式，存储在前16字节）
                                call_id_bytes = binary_data[:16]
                                audio_data = binary_data[16:]
                                
                                try:
                                    # 将字节转换为UUID字符串
                                    call_id = str(uuid.UUID(bytes=call_id_bytes))
                                    logger.info(f"接收到呼叫AI后端音频数据: {len(audio_data)} 字节, 呼叫ID: {call_id}")
                                        
                                    # 查找对应的FreeSwitch客户端
                                    if call_id in call_to_client:
                                        client_id = call_to_client[call_id]
                                        
                                        if client_id in call_freeswitch_clients:
                                            freeswitch_ws = call_freeswitch_clients[client_id]
                                            
                                            # 获取该呼叫的音频配置
                                            audio_config = call_audio_configs.get(call_id, {
                                                "audioDataType": "wav",
                                                "sampleRate": 24000,
                                                "channels": 1,
                                                "bitDepth": 16
                                            })
                                            
                                            # 按照FreeSwitch要求的格式转发音频数据
                                            audio_message = {
                                                "type": "streamAudio",
                                                "data": {
                                                    "audioDataType": "wav",
                                                    "sampleRate": 24000,
                                                    "channels": 1,
                                                    "bitDepth": 16,
                                                    "audioData": base64.b64encode(audio_data).decode('utf-8')
                                                }
                                            }
                                            
                                            # 如果配置中包含额外信息，也添加到消息中
                                            # if "channels" in audio_config:
                                            #     audio_message["data"]["channels"] = audio_config["channels"]
                                            # if "bitDepth" in audio_config:
                                            #     audio_message["data"]["bitDepth"] = audio_config["bitDepth"]
                                            
                                            await freeswitch_ws.send_text(json.dumps(audio_message))
                                            logger.info(f"已将AI处理的音频数据转发至FreeSwitch客户端 {client_id} (格式: {audio_config['audioDataType']}, {audio_config['sampleRate']}Hz)")
                                        else:
                                            logger.warning(f"找不到FreeSwitch客户端ID: {client_id}")
                                    else:
                                        logger.warning(f"转发音频数据失败,找不到呼叫ID: {call_id}")
                                except ValueError:
                                    logger.error("无法解析呼叫ID")
                            else:
                                logger.error("呼叫音频数据格式不正确")
                    except WebSocketDisconnect:
                        logger.info("呼叫AI后端断开连接")
                        break
            except Exception as e:
                logger.error(f"呼叫AI后端连接错误: {str(e)}")
            finally:
                # 清理AI后端连接
                call_ai_backend = None
                logger.info("呼叫AI后端连接已关闭")
                
        elif client_type == "freeswitch":
            # 处理FreeSwitch客户端连接
            client_id = f"fs_client_{id(websocket)}"
            
            # 获取呼叫ID，如果没有提供则生成一个
            call_id = init_data.get("call_id", str(uuid.uuid4()))
            
            # 获取音频格式配置，设置默认值
            audio_config = init_data.get("audio_config", {})
            default_config = {
                "audioDataType": "raw",
                "sampleRate": 8000,
                "channels": 1,
                "bitDepth": 16
            }
            # 合并配置，用户提供的配置覆盖默认值
            final_audio_config = {**default_config, **audio_config}
            
            # 验证音频格式
            supported_formats = ["raw", "wav", "mp3", "ogg"]
            if final_audio_config["audioDataType"] not in supported_formats:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": f"不支持的音频格式: {final_audio_config['audioDataType']}，支持的格式: {supported_formats}"
                }))
                await websocket.close()
                return
            
            # 记录映射关系
            call_freeswitch_clients[client_id] = websocket
            call_to_client[call_id] = client_id
            client_to_call[client_id] = call_id
            
            # 保存音频配置
            call_audio_configs[call_id] = final_audio_config
            
            # 初始化音频缓冲区
            call_audio_buffers[call_id] = bytearray()
            
            logger.info(f"FreeSwitch客户端已连接: ID={client_id}, 呼叫ID={call_id}, 音频格式={final_audio_config['audioDataType']}")
            
            # 发送欢迎音频，读取目录下的welcome.wav，转换成8000，mono，16bit
            with open("welcome.wav", "rb") as f:
                audio_data = f.read()
                audio_data = base64.b64encode(audio_data).decode('utf-8')
                
            logger.info(f"欢迎音频数据长度: {len(audio_data)}")

            welcome_message = {
                "type": "streamAudio",
                "data": {
                    "audioDataType": "wav",
                    "sampleRate": 32000,
                    "channels": 1,
                    "bitDepth": 16,
                    "audioData": audio_data
                }
            }
            await websocket.send_text(json.dumps(welcome_message))
            logger.info(f"发送欢迎音频: {len(audio_data)} 字节")
            await asyncio.sleep(1)
            
            try:
                # 监听来自FreeSwitch的消息
                while True:
                    try:
                        logger.debug(f"准备接收来自FreeSwitch客户端{client_id}的消息")
                        message = await websocket.receive()
                        
                        # 检查消息类型
                        if "bytes" in message:
                            # 接收音频数据块
                            audio_data = message["bytes"]
                            # 保存为wav文件到当前目录的input目录下
                            with open(f"input/{call_id}.wav", "wb") as f:
                                f.write(audio_data)
                            logger.info(f"保存音频数据到文件: {call_id}.wav")
                            
                            # 将音频数据添加到缓冲区
                            call_audio_buffers[call_id].extend(audio_data)
                            
                            # 检查缓冲区大小是否超过32k
                            if len(call_audio_buffers[call_id]) >= 32768:  # 32k = 32 * 1024
                                if call_ai_backend is not None:
                                    # 发送累积的音频数据到呼叫AI后端
                                    complete_audio_data = bytes(call_audio_buffers[call_id])
                                    # 使用call_id作为会话标识
                                    call_id_bytes = uuid.UUID(call_id).bytes
                                    data_with_call_id = call_id_bytes + complete_audio_data

                                    await call_ai_backend.send_bytes(data_with_call_id)
                                    
                                    # 清空缓冲区
                                    call_audio_buffers[call_id] = bytearray()
                                    logger.info(f"发送呼叫音频数据: {len(complete_audio_data)} 字节, 呼叫ID: {call_id}")
                                else:
                                    logger.warning("呼叫AI后端未连接，无法发送呼叫音频数据")
                            
                        elif "text" in message:
                            try:
                                data = json.loads(message["text"])
                                
                                if "command" in data:
                                    command = data["command"]
                                    
                                    if command == "audio_complete":
                                        # FreeSwitch发送完当前音频片段
                                        if len(call_audio_buffers[call_id]) > 0:
                                            if call_ai_backend is None:
                                                await websocket.send_text(json.dumps({
                                                    "type": "error",
                                                    "content": "呼叫AI后端未连接，无法处理呼叫请求"
                                                }))
                                                continue
                                            
                                            # 转发剩余音频数据到呼叫AI后端
                                            complete_audio_data = bytes(call_audio_buffers[call_id])
                                            call_id_bytes = uuid.UUID(call_id).bytes
                                            data_with_call_id = call_id_bytes + complete_audio_data

                                            # 发送音频数据
                                            await call_ai_backend.send_bytes(data_with_call_id)
                                            
                                            # 清空缓冲区
                                            call_audio_buffers[call_id] = bytearray()
                                            logger.info(f"呼叫音频发送完成: {len(complete_audio_data)} 字节, 呼叫ID: {call_id}")
                                            
                                        else:
                                            await websocket.send_text(json.dumps({
                                                "type": "error",
                                                "content": "没有接收到呼叫音频数据"
                                            }))
                                    
                                    elif command == "call_start":
                                        # 呼叫开始
                                        logger.info(f"呼叫开始: {call_id}")
                                        await websocket.send_text(json.dumps({
                                            "type": "status",
                                            "content": "呼叫已开始"
                                        }))
                                    
                                    elif command == "call_end":
                                        # 呼叫结束
                                        logger.info(f"呼叫结束: {call_id}")
                                        await websocket.send_text(json.dumps({
                                            "type": "status",
                                            "content": "呼叫已结束"
                                        }))
                                        break
                                    
                                    elif command == "heartbeat":
                                        # 心跳检测
                                        await websocket.send_text(json.dumps({
                                            "type": "heartbeat_ack",
                                            "timestamp": data.get("timestamp")
                                        }))
                                        
                            except json.JSONDecodeError:
                                logger.error("无法解析FreeSwitch发送的JSON消息")
                    except WebSocketDisconnect:
                        logger.info(f"FreeSwitch客户端断开连接: {client_id}")
                        break
            except Exception as e:
                logger.error(f"FreeSwitch客户端连接错误: {str(e)}")
            finally:
                # 清理FreeSwitch客户端资源
                if client_id in call_freeswitch_clients:
                    del call_freeswitch_clients[client_id]
                
                if client_id in client_to_call:
                    call_id = client_to_call[client_id]
                    
                    # 清理呼叫相关资源
                    if call_id in call_to_client:
                        del call_to_client[call_id]
                    
                    if call_id in call_audio_buffers:
                        del call_audio_buffers[call_id]
                    
                    # 清理音频配置
                    if call_id in call_audio_configs:
                        del call_audio_configs[call_id]
                        
                    del client_to_call[client_id]
                
                logger.info(f"FreeSwitch客户端资源已清理: {client_id}")
                logger.debug(f"删除呼叫映射: 呼叫ID={call_id}")
                
        else:
            # 未知客户端类型
            await websocket.send_text(json.dumps({
                "type": "error", 
                "content": f"呼叫接口不支持的客户端类型: {client_type}，支持的类型: ai_backend, freeswitch"
            }))
            await websocket.close()
            
    except WebSocketDisconnect:
        logger.info("呼叫WebSocket连接断开")
    except json.JSONDecodeError:
        logger.error("无法解析呼叫客户端初始化消息")
        await websocket.close()
    except Exception as e:
        import sys
        exc_type, exc_obj, exc_tb = sys.exc_info()
        line_number = exc_tb.tb_lineno
        logger.error(f"呼叫WebSocket错误: {str(e)}, 出错行号: {line_number}")
        await websocket.close()


@router.get("/call/status")
async def get_call_status():
    """
    获取呼叫接口的连接状态
    """
    return {
        "status": "ok",
        "connections": {
            "ai_backend": {
                "connected": call_ai_backend is not None,
                "connection_id": id(call_ai_backend) if call_ai_backend else None
            },
            "freeswitch_clients": {
                "count": len(call_freeswitch_clients),
                "clients": list(call_freeswitch_clients.keys())
            },
            "active_calls": {
                "count": len(call_to_client),
                "calls": list(call_to_client.keys())
            },
            "audio_buffers": {
                "count": len(call_audio_buffers),
                "buffer_sizes": {call_id: len(buffer) for call_id, buffer in call_audio_buffers.items()}
            },
            "audio_configs": {
                "count": len(call_audio_configs),
                "configurations": {call_id: config for call_id, config in call_audio_configs.items()}
            }
        }
    }

@router.post("/call/cleanup")
async def cleanup_call_resources():
    """
    清理呼叫接口的孤立资源（管理员使用）
    """
    cleaned_items = []
    
    # 清理孤立的音频缓冲区
    orphaned_buffers = []
    for call_id in list(call_audio_buffers.keys()):
        if call_id not in call_to_client:
            orphaned_buffers.append(call_id)
            del call_audio_buffers[call_id]
    
    # 清理孤立的音频配置
    orphaned_configs = []
    for call_id in list(call_audio_configs.keys()):
        if call_id not in call_to_client:
            orphaned_configs.append(call_id)
            del call_audio_configs[call_id]
    
    if orphaned_buffers:
        cleaned_items.append(f"清理了 {len(orphaned_buffers)} 个孤立的音频缓冲区")
    
    if orphaned_configs:
        cleaned_items.append(f"清理了 {len(orphaned_configs)} 个孤立的音频配置")
    
    # 检查并清理不一致的映射关系
    inconsistent_mappings = []
    
    # 检查 call_to_client 中的映射是否在 client_to_call 中存在
    for call_id, client_id in list(call_to_client.items()):
        if client_id not in client_to_call or client_to_call[client_id] != call_id:
            inconsistent_mappings.append(f"call_to_client: {call_id} -> {client_id}")
            del call_to_client[call_id]
    
    # 检查 client_to_call 中的映射是否在 call_to_client 中存在
    for client_id, call_id in list(client_to_call.items()):
        if call_id not in call_to_client or call_to_client[call_id] != client_id:
            inconsistent_mappings.append(f"client_to_call: {client_id} -> {call_id}")
            del client_to_call[client_id]
    
    if inconsistent_mappings:
        cleaned_items.append(f"修复了 {len(inconsistent_mappings)} 个不一致的映射关系")
    
    # 检查是否有断开连接但未清理的客户端
    disconnected_clients = []
    for client_id, ws in list(call_freeswitch_clients.items()):
        try:
            # 尝试发送ping来检查连接状态
            await ws.ping()
        except:
            # 连接已断开，清理相关资源
            disconnected_clients.append(client_id)
            del call_freeswitch_clients[client_id]
            
            # 清理相关映射
            if client_id in client_to_call:
                call_id = client_to_call[client_id]
                if call_id in call_to_client:
                    del call_to_client[call_id]
                if call_id in call_audio_buffers:
                    del call_audio_buffers[call_id]
                if call_id in call_audio_configs:
                    del call_audio_configs[call_id]
                del client_to_call[client_id]
    
    if disconnected_clients:
        cleaned_items.append(f"清理了 {len(disconnected_clients)} 个断开的FreeSwitch客户端")
    
    if not cleaned_items:
        cleaned_items.append("没有发现需要清理的资源")
    
    return {
        "status": "cleanup_completed",
        "cleaned_items": cleaned_items,
        "current_status": {
            "ai_backend_connected": call_ai_backend is not None,
            "freeswitch_clients": len(call_freeswitch_clients),
            "active_calls": len(call_to_client),
            "audio_buffers": len(call_audio_buffers),
                         "audio_configs": len(call_audio_configs)
         }
     }