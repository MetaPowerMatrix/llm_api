import time
import logging
import grpc
from concurrent import futures

from app.config import settings

# 注意：在实际运行前，需要先执行generate_grpc.py生成service_pb2和service_pb2_grpc
# 这里先假设已经生成了这些文件
try:
    from app.grpc import service_pb2, service_pb2_grpc
except ImportError:
    logging.warning("gRPC生成的代码未找到。请先运行generate_grpc.py脚本。")
    # 创建模拟的类，使代码能够编译
    class service_pb2:
        class MessageRequest:
            pass
        class GetMessageRequest:
            pass
        class StreamRequest:
            pass
        class MessageResponse:
            pass
    
    class service_pb2_grpc:
        class MessageServiceServicer:
            pass
        def add_MessageServiceServicer_to_server(servicer, server):
            pass

logger = logging.getLogger(__name__)

class MessageServicer(service_pb2_grpc.MessageServiceServicer):
    """gRPC服务实现"""
    
    def SendMessage(self, request, context):
        """实现发送消息方法"""
        logger.info(f"收到发送消息请求: {request.content}")
        
        # 创建响应
        response = service_pb2.MessageResponse(
            id="msg_" + str(int(time.time())),
            content=request.content,
            created_at="2023-10-28T12:00:00Z",
            status="success"
        )
        
        # 如果是广播消息，可以在这里调用WebSocket连接管理器进行广播
        if request.broadcast:
            logger.info("广播消息到所有WebSocket客户端")
            # 这里可以异步调用WebSocket广播
            # 略，实际实现时需要处理异步调用
            
        return response
    
    def GetMessage(self, request, context):
        """实现获取消息方法"""
        logger.info(f"收到获取消息请求: {request.message_id}")
        
        # 这里可以从数据库查询消息
        # 略，实际实现时需要添加数据库访问逻辑
        
        # 创建响应
        if request.message_id == "msg_123456":
            response = service_pb2.MessageResponse(
                id=request.message_id,
                content="示例消息内容",
                created_at="2023-10-28T12:00:00Z",
                status="success"
            )
        else:
            # 设置gRPC错误
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"消息ID {request.message_id} 不存在")
            return service_pb2.MessageResponse()
            
        return response
    
    def StreamMessages(self, request, context):
        """实现流式响应方法"""
        logger.info(f"收到流式消息请求，数量: {request.count}")
        
        # 生成指定数量的消息
        for i in range(request.count):
            # 创建响应
            response = service_pb2.MessageResponse(
                id=f"msg_{i}",
                content=f"流式消息 {i}",
                created_at="2023-10-28T12:00:00Z",
                status="streaming"
            )
            
            yield response
            time.sleep(0.5)  # 间隔发送

def serve_grpc():
    """启动gRPC服务器"""
    # 创建gRPC服务器
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    
    # 添加服务实现
    service_pb2_grpc.add_MessageServiceServicer_to_server(
        MessageServicer(), server
    )
    
    # 添加安全凭证（如需要）
    # credentials = grpc.ssl_server_credentials(...)
    # server.add_secure_port(f'[::]:{settings.GRPC_PORT}', credentials)
    
    # 添加不安全端口（开发环境）
    server.add_insecure_port(f'[::]:{settings.GRPC_PORT}')
    
    # 启动服务器
    logger.info(f"gRPC服务器启动在端口 {settings.GRPC_PORT}")
    server.start()
    
    # 保持服务器运行
    server.wait_for_termination() 