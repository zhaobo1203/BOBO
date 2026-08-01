# -*- coding: utf-8 -*-
"""
股票匹配引擎模块
提供 MatchEngine 类，封装 Matcher 服务
"""

import logging
from typing import List, Dict, Optional, Tuple
from pathlib import Path

from .services.matcher import Matcher
from .models.stock import Stock
from .models.mention import MentionRecord

logger = logging.getLogger(__name__)


class MatchEngine:
    """股票匹配引擎
    
    负责加载股票数据、消息数据，执行匹配分析，并输出提及记录。
    
    使用流程:
        engine = MatchEngine()
        engine.load_stocks(stock_db_path)
        engine.load_messages(messages_db_path)
        engine.run_full_match()
        engine.save_mentions(output_db_path)
    """
    
    def __init__(self, stock_db_path: Optional[str] = None, messages_db_path: Optional[str] = None):
        """初始化匹配引擎
        
        Args:
            stock_db_path: A股数据库路径
            messages_db_path: 消息数据库路径
        """
        self.stock_db_path = stock_db_path
        self.messages_db_path = messages_db_path
        
        self._name_index: Dict[str, Stock] = {}
        self._code_index: Dict[str, Stock] = {}
        self._matcher: Optional[Matcher] = None
        self._mentions: List[MentionRecord] = []
        self._messages: List[Tuple] = []
        
        # 自动加载
        if stock_db_path:
            self.load_stocks(stock_db_path)
    
    @property
    def name_index(self) -> Dict[str, Stock]:
        """股票名称索引"""
        return self._name_index
    
    @property
    def code_index(self) -> Dict[str, Stock]:
        """股票代码索引"""
        return self._code_index
    
    @property
    def matcher(self) -> Optional[Matcher]:
        """匹配器实例"""
        return self._matcher
    
    def load_stocks(self, stock_db_path: Optional[str] = None) -> int:
        """加载股票数据
        
        Args:
            stock_db_path: A股数据库路径
            
        Returns:
            加载的股票数量
        """
        from .services.stock_loader import StockLoader
        
        path = stock_db_path or self.stock_db_path
        if not path:
            logger.warning("未指定股票数据库路径")
            return 0
        
        loader = StockLoader(Path(path))
        stocks = loader.load()
        
        self._name_index = {}
        self._code_index = {}
        
        for stock in stocks:
            self._name_index[stock.name] = stock
            self._code_index[stock.code] = stock
        
        logger.info(f"已加载 {len(stocks)} 只股票")
        
        # 创建匹配器
        self._matcher = Matcher(self._name_index, self._code_index)
        
        return len(stocks)
    
    def load_messages(self, messages_db_path: Optional[str] = None) -> int:
        """加载消息数据
        
        Args:
            messages_db_path: 消息数据库路径
            
        Returns:
            加载的消息数量
        """
        import sqlite3
        
        path = messages_db_path or self.messages_db_path
        if not path:
            logger.warning("未指定消息数据库路径")
            return 0
        
        self._messages = []
        
        try:
            with sqlite3.connect(path) as conn:
                cursor = conn.cursor()
                
                # 检查表是否存在
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='group_messages'
                """)
                if not cursor.fetchone():
                    logger.warning(f"消息数据库中未找到 group_messages 表: {path}")
                    return 0
                
                cursor.execute("""
                    SELECT id, sender_nickname, message_content, send_time, group_name
                    FROM group_messages
                    ORDER BY id
                """)
                
                self._messages = cursor.fetchall()
                logger.info(f"已加载 {len(self._messages)} 条消息")
                
        except sqlite3.Error as e:
            logger.error(f"加载消息失败: {e}")
        
        return len(self._messages)
    
    def match_message(self, message_id: int, content: str, 
                      sender: str, send_time: str, 
                      group_name: str) -> List[MentionRecord]:
        """匹配单条消息
        
        Args:
            message_id: 消息ID
            content: 消息内容
            sender: 发送者
            send_time: 发送时间
            group_name: 群名称
            
        Returns:
            匹配到的提及记录列表
        """
        if not self._matcher:
            logger.warning("匹配器未初始化，请先调用 load_stocks()")
            return []
        
        return self._matcher.match_message(
            message_id=message_id,
            content=content,
            sender=sender,
            send_time=send_time,
            group_name=group_name
        )
    
    def run_full_match(self, messages: Optional[List[Tuple]] = None) -> List[MentionRecord]:
        """执行全量匹配
        
        Args:
            messages: 可选的消息列表，格式为 (id, sender, content, time, group_name)
                     如果不提供，则使用已加载的消息
            
        Returns:
            所有提及记录列表
        """
        if not self._matcher:
            logger.warning("匹配器未初始化，请先调用 load_stocks()")
            return []
        
        msgs = messages or self._messages
        if not msgs:
            logger.warning("没有消息可匹配，请先调用 load_messages()")
            return []
        
        self._mentions = self._matcher.match_messages_batch(msgs)
        
        logger.info(f"全量匹配完成: {len(self._mentions)} 条提及记录")
        
        return self._mentions
    
    def save_mentions(self, output_db_path: str) -> int:
        """保存提及记录到数据库
        
        Args:
            output_db_path: 输出数据库路径
            
        Returns:
            保存的记录数量
        """
        from .services.storage import MentionStorage
        
        if not self._mentions:
            logger.warning("没有提及记录可保存")
            return 0
        
        storage = MentionStorage(Path(output_db_path))
        count = storage.save_mentions(self._mentions)
        
        logger.info(f"已保存 {count} 条提及记录到 {output_db_path}")
        
        return count
    
    def get_stats(self) -> Dict:
        """获取统计信息
        
        Returns:
            统计信息字典
        """
        return {
            'total_stocks': len(self._name_index),
            'total_messages': len(self._messages),
            'total_mentions': len(self._mentions),
        }