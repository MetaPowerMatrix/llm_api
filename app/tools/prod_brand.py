#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# app/tools/prod_classify.py

import os
import json
import time
import logging
import hashlib
import requests
import argparse
from typing import Dict, List, Optional
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

class JDDJProductBrandClassifier:
    """京东到家商品品牌分类工具"""

    def __init__(self):
        # API配置
        self.base_url = "https://openapi.jddj.com/djapi/pms/getSkuCateBrandBySkuName"
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
    
    def get_product_brand(self, product_name: str) -> Optional[Dict]:
        """获取商品的推荐类目和品牌"""
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
                "jd_param_json": json.dumps({"productName": product_name, "fields": [
                    "brand", "category"
                ]})
            }
            
            # 生成签名（只使用系统级参数）
            sign = self.generate_sign(system_params)
            
            # 完整请求参数
            params = {
                **system_params,
                "sign": sign,
            }
            
            logger.info(f"请求商品品牌信息: {product_name}")
            response = requests.get(self.base_url, params=params)
            response.raise_for_status()
            
            result = response.json()
            
            if result.get("code") != "0":
                logger.error(f"获取商品品牌信息失败: {result.get('msg')}")
                return None
            
            brand_data = json.loads(result.get("data", {})).get("result", {})
            logger.info(f"获取到商品 '{product_name}' 的品牌信息")
            
            return brand_data
            
        except Exception as e:
            logger.error(f"获取商品品牌时出错: {str(e)}")
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
        """保存品牌分类结果到文件"""
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            logger.info(f"品牌信息已保存到: {output_file}")
        except Exception as e:
            logger.error(f"保存品牌信息失败: {str(e)}")
    
    def process_products(self, database_file: str, output_file: str):
        """处理所有商品"""
        # 加载商品数据
        products = self.load_products(database_file)
        if not products:
            logger.error("没有加载到商品数据，退出")
            return
        
        # 处理每个商品
        results = []
        total = len(products)
        
        for i, product in enumerate(products):
            product_id = product.get("_id", "")
            product_title = product.get("title", "")
            
            if not product_title:
                logger.warning(f"商品 {product_id} 没有标题，跳过")
                continue
            
            logger.info(f"处理商品 {i+1}/{total}: {product_id}")
            brand_info = self.get_product_brand(product_title)
            
            result = {
                "_id": product_id,
                "title": product_title,
                "brand_info": brand_info.get("brandId", 0),
                "category_info": brand_info.get("categoryId", 0)
            }
            
            results.append(result)
            
            # 每处理10个商品保存一次结果
            if (i + 1) % 10 == 0:
                self.save_results(results, output_file)
                logger.info(f"已保存 {i+1} 个商品的品牌信息")
        
        # 最后保存一次完整结果
        self.save_results(results, output_file)
        logger.info(f"商品品牌分类完成，共处理 {len(results)} 个商品")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="京东到家商品品牌分类工具")
    parser.add_argument("--database", default="database_export.json",
                     help="数据库导出文件路径")
    parser.add_argument("--output", default="/data/app/jd/prod_brand.json",
                     help="商品品牌结果输出文件路径")
    
    args = parser.parse_args()
    
    try:
        classifier = JDDJProductBrandClassifier()
        logger.info("开始获取商品推荐类目和品牌信息...")
        classifier.process_products(args.database, args.output)
    except Exception as e:
        logger.error(f"程序执行出错: {str(e)}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())