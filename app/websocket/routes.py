import json
import logging
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
                        logger.debug(f"准备接收来自客户端的消息")
                        message = await websocket.receive()
                        
                        # 检查消息类型
                        if "text" in message:
                            # 解析JSON消息
                            try:
                                data = json.loads(message["text"])
                                
                                if "type" in data and data.get("type") == "heartbeat":
                                    # 回复心跳确认
                                    await ai_backend.send_text(json.dumps({"type": "heartbeat_ack"}))
                                    logger.info("收到心跳，回复心跳确认")
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
                                    # logger.info(f"接收到AI后端音频数据: {len(audio_data)} 字节, 会话ID: {session_id}")
                                        
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
                        logger.debug(f"准备接收来自客户端{client_id}的消息")
                        message = await websocket.receive()
                        
                        # 检查消息类型
                        if "bytes" in message:
                            # 接收音频数据块
                            audio_data = message["bytes"]
                            session_audio_buffers[session_id].extend(audio_data)
                            
                        elif "text" in message:
                            try:
                                data = json.loads(message["text"])
                                
                                if "command" in data:
                                    command = data["command"]
                                    
                                    if command == "audio_complete":
                                        # 前端发送完所有音频数据
                                        if len(session_audio_buffers[session_id]) > 0:
                                            logger.info(f"前端音频传输完成，准备转发到AI后端处理，总大小: {len(session_audio_buffers[session_id])} 字节")
                                            wav_file_path = await save_raw_to_wav(session_audio_buffers[session_id])
                                            logger.info(f"音频数据已保存为WAV文件: {wav_file_path}")

                                            # 检查AI后端是否连接
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
    