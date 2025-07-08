import os
from dotenv import load_dotenv

# 加载.env文件中的环境变量
load_dotenv()

# 应用环境：development, production, testing
APP_ENV = os.getenv("APP_ENV", "production")

# FastAPI服务端口
APP_PORT = int(os.getenv("APP_PORT", 8000))

# gRPC服务端口
GRPC_PORT = int(os.getenv("GRPC_PORT", 50051))

# WebSocket服务端口
WEBSOCKET_PORT = int(os.getenv("WEBSOCKET_PORT", 8001))

# 日志配置
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# 其他配置项
API_PREFIX = "/api/v1"
WEBSOCKET_PATH = "/ws"

# API密钥配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# 数据存储目录
DATA_DIR = os.getenv("DATA_DIR", "/data/app/")
os.makedirs(DATA_DIR, exist_ok=True)

# 音频处理配置
# 存储音频和IMU数据的目录
AUDIO_DIR = os.path.join(DATA_DIR, "audio")
IMU_DIR = os.path.join(DATA_DIR, "imu")
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")

# 确保目录存在
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(IMU_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)

# ESP32音频参数设置
ESP32_SAMPLE_RATE = int(os.getenv("ESP32_SAMPLE_RATE", 44100))  # ESP32使用的采样率，需匹配ESP32的I2S配置
ESP32_CHANNELS = int(os.getenv("ESP32_CHANNELS", 1))            # 单声道
ESP32_SAMPLE_WIDTH = int(os.getenv("ESP32_SAMPLE_WIDTH", 2))    # 16位

# 图片存储配置
IMAGE_STORAGE_DIR = os.getenv("IMAGE_STORAGE_DIR", "/data/www/xfiles/extra-images")

# 确保图片存储目录存在
os.makedirs(IMAGE_STORAGE_DIR, exist_ok=True)

JD_OPENAPI_URL = os.getenv("JD_OPENAPI_URL", "")
JD_APP_KEY = os.getenv("JD_APP_KEY", "")
JD_APP_SECRET = os.getenv("JD_APP_SECRET", "")
