import os
import json
import requests
import logging
import hashlib
import time
import argparse
import sys
from typing import Dict, List, Optional, Any
from datetime import datetime
from dotenv import load_dotenv

# 加载.env文件
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class JDDJCategoryTool:
    def __init__(self):
        self.base_url = "https://openapi.jddj.com/djapi/api/queryChildCategoriesForOP"
        self.data_dir = "/data/app/jd"  # 修改为指定目录
        os.makedirs(self.data_dir, exist_ok=True)
        self.app_key = os.getenv("JDDJ_APP_KEY")
        self.app_secret = os.getenv("JDDJ_APP_SECRET")
        
        if not self.app_key or not self.app_secret:
            raise ValueError("请在.env文件中设置JDDJ_APP_KEY和JDDJ_APP_SECRET")
        
        # 请求频率控制
        self.max_requests_per_minute = 45
        self.request_timestamps = []
        self.request_interval = 60.0 / self.max_requests_per_minute  # 每次请求的最小间隔（秒）
        
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

    def get_categories(self, parent_id: str = "0", level: int = 1) -> List[Dict]:
        """获取指定父级ID下的子类目"""
        token = self.load_token()
        if not token:
            return []

        try:
            # 等待直到可以发送请求
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
                "jd_param_json": json.dumps({"id": parent_id, "fields": [
                    "ID", "CATEGORY_NAME", "CATEGORY_LEVEL",
                    "CHECK_UPC_STATUS", "WEIGHT_MARK", "PACKAGE_FEE_MARK", "LEAF"
                ]})
            }
            
            # 生成签名（只使用系统级参数）
            sign = self.generate_sign(system_params)
            
            # 完整的请求参数
            params = {
                **system_params,
                "sign": sign,
            }
            
            logger.info(f"请求参数: {json.dumps(params, ensure_ascii=False)}")
            response = requests.get(self.base_url, params=params)
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"响应结果: {json.dumps(result, ensure_ascii=False)}")
            
            if result.get("code") != "0":
                logger.error(f"获取类目失败: {result.get('msg')}")
                return []
                
            # 提取类目数据, parse data field for json
            categories = json.loads(result.get("data", {})).get("result", [])
            logger.info(f"获取到{level}级类目数量: {len(categories)}")
            
            # 递归获取子类目
            for category in categories:
                if level < 5 and category.get("leaf") != 1:  # 最多获取5级类目，且不是末级类目
                    category["children"] = self.get_categories(
                        str(category.get("id", "")),
                        level + 1
                    )
                    
            return categories
            
        except Exception as e:
            logger.error(f"获取类目时出错: {str(e)}")
            return []

    def save_categories(self, categories: List[Dict]):
        """保存类目信息到文件"""
        try:
            output_file = os.path.join(self.data_dir, "category.json")
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(categories, f, ensure_ascii=False, indent=2)
            logger.info(f"类目信息已保存到: {output_file}")
        except Exception as e:
            logger.error(f"保存类目信息失败: {str(e)}")

class DeepSeekClassifier:
    def __init__(self):
        self.data_dir = "/data/app/jd"  # 分类数据目录
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 请求频率控制
        self.max_requests_per_minute = 50
        self.request_timestamps = []
        self.request_interval = 60.0 / self.max_requests_per_minute  # 每次请求的最小间隔（秒）
        
        # API 配置
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("请在.env文件中设置DEEPSEEK_API_KEY")
        
        self.api_url = "https://api.deepseek.com/v1/chat/completions"
        
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
    
    def load_database_products(self, file_path: str) -> List[Dict]:
        """加载数据库导出的产品信息"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                products = json.load(f)
            logger.info(f"从 {file_path} 加载了 {len(products)} 个产品")
            return products
        except Exception as e:
            logger.error(f"加载产品数据失败: {str(e)}")
            return []
    
    def load_categories(self, file_path: str) -> List[Dict]:
        """加载分类信息"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                categories = json.load(f)
            logger.info(f"从 {file_path} 加载了分类信息")
            return categories
        except Exception as e:
            logger.error(f"加载分类信息失败: {str(e)}")
            return []
    
    def extract_health_categories(self, categories: List[Dict]) -> List[Dict]:
        """提取医疗保健下的计生情趣分类及子分类"""
        health_categories = []
        
        # 递归查找医疗保健类别
        def find_health_and_jisheng(cats, path=None):
            if path is None:
                path = []
            
            for cat in cats:
                current_path = path + [cat.get("categoryName", "")]
                
                # 检查是否是医疗保健
                if "医疗保健" in cat.get("categoryName", ""):
                    # 继续查找计生情趣
                    if "children" in cat:
                        find_jisheng(cat["children"], current_path)
                
                # 继续向下递归查找医疗保健
                if "children" in cat:
                    find_health_and_jisheng(cat["children"], current_path)
        
        # 在医疗保健下查找计生情趣
        def find_jisheng(cats, path):
            for cat in cats:
                current_path = path + [cat.get("categoryName", "")]
                
                # 检查是否是计生情趣
                if "计生情趣" in cat.get("categoryName", ""):
                    # 将这个分类和所有子分类添加到结果中
                    flat_cat = self.flatten_category(cat, current_path)
                    health_categories.append(flat_cat)
                    
                    # 添加所有子分类
                    if "children" in cat:
                        extract_sub_categories(cat["children"], current_path)
                
                # 继续向下递归查找计生情趣
                if "children" in cat:
                    find_jisheng(cat["children"], current_path)
        
        # 提取子分类
        def extract_sub_categories(cats, path):
            for cat in cats:
                current_path = path + [cat.get("categoryName", "")]
                flat_cat = self.flatten_category(cat, current_path)
                health_categories.append(flat_cat)
                
                if "children" in cat:
                    extract_sub_categories(cat["children"], current_path)
        
        find_health_and_jisheng(categories)
        logger.info(f"提取了 {len(health_categories)} 个医疗保健相关分类")
        return health_categories
    
    def flatten_category(self, category: Dict, path: List[str]) -> Dict:
        """将分类扁平化，添加路径信息"""
        return {
            "id": category.get("id", ""),
            "categoryName": category.get("categoryName", ""),
            "path": " > ".join(path),
            "categoryLevel": category.get("categoryLevel", 0),
            "leaf": category.get("leaf", 0)
        }
    
    def classify_product(self, product: Dict, categories: List[Dict]) -> Dict:
        """使用DeepSeek API对产品进行分类"""
        title = product.get("title", "")
        if not title:
            logger.warning(f"产品 {product.get('_id', '未知')} 没有标题，跳过")
            return {"_id": product.get("_id", ""), "category": None}
        
        # 等待频率限制
        self.wait_for_rate_limit()
        
        # 构建分类列表字符串
        categories_text = "\n".join([
            f"ID: {cat['id']}, 名称: {cat['categoryName']}, 路径: {cat['path']}"
            for cat in categories
        ])
        
        # 构建提示词
        prompt = f"""请根据产品标题，选择最合适的京东到家分类ID。只需要返回一个最合适的分类ID，不需要其他解释。

产品标题: {title}

可选分类:
{categories_text}

请直接返回最匹配的一个分类ID（只需数字）:"""
        
        try:
            # 调用DeepSeek API
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            data = {
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 10
            }
            
            response = requests.post(self.api_url, headers=headers, json=data)
            response.raise_for_status()
            
            result = response.json()
            category_id = result["choices"][0]["message"]["content"].strip()
            
            # 尝试提取数字ID
            import re
            id_match = re.search(r'\d+', category_id)
            if id_match:
                category_id = id_match.group(0)
            
            logger.info(f"产品 {product.get('_id', '')} ({title}) 分类为: {category_id}")
            
            # 查找完整的分类信息
            category_info = next((cat for cat in categories if str(cat['id']) == str(category_id)), None)
            
            return {
                "_id": product.get("_id", ""),
                "title": title,
                "category_id": category_id,
                "category_info": category_info
            }
            
        except Exception as e:
            logger.error(f"分类产品 {product.get('_id', '')} 失败: {str(e)}")
            return {"_id": product.get("_id", ""), "category": None, "error": str(e)}
    
    def classify_products(self, database_file: str, category_file: str, output_file: str):
        """对所有产品进行分类并保存结果"""
        # 加载产品数据
        products = self.load_database_products(database_file)
        if not products:
            logger.error("没有加载到产品数据，退出")
            return
        
        # 加载分类数据
        all_categories = self.load_categories(category_file)
        if not all_categories:
            logger.error("没有加载到分类数据，退出")
            return
        
        # 提取医疗保健下的计生情趣分类
        health_categories = self.extract_health_categories(all_categories)
        if not health_categories:
            logger.error("没有找到医疗保健相关分类，退出")
            return
        
        # 对每个产品进行分类
        results = []
        total = len(products)
        
        for i, product in enumerate(products):
            logger.info(f"正在处理产品 {i+1}/{total}: {product.get('_id', '')}")
            result = self.classify_product(product, health_categories)
            results.append(result)
            
            # 每处理10个产品保存一次结果，以防程序中断
            if (i + 1) % 10 == 0:
                self.save_results(results, output_file)
                logger.info(f"已保存 {i+1} 个产品的分类结果")
        
        # 最后保存一次完整结果
        self.save_results(results, output_file)
        logger.info(f"产品分类完成，共处理 {len(results)} 个产品")
    
    def save_results(self, results: List[Dict], output_file: str):
        """保存分类结果到文件"""
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            logger.info(f"分类结果已保存到: {output_file}")
        except Exception as e:
            logger.error(f"保存分类结果失败: {str(e)}")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="京东到家工具")
    parser.add_argument("command", choices=["category", "classify"],
                      help="执行的命令: category (获取分类), classify (分类产品)")
    parser.add_argument("--database", default="database_export.json",
                      help="数据库导出文件路径")
    parser.add_argument("--output", default="/data/app/jd/prod_category.json",
                      help="产品分类结果输出文件路径")
    
    args = parser.parse_args()
    
    if args.command == "category":
        tool = JDDJCategoryTool()
        logger.info("开始获取京东到家商品类目...")
        
        # 从根类目开始获取
        categories = tool.get_categories()
        
        if categories:
            tool.save_categories(categories)
            logger.info("类目获取完成")
        else:
            logger.error("获取类目失败")
    
    elif args.command == "classify":
        classifier = DeepSeekClassifier()
        category_file = os.path.join("/data/app/jd", "category.json")
        
        if not os.path.exists(category_file):
            logger.error(f"分类文件 {category_file} 不存在，请先运行 'python tools.py category' 获取分类")
            sys.exit(1)
        
        logger.info("开始对产品进行分类...")
        classifier.classify_products(args.database, category_file, args.output)

if __name__ == "__main__":
    main()
