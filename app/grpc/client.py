import logging
import grpc

from app.config import settings

# 注意：在实际运行前，需要先执行generate_grpc.py生成service_pb2和service_pb2_grpc
try:
    from app.grpc import service_pb2, service_pb2_grpc
except ImportError:
    logging.warning("gRPC生成的代码未找到。请先运行generate_grpc.py脚本。")

logger = logging.getLogger(__name__)

class GrpcClient:
    """gRPC客户端示例"""
    
    def __init__(self, host="localhost", port=None):
        """初始化客户端"""
        self.port = port or settings.GRPC_PORT
        self.channel = grpc.insecure_channel(f"{host}:{self.port}")
        self.stub = service_pb2_grpc.MessageServiceStub(self.channel)
    
    def send_message(self, content, broadcast=False):
        """发送消息"""
        try:
            request = service_pb2.MessageRequest(
                content=content,
                broadcast=broadcast
            )
            response = self.stub.SendMessage(request)
            return response
        except grpc.RpcError as e:
            logger.error(f"gRPC错误: {e.code()}: {e.details()}")
            return None
    
    def get_message(self, message_id):
        """获取消息"""
        try:
            request = service_pb2.GetMessageRequest(message_id=message_id)
            response = self.stub.GetMessage(request)
            return response
        except grpc.RpcError as e:
            logger.error(f"gRPC错误: {e.code()}: {e.details()}")
            return None
    
    def stream_messages(self, count=5):
        """接收流式消息"""
        try:
            request = service_pb2.StreamRequest(count=count)
            responses = self.stub.StreamMessages(request)
            
            for response in responses:
                yield response
                
        except grpc.RpcError as e:
            logger.error(f"gRPC错误: {e.code()}: {e.details()}")
            return None
    
    def close(self):
        """关闭连接"""
        self.channel.close()

def example_usage():
    """gRPC客户端使用示例"""
    client = GrpcClient()
    
    # 发送消息示例
    print("发送消息:")
    response = client.send_message("Hello, gRPC!", broadcast=True)
    print(f"响应: {response}")
    
    # 获取消息示例
    print("\n获取消息:")
    response = client.get_message("msg_123456")
    print(f"响应: {response}")
    
    # 流式消息示例
    print("\n接收流式消息:")
    for response in client.stream_messages(3):
        print(f"流式响应: {response}")
    
    # 关闭连接
    client.close()

if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    example_usage() 