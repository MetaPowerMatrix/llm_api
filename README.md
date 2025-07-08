# Python WebServer

一个基于Python的Web服务器，支持WebSocket连接和gRPC接口服务。

## 功能

- RESTful API (使用FastAPI)
- WebSocket服务
- gRPC服务

## 安装

```bash
# 克隆仓库
git clone <仓库URL>
cd <项目目录>

# 安装依赖
pip install -r requirements.txt
```

## 运行

```bash
# 启动服务器
python -m app.main
```

## 目录结构

```
app/
├── api/            # REST API接口
├── config/         # 配置文件
├── grpc/           # gRPC服务实现
├── protos/         # Protobuf定义文件
├── services/       # 业务逻辑服务
├── websocket/      # WebSocket服务
└── main.py         # 应用入口
```

## 使用示例

### REST API

```
curl http://localhost:8000/api/v1/health
```

### WebSocket

```javascript
const ws = new WebSocket('ws://localhost:8000/ws');
ws.onmessage = (event) => {
  console.log(event.data);
};
```

### gRPC

通过gRPC客户端调用服务。

## 环境变量

创建`.env`文件并配置以下环境变量：

```
APP_ENV=development
APP_PORT=8000
GRPC_PORT=50051
``` 