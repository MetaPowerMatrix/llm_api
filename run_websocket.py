#!/usr/bin/env python3
import os
import sys
import uvicorn

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.config import settings

if __name__ == "__main__":
    """WebSocket服务器主入口"""
    uvicorn.run(
        "app.server:ws_app",
        host="0.0.0.0",
        port=settings.WEBSOCKET_PORT,
        reload=settings.APP_ENV == "development",
        # timeout_keep_alive=120,        # 将保持连接活跃的超时时间设为120秒
        # ws_ping_interval=30,           # 将WebSocket ping间隔设为30秒
        # ws_ping_timeout=30,            # 将WebSocket ping超时设为30秒
    )