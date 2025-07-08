import json
import logging
import os
import uuid
import asyncio
import time
from queue import Queue
from typing import Dict, Set
from fastapi import APIRouter, WebSocket
import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTTv5
from app.utils.audio import save_raw_to_wav, get_touch_audio_data

router = APIRouter()
logger = logging.getLogger(__name__)

# ===== 前端WebSocket连接管理 =====
frontend_clients: Dict[str, WebSocket] = {}
session_to_client: Dict[str, str] = {}
client_to_session: Dict[str, str] = {}
session_audio_buffers: Dict[str, bytearray] = {}
pending_sessions: Set[str] = set()

# ===== MQTT配置 =====
MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_CLIENT_ID = f"secretgarden_proxy_{uuid.uuid4().hex[:8]}"
MQTT_TOPICS = {
    "ai_audio": "secretgarden/ai/audio/+",  # + 是通配符，表示任意会话ID
    "ai_text": "secretgarden/ai/text/+",
    "proxy_audio": "secretgarden/proxy/audio/",  # 发送到AI后端的音频数据
    "heartbeat": "secretgarden/heartbeat"
}
MQTT_QOS = 1  # 至少一次传递

# 存储从MQTT接收的消息的队列
mqtt_message_queue = Queue()
mqtt_client = None
mqtt_connected = False

def on_mqtt_connect(client, userdata, flags, rc, properties=None):
    """MQTT连接回调"""
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        logger.info("已连接到MQTT代理")
        # 订阅音频和文本主题
        client.subscribe(MQTT_TOPICS["ai_audio"], qos=MQTT_QOS)
        client.subscribe(MQTT_TOPICS["ai_text"], qos=MQTT_QOS)
        client.subscribe(MQTT_TOPICS["heartbeat"], qos=MQTT_QOS)
    else:
        mqtt_connected = False
        logger.error(f"MQTT连接失败，返回码: {rc}")

def on_mqtt_disconnect(client, userdata, rc, properties=None):
    """MQTT断开连接回调"""
    global mqtt_connected
    mqtt_connected = False
    logger.info(f"已从MQTT代理断开连接: {rc}")
    if rc != 0:
        logger.warning("意外断开，尝试重新连接...")
        # 尝试重连
        try:
            client.reconnect()
        except Exception as e:
            logger.error(f"重连MQTT代理失败: {e}")

def on_mqtt_message(client, userdata, message):
    """MQTT消息接收回调"""
    try:
        # 解析主题以确定消息类型和会话ID
        topic_parts = message.topic.split('/')
        if len(topic_parts) < 3:
            logger.warning(f"收到格式不正确的MQTT主题: {message.topic}")
            return
            
        message_type = topic_parts[1]  # ai 或 proxy
        data_type = topic_parts[2]     # audio 或 text
        
        if len(topic_parts) > 3:
            session_id = topic_parts[3]  # 会话ID
        else:
            session_id = None
            
        # 将消息放入队列，以便异步处理
        mqtt_message_queue.put({
            "message_type": message_type,
            "data_type": data_type,
            "session_id": session_id,
            "payload": message.payload,
            "timestamp": time.time()
        })
        
        if data_type != "heartbeat":  # 不记录心跳消息
            logger.debug(f"MQTT消息已入队: {message_type}/{data_type}, 会话ID: {session_id}, 大小: {len(message.payload)} 字节")
    except Exception as e:
        logger.error(f"处理MQTT消息时出错: {str(e)}")

def initialize_mqtt_client():
    """初始化MQTT客户端"""
    global mqtt_client
    try:
        # 创建MQTT客户端
        mqtt_client = mqtt.Client(client_id=MQTT_CLIENT_ID, protocol=MQTTv5)
        
        # 设置回调
        mqtt_client.on_connect = on_mqtt_connect
        mqtt_client.on_disconnect = on_mqtt_disconnect
        mqtt_client.on_message = on_mqtt_message
        
        # 设置遗嘱消息（当客户端意外断开时发送）
        will_msg = json.dumps({
            "status": "offline",
            "client_id": MQTT_CLIENT_ID,
            "timestamp": time.time()
        })
        mqtt_client.will_set(
            topic=f"secretgarden/status/{MQTT_CLIENT_ID}",
            payload=will_msg,
            qos=1,
            retain=True
        )
        
        # 连接到MQTT代理
        logger.info(f"正在连接到MQTT代理 {MQTT_BROKER}:{MQTT_PORT}...")
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT)
        
        # 在后台线程启动MQTT循环
        mqtt_client.loop_start()
        
        return True
    except Exception as e:
        logger.error(f"初始化MQTT客户端失败: {str(e)}")
        return False

async def publish_audio_to_mqtt(session_id, audio_data):
    """通过MQTT发布音频数据到AI后端"""
    if not mqtt_connected:
        logger.warning("MQTT未连接，无法发送音频数据")
        return False
        
    try:
        # 构建完整的主题，包含会话ID
        topic = f"{MQTT_TOPICS['proxy_audio']}{session_id}"
        
        # 发布音频数据
        mqtt_client.publish(
            topic=topic,
            payload=audio_data,
            qos=MQTT_QOS
        )
        logger.info(f"已通过MQTT发送音频数据: {len(audio_data)} 字节, 会话ID: {session_id}")
        return True
    except Exception as e:
        logger.error(f"通过MQTT发送音频数据失败: {str(e)}")
        return False

async def process_mqtt_messages():
    """异步处理MQTT消息队列中的消息"""
    while True:
        try:
            # 检查队列是否有消息
            if not mqtt_message_queue.empty():
                message = mqtt_message_queue.get()
                
                message_type = message["message_type"]
                data_type = message["data_type"]
                session_id = message["session_id"]
                payload = message["payload"]
                
                # 处理不同类型的消息
                if message_type == "ai" and session_id:
                    if data_type == "audio":
                        # 处理来自AI后端的音频数据
                        await handle_mqtt_audio_message(session_id, payload)
                    elif data_type == "text":
                        # 处理来自AI后端的文本消息
                        try:
                            text_data = json.loads(payload)
                            await handle_mqtt_text_message(session_id, text_data)
                        except json.JSONDecodeError:
                            logger.error("无法解析MQTT文本消息的JSON内容")
                elif data_type == "heartbeat":
                    # 处理心跳消息
                    if mqtt_client:
                        mqtt_client.publish(
                            topic=f"{MQTT_TOPICS['heartbeat']}_ack",
                            payload=json.dumps({"timestamp": time.time()}),
                            qos=0
                        )
                
                # 标记消息已处理
                mqtt_message_queue.task_done()
            
            # 短暂休眠以避免CPU占用过高
            await asyncio.sleep(0.01)
        except Exception as e:
            logger.error(f"处理MQTT消息时出错: {str(e)}")
            await asyncio.sleep(1)  # 出错时稍微长一点的休眠

async def handle_mqtt_audio_message(session_id, audio_data):
    """处理从MQTT接收的音频数据"""
    if session_id in session_to_client:
        client_id = session_to_client[session_id]
        
        if client_id in frontend_clients:
            frontend_ws = frontend_clients[client_id]
            
            try:
                # 直接转发音频数据到前端WebSocket
                await frontend_ws.send_bytes(audio_data)
                logger.info(f"已将MQTT音频数据转发至前端客户端 {client_id}, 大小: {len(audio_data)} 字节")
            except Exception as e:
                logger.error(f"向前端发送MQTT音频数据失败: {str(e)}")
        else:
            logger.warning(f"找不到客户端ID: {client_id}")
    else:
        logger.warning(f"转发MQTT音频数据失败,找不到会话ID: {session_id}")

async def handle_mqtt_text_message(session_id, data):
    """处理从MQTT接收的文本消息"""
    if "type" not in data:
        logger.warning("MQTT文本消息缺少type字段")
        return
        
    if session_id in session_to_client:
        client_id = session_to_client[session_id]
        
        if client_id in frontend_clients:
            frontend_ws = frontend_clients[client_id]
            
            try:
                if data["type"] == "text":
                    # 文本消息
                    await frontend_ws.send_text(json.dumps({
                        "type": "text",
                        "content": data["content"]
                    }))
                elif data["type"] == "processing_complete":
                    # 处理完成消息
                    if session_id in pending_sessions:
                        pending_sessions.remove(session_id)
                    
                    # 通知前端处理完成
                    await frontend_ws.send_text(json.dumps({
                        "type": "status",
                        "content": "处理完成"
                    }))
                
                logger.info(f"已将MQTT文本消息转发至前端客户端 {client_id}")
            except Exception as e:
                logger.error(f"向前端发送MQTT文本消息失败: {str(e)}")
        else:
            logger.warning(f"找不到客户端ID: {client_id}")
    else:
        logger.warning(f"转发MQTT文本消息失败,找不到会话ID: {session_id}")

@router.websocket("/mqtt_proxy")
async def mqtt_proxy_websocket_endpoint(websocket: WebSocket):
    """MQTT版本的WebSocket端点，只处理前端客户端连接，后端通过MQTT通信"""
    await websocket.accept()
    
    # 启动MQTT客户端
    if not mqtt_client:
        mqtt_initialized = initialize_mqtt_client()
        if not mqtt_initialized:
            await websocket.send_text(json.dumps({
                "type": "error",
                "content": "MQTT客户端初始化失败"
            }))
            await websocket.close()
            return
    
    # 启动MQTT消息处理任务
    mqtt_processor_task = asyncio.create_task(process_mqtt_messages())
    
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
        
        if client_type != "frontend":
            # MQTT模式只支持前端客户端
            await websocket.send_text(json.dumps({
                "type": "error",
                "content": "MQTT模式只支持前端客户端连接"
            }))
            await websocket.close()
            return
            
        # 处理前端客户端连接
        client_id = f"client_{id(websocket)}"
        session_id = str(uuid.uuid4())
        
        # 记录映射关系
        frontend_clients[client_id] = websocket
        session_to_client[session_id] = client_id
        client_to_session[client_id] = session_id
        
        # 初始化音频缓冲区
        session_audio_buffers[session_id] = bytearray()
        
        logger.info(f"前端客户端已连接(MQTT模式): ID={client_id}, 会话ID={session_id}")
        
        # 向前端发送会话信息
        await websocket.send_text(json.dumps({
            "type": "session_info",
            "content": {
                "session_id": session_id,
                "client_id": client_id,
                "mode": "mqtt"
            }
        }))
        
        try:
            # 监听来自前端的消息
            while True:
                try:
                    message = await websocket.receive()
                    
                    # 检查消息类型
                    if "bytes" in message:
                        # 接收音频数据块
                        audio_data = message["bytes"]
                        session_audio_buffers[session_id].extend(audio_data)
                        
                    elif "text" in message:
                        # 解析JSON消息
                        try:
                            data = json.loads(message["text"])
                            
                            if "command" in data:
                                command = data["command"]
                                
                                if command == "audio_complete":
                                    # 前端发送完所有音频数据
                                    if len(session_audio_buffers[session_id]) > 0:
                                        logger.info(f"前端音频传输完成，准备通过MQTT转发，总大小: {len(session_audio_buffers[session_id])} 字节")
                                        wav_file_path = await save_raw_to_wav(session_audio_buffers[session_id])
                                        logger.info(f"音频数据已保存为WAV文件: {wav_file_path}")

                                        # 通过MQTT发送音频数据
                                        complete_audio_data = bytes(session_audio_buffers[session_id])
                                        
                                        # 发送数据
                                        mqtt_sent = await publish_audio_to_mqtt(session_id, complete_audio_data)
                                        
                                        if not mqtt_sent:
                                            await websocket.send_text(json.dumps({
                                                "type": "error",
                                                "content": "MQTT服务未连接，无法发送音频数据"
                                            }))
                                            continue
                                        
                                        # 加入等待处理队列
                                        pending_sessions.add(session_id)
                                        
                                        # 清空缓冲区，准备下一次录音
                                        session_audio_buffers[session_id] = bytearray()
                                        
                                    else:
                                        await websocket.send_text(json.dumps({
                                            "type": "error",
                                            "content": "没有接收到音频数据"
                                        }))
                                
                                elif command == "cancel_processing":
                                    # 取消正在处理的请求
                                    if session_id in pending_sessions:
                                        # 通知AI后端取消处理
                                        if mqtt_connected:
                                            mqtt_client.publish(
                                                topic=f"secretgarden/ai/control/{session_id}",
                                                payload=json.dumps({
                                                    "command": "cancel_processing",
                                                    "session_id": session_id
                                                }),
                                                qos=MQTT_QOS
                                            )
                                            
                                        pending_sessions.remove(session_id)
                                        
                                        await websocket.send_text(json.dumps({
                                            "type": "status",
                                            "content": "处理请求已取消"
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
                    logger.info(f"前端客户端断开连接(MQTT模式): {client_id}")
                    break
        except Exception as e:
            import sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            line_number = exc_tb.tb_lineno
            logger.error(f"前端客户端连接错误(MQTT模式): {str(e)}, 出错行号: {line_number}")
        finally:
            # 清理前端客户端资源
            if client_id in frontend_clients:
                del frontend_clients[client_id]
            
            if client_id in client_to_session:
                session_id = client_to_session[client_id]
                
                # 如果会话还在处理队列中，通知AI后端取消处理
                if session_id in pending_sessions and mqtt_connected:
                    try:
                        mqtt_client.publish(
                            topic=f"secretgarden/ai/control/{session_id}",
                            payload=json.dumps({
                                "command": "cancel_processing",
                                "session_id": session_id
                            }),
                            qos=MQTT_QOS
                        )
                    except:
                        pass
                        
                    pending_sessions.remove(session_id)
                
                # 清理会话相关资源
                if session_id in session_to_client:
                    del session_to_client[session_id]
                
                if session_id in session_audio_buffers:
                    del session_audio_buffers[session_id]
                    
                del client_to_session[client_id]
            
            logger.info(f"前端客户端资源已清理(MQTT模式): {client_id}")
            
            # 取消MQTT处理任务
            mqtt_processor_task.cancel()
    
    except Exception as e:
        logger.error(f"MQTT代理错误: {str(e)}")
        
        # 如果有运行中的MQTT处理任务，取消它
        if 'mqtt_processor_task' in locals():
            mqtt_processor_task.cancel()
            
        await websocket.close()