import logging
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI

from app.config import settings
from app.api.routes import router as api_router
from app.services import init_services

# 配置日志
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),  # 输出到控制台
        RotatingFileHandler('app.log', maxBytes=10*1024*1024, backupCount=5)  # 轮转日志文件
    ]
)

# 获取应用日志记录器
logger = logging.getLogger("app")

# 创建FastAPI应用
app = FastAPI(
    title="model access server",
    description="支持REST API的模型访问服务器",
    version="0.1.0",
)

# 注册REST API路由
app.include_router(api_router, prefix=settings.API_PREFIX)

@app.on_event("startup")
async def startup_event():
    """应用启动时执行的操作"""
    logger.info("Starting application...")
    
    # 初始化服务目录
    init_services()
    
    logger.info(f"REST API available at http://localhost:{settings.APP_PORT}{settings.API_PREFIX}")

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时执行的操作"""
    logger.info("Shutting down application...")

# def main():
#     """应用主入口"""
#     uvicorn.run(
#         "app.main:app",
#         host="0.0.0.0",
#         port=settings.APP_PORT,
#         reload=settings.APP_ENV == "development",
#     )

# if __name__ == "__main__":
#     main() 