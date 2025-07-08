import logging
from fastapi import FastAPI
from app.config import settings
from app.services import init_services
import os
from dotenv import load_dotenv

# 配置日志
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),  # 输出到控制台
        logging.FileHandler('websocket.log')  # 输出到单独的日志文件
    ]
)
logger = logging.getLogger("websocket")

# 加载.env文件
load_dotenv()

# 创建WebSocket应用
ws_app = FastAPI(
    title="WebSocket Server",
    description="WebSocket服务器，用于音频数据代理",
    version="0.1.0",
)
# 根据环境变量决定使用哪种通信方式
COMMUNICATION_MODE = os.getenv("COMMUNICATION_MODE", "websocket").lower()

if COMMUNICATION_MODE == "mqtt":
    from app.mqtt.routes import router as mqtt_router
    ws_app.include_router(mqtt_router)
    print("已启用MQTT通信模式，前端可连接到 /mqtt_proxy 端点")
else:
    from app.websocket.routes import router as ws_router
    ws_app.include_router(ws_router, prefix=settings.WEBSOCKET_PATH)
    print("已启用WebSocket通信模式，前端可连接到 /ws/proxy 端点")

@ws_app.on_event("startup")
async def startup_event():
    logger.info("Starting WebSocket server...")
    # 初始化服务目录
    init_services()
    logger.info(f"WebSocket server running on port {settings.WEBSOCKET_PORT}")

@ws_app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down WebSocket server...")
