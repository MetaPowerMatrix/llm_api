# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Starting the Application
```bash
# Start the main API server
python run.py

# Start WebSocket server  
python run_websocket.py

# Start via module (alternative)
python -m app.main
```

### gRPC Code Generation
```bash
# Generate gRPC code from proto files
python generate_grpc.py
```

### Environment Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp .env_private .env
# Edit .env with your API keys and configuration
```

### File Upload
```bash
# Upload voice files (example script)
./upload_voice.sh
```

## Architecture Overview

This is a multi-protocol AI model access server built with FastAPI, supporting:
- **REST API** (FastAPI on port 8000)
- **WebSocket** (real-time communication on port 8001)
- **gRPC** (high-performance RPC on port 50051)

### Core Components

#### Service Layer (`app/services/`)
- `whisper_service.py` - Speech-to-text using Whisper
- `minicpm_service.py` - MiniCPM multimodal model for voice chat
- `qwen_service.py` - Qwen-QwQ-32B text generation
- `deepseek_service.py` - DeepSeek-v3 model integration
- `uncensored_service.py` - Gryphe/MythoMax-L2-13b model
- `memory_cache.py` - Caching layer for models

#### API Layer (`app/api/`)
- `routes.py` - All REST API endpoints including:
  - `/api/v1/speech-to-text` - Audio transcription
  - `/api/v1/voice-chat` - End-to-end voice chat
  - `/api/v1/chat/*` - Text chat endpoints for different models
  - `/api/v1/upload/*` - File upload endpoints
  - `/api/v1/jd/*` - JD (京东) e-commerce integration

#### Real-time Communication
- **WebSocket** (`app/websocket/routes.py`) - Proxy between frontend and AI backend
- **gRPC** (`app/grpc/server.py`) - High-performance service interface

#### Configuration (`app/config/settings.py`)
- Environment-based configuration
- API keys and service endpoints
- Audio processing parameters
- Data storage directories

### Data Flow Architecture

1. **Frontend → WebSocket Proxy → AI Backend**
   - Real-time audio streaming
   - Session management with UUID tracking
   - Binary data forwarding with session context

2. **REST API → Service Layer → External APIs/Models**
   - HTTP requests for model inference
   - File upload and processing
   - E-commerce integration

3. **gRPC Service**
   - Message passing with streaming support
   - Integration with WebSocket for broadcasting

### Key Features

- **Multi-model Support**: Whisper, MiniCPM, Qwen, DeepSeek, Uncensored models
- **Audio Processing**: Real-time voice chat, speech-to-text, TTS
- **E-commerce Integration**: JD (京东) product upload and management
- **Session Management**: UUID-based session tracking across protocols
- **File Storage**: Organized audio, IMU, and image data storage
- **Real-time Communication**: WebSocket proxy with binary data support

### Important Notes

- Models are loaded lazily and cached for performance
- Audio data is processed in real-time with chunked streaming
- Session state is maintained across WebSocket connections
- gRPC code must be generated before running (use `generate_grpc.py`)
- Environment variables in `.env` are required for external API access