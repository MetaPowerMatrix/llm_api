#!/usr/bin/env python3
"""
音频接收器 - 接收mod_audio_stream发送的PCM音频数据并保存为WAV文件
"""

import asyncio
import websockets
import wave
import struct
import logging
from datetime import datetime
import os

class AudioReceiver:
    def __init__(self, sample_rate=16000, channels=1, output_dir="./audio_output"):
        """
        初始化音频接收器
        
        Args:
            sample_rate: 采样率 (8000 或 16000)
            channels: 声道数 (1=mono, 2=stereo)
            output_dir: 输出目录
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.output_dir = output_dir
        self.audio_data = bytearray()
        self.session_id = None
        
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)
        
        # 设置日志
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
    
    def create_wav_header(self, data_length):
        """
        创建WAV文件头
        
        Args:
            data_length: PCM数据长度(字节)
            
        Returns:
            bytes: WAV文件头(44字节)
        """
        # WAV文件头格式
        header = struct.pack('<4sI4s', b'RIFF', 36 + data_length, b'WAVE')
        
        # fmt子块
        fmt_chunk = struct.pack('<4sIHHIIHH',
            b'fmt ',          # 子块ID
            16,               # 子块大小
            1,                # 音频格式 (1=PCM)
            self.channels,    # 声道数
            self.sample_rate, # 采样率
            self.sample_rate * self.channels * 2,  # 字节率
            self.channels * 2,  # 块对齐
            16                # 位深度
        )
        
        # data子块头
        data_header = struct.pack('<4sI', b'data', data_length)
        
        return header + fmt_chunk + data_header
    
    def save_wav_file(self, filename=None):
        """
        保存PCM数据为WAV文件
        
        Args:
            filename: 输出文件名，如果为None则自动生成
        """
        if not self.audio_data:
            self.logger.warning("没有音频数据可保存")
            return
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            session_suffix = f"_{self.session_id}" if self.session_id else ""
            filename = f"audio_{timestamp}{session_suffix}.wav"
        
        filepath = os.path.join(self.output_dir, filename)
        
        try:
            # 创建WAV文件头
            wav_header = self.create_wav_header(len(self.audio_data))
            
            # 写入WAV文件
            with open(filepath, 'wb') as f:
                f.write(wav_header)
                f.write(self.audio_data)
            
            self.logger.info(f"音频已保存: {filepath}")
            self.logger.info(f"文件大小: {len(self.audio_data)} bytes")
            self.logger.info(f"时长: {len(self.audio_data) / (self.sample_rate * self.channels * 2):.2f}秒")
            
        except Exception as e:
            self.logger.error(f"保存WAV文件失败: {e}")
    