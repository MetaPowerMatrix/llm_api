#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# app/tools/shop_category.py

import os
import json
import time
import logging
import hashlib
import requests
import argparse
from typing import Dict, List, Optional, Set
from datetime import datetime
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class JDDJShopCategoryManager:
    """京东到家店内分类管理工具"""

    def __init__(self):
        # API配置
        self.base_url = "https://openapi.jddj.com/djapi/pms/addShopCategory"
        self.data_dir = "/data/app/jd"
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 从环境变量加载配置
        self.app_key = os.getenv("JDDJ_APP_KEY")
        self.app_secret = os.getenv("JDDJ_APP_SECRET")
        
        if not self.app_key or not self.app_secret:
            raise ValueError("请在.env文件中设置JDDJ_APP_KEY和JDDJ_APP_SECRET")
        
        # 请求频率控制 (40次/分钟)
        self.max_requests_per_minute = 40
        self.request_timestamps = []
        self.request_interval = 60.0 / self.max_requests_per_minute
        
        # 分类名称和ID的映射，避免重复创建
        self.category_id_map = {}
    
    def wait_for_rate_limit(self):
        """等待直到可以发送下一个请求"""
        current_time = time.time()
        
        # 清理超过1分钟的时间戳
        self.request_timestamps = [ts for ts in self.request_timestamps 
                                  if current_time - ts < 60.0]
        
        # 如果已经达到限制，等待
        if len(self.request_timestamps) >= self.max_requests_per_minute:
            wait_time = 60.0 - (current_time - self.request_timestamps[0])
            if wait_time > 0:
                logger.info(f"达到请求频率限制，等待 {wait_time:.2f} 秒")
                time.sleep(wait_time)
                current_time = time.time()
        
        # 如果距离上次请求时间太短，等待
        if self.request_timestamps:
            time_since_last = current_time - self.request_timestamps[-1]
            if time_since_last < self.request_interval:
                wait_time = self.request_interval - time_since_last
                logger.info(f"请求间隔太短，等待 {wait_time:.2f} 秒")
                time.sleep(wait_time)
        
        # 记录当前请求时间
        self.request_timestamps.append(time.time())
    
    def load_token(self) -> Optional[str]:
        """从文件中加载token"""
        token_file = os.path.join(self.data_dir, "jd_auth.json")
        if not os.path.exists(token_file):
            logger.error("未找到token文件，请先运行授权流程")
            return None
            
        try:
            with open(token_file, "r", encoding="utf-8") as f:
                token_data = json.load(f)
                return token_data.get("token")
        except Exception as e:
            logger.error(f"读取token文件失败: {str(e)}")
            return None
    
    def generate_sign(self, params: Dict) -> str:
        """生成签名"""
        # 按参数名升序排列
        sorted_params = sorted(params.items())
        # 拼接参数
        param_str = "".join([f"{k}{v}" for k, v in sorted_params])
        # 添加app_secret
        sign_str = f"{self.app_secret}{param_str}{self.app_secret}"
        # MD5加密
        return hashlib.md5(sign_str.encode('utf-8')).hexdigest().upper()
    
    def add_shop_category(self, category_name: str, pid: int = 0) -> Optional[str]:
        """添加店内分类"""
        # 如果该分类已经创建过，直接返回ID
        if category_name in self.category_id_map:
            logger.info(f"分类 '{category_name}' 已存在，ID: {self.category_id_map[category_name]}")
            return self.category_id_map[category_name]
        
        token = self.load_token()
        if not token:
            return None
        
        try:
            # 等待频率限制
            self.wait_for_rate_limit()
            
            # 系统级参数
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            system_params = {
                "token": token,
                "app_key": self.app_key,
                "timestamp": timestamp,
                "format": "json",
                "v": "1.0",
                # 应用级参数
                "jd_param_json": json.dumps({"shopCategoryName": category_name, "pid": pid})
            }
            
            # 生成签名（只使用系统级参数）
            sign = self.generate_sign(system_params)
            
            # 完整请求参数
            params = {
                **system_params,
                "sign": sign,
            }
            
            logger.info(f"创建店内分类: {category_name}")
            response = requests.get(self.base_url, params=params)
            response.raise_for_status()
            
            result = response.json()
            
            if result.get("code") != "0":
                logger.error(f"创建店内分类失败: {result.get('msg')}")
                return None
            
            # 提取分类ID
            category_id = json.loads(result.get("data", {})).get("result", {}).get("id")
            
            if category_id:
                logger.info(f"创建店内分类成功, '{category_name}' ID: {category_id}")
                # 记录分类ID，避免重复创建
                self.category_id_map[category_name] = category_id
                return category_id
            else:
                logger.error("创建店内分类成功但未返回ID")
                return None
            
        except Exception as e:
            logger.error(f"创建店内分类时出错: {str(e)}")
            return None
    
    def load_products(self, file_path: str) -> List[Dict]:
        """加载商品数据"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                products = json.load(f)
            logger.info(f"从 {file_path} 加载了 {len(products)} 个商品")
            return products
        except Exception as e:
            logger.error(f"加载商品数据失败: {str(e)}")
            return []
    
    def save_results(self, results: List[Dict], output_file: str):
        """保存分类结果到文件"""
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            logger.info(f"分类结果已保存到: {output_file}")
        except Exception as e:
            logger.error(f"保存分类结果失败: {str(e)}")
    
    def process_products(self, database_file: str, output_file: str):
        """处理所有商品的分类"""
        # 加载商品数据
        products = self.load_products(database_file)
        if not products:
            logger.error("没有加载到商品数据，退出")
            return
        
        # 收集所有唯一的分类名称
        unique_categories = set()
        for product in products:
            category = product.get("category-1")
            if category:
                unique_categories.add(category)
        
        logger.info(f"找到 {len(unique_categories)} 个唯一分类")
        
        # 首先创建所有分类
        for category in unique_categories:
            self.add_shop_category(category)
        
        # 处理每个商品
        results = []
        total = len(products)
        
        for i, product in enumerate(products):
            product_id = product.get("_id", "")
            category = product.get("category-1", "")
            
            if not category:
                logger.warning(f"商品 {product_id} 没有分类信息，跳过")
                continue
            
            logger.info(f"处理商品 {i+1}/{total}: {product_id}")
            
            # 获取分类ID
            category_id = self.category_id_map.get(category)
            
            result = {
                "_id": product_id,
                "category_name": category,
                "category_id": category_id
            }
            
            results.append(result)
            
            # 每处理10个商品保存一次结果
            if (i + 1) % 10 == 0:
                self.save_results(results, output_file)
                logger.info(f"已保存 {i+1} 个商品的分类信息")
        
        # 最后保存一次完整结果
        self.save_results(results, output_file)
        logger.info(f"商品分类处理完成，共处理 {len(results)} 个商品")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="京东到家店内分类管理工具")
    parser.add_argument("--database", default="database_export.json",
                     help="数据库导出文件路径")
    parser.add_argument("--output", default="/data/app/jd/shop_category.json",
                     help="分类结果输出文件路径")
    
    args = parser.parse_args()
    
    try:
        manager = JDDJShopCategoryManager()
        logger.info("开始创建店内分类信息...")
        manager.process_products(args.database, args.output)
    except Exception as e:
        logger.error(f"程序执行出错: {str(e)}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())