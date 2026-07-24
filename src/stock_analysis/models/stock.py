"""
股票数据模型
"""
from dataclasses import dataclass


@dataclass
class Stock:
    """A股股票数据模型"""
    code: str  # 股票代码，如 "000001"
    name: str  # 股票名称，如 "平安银行"

    def __repr__(self):
        return f"Stock(code={self.code}, name={self.name})"