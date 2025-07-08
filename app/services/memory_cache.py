import threading
from collections import deque

class MemoryCache:
    """
    内存缓存类，用于存储和访问聊天模型的历史聊天记录。
    按照每个聊天会话的session_id为key保存，仅保存最近的20条聊天记录。
    """
    def __init__(self):
        self.cache = {}  # 使用字典存储聊天记录，key为session_id，value为deque
        self.lock = threading.Lock()  # 线程锁，确保线程安全

    def add_message(self, session_id, message):
        """
        添加一条聊天记录到指定会话。
        :param session_id: 会话ID
        :param message: 聊天记录
        """
        with self.lock:
            if session_id not in self.cache:
                self.cache[session_id] = deque(maxlen=20)  # 使用deque限制最大长度为20
            self.cache[session_id].append(message)

    def get_messages(self, session_id):
        """
        获取指定会话的聊天记录。
        :param session_id: 会话ID
        :return: 聊天记录列表，如果会话不存在则返回空列表
        """
        with self.lock:
            return list(self.cache.get(session_id, deque()))

    def clear_session(self, session_id):
        """
        清除指定会话的聊天记录。
        :param session_id: 会话ID
        """
        with self.lock:
            if session_id in self.cache:
                del self.cache[session_id] 