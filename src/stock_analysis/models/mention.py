"""
股票提及记录数据模型
"""
from dataclasses import dataclass


@dataclass
class MentionRecord:
    """股票提及记录 - 匹配结果"""
    id: int = 0
    message_id: int = 0  # 原始消息ID
    stock_code: str = ""  # 股票代码
    stock_name: str = ""  # 股票名称
    match_type: str = ""  # 匹配类型：name（名称匹配）或 code（代码匹配）
    sender: str = ""  # 发送人昵称
    message_content: str = ""  # 原始消息内容
    send_time: str = ""  # 消息发送时间
    group_name: str = ""  # 群名称

    def __repr__(self):
        return f"MentionRecord(stock={self.stock_code}:{self.stock_name}, sender={self.sender}, time={self.send_time})"