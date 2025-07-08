#!/usr/bin/env python3
"""
生成gRPC代码的脚本
"""
import os
import subprocess

def main():
    """生成gRPC代码"""
    proto_dir = os.path.join("app", "protos")
    grpc_dir = os.path.join("app", "grpc")
    
    # 确保目录存在
    os.makedirs(grpc_dir, exist_ok=True)
    
    # 创建__init__.py文件
    with open(os.path.join(grpc_dir, "__init__.py"), "w") as f:
        pass
    
    # 获取所有proto文件
    proto_files = [f for f in os.listdir(proto_dir) if f.endswith(".proto")]
    
    for proto_file in proto_files:
        proto_path = os.path.join(proto_dir, proto_file)
        cmd = [
            "python", "-m", "grpc_tools.protoc",
            f"--proto_path={proto_dir}",
            f"--python_out={grpc_dir}",
            f"--grpc_python_out={grpc_dir}",
            proto_path
        ]
        
        print(f"生成gRPC代码: {proto_file}")
        subprocess.run(cmd, check=True)
    
    print("gRPC代码生成完成")

if __name__ == "__main__":
    main() 