"""
A股数据加载与过滤服务
从a_stock.db加载股票数据，过滤掉指数和退市股
"""
import sqlite3
import logging
from typing import List

from ..config.settings import A_STOCK_DB_PATH, EXCLUDE_NAME_PATTERNS
from ..models.stock import Stock

logger = logging.getLogger(__name__)


class StockLoader:
    """A股数据加载器"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(A_STOCK_DB_PATH)
        self._stocks: List[Stock] = []
        self._name_index: dict = {}  # name -> Stock
        self._code_index: dict = {}  # code -> Stock
        self._loaded = False

    def load(self) -> List[Stock]:
        """加载并过滤A股数据"""
        if self._loaded:
            return self._stocks

        logger.info(f"开始加载A股数据，数据库路径: {self.db_path}")

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT code, name FROM stocks")
            all_rows = cursor.fetchall()
            conn.close()
        except Exception as e:
            logger.error(f"加载A股数据库失败: {e}")
            raise

        total_count = len(all_rows)
        logger.info(f"A股数据库原始记录数: {total_count}")

        # 过滤
        filtered_stocks = []
        excluded_count = 0
        for code, name in all_rows:
            if self._should_exclude(name):
                excluded_count += 1
                continue
            stock = Stock(code=code, name=name)
            filtered_stocks.append(stock)

        self._stocks = filtered_stocks

        # 构建索引
        self._name_index = {s.name: s for s in self._stocks}
        self._code_index = {s.code: s for s in self._stocks}

        self._loaded = True
        logger.info(
            f"A股数据加载完成: 原始{total_count}条, "
            f"过滤{excluded_count}条, 保留{len(self._stocks)}条"
        )

        return self._stocks

    def _should_exclude(self, name: str) -> bool:
        """判断是否应排除该股票"""
        for pattern in EXCLUDE_NAME_PATTERNS:
            if pattern in name:
                return True
        return False

    def get_all_stocks(self) -> List[Stock]:
        """获取所有已加载的股票"""
        if not self._loaded:
            self.load()
        return self._stocks

    def get_stock_by_name(self, name: str) -> Stock:
        """根据名称获取股票"""
        if not self._loaded:
            self.load()
        return self._name_index.get(name)

    def get_stock_by_code(self, code: str) -> Stock:
        """根据代码获取股票"""
        if not self._loaded:
            self.load()
        return self._code_index.get(code)

    def get_name_index(self) -> dict:
        """获取名称索引"""
        if not self._loaded:
            self.load()
        return self._name_index

    def get_code_index(self) -> dict:
        """获取代码索引"""
        if not self._loaded:
            self.load()
        return self._code_index

    def reload(self) -> tuple:
        """
        重新加载A股数据（用于数据更新后刷新索引）
        
        Returns:
            (old_count, new_count) 旧数量和新数量
        """
        old_count = len(self._stocks)
        self._loaded = False
        self._stocks = []
        self._name_index = {}
        self._code_index = {}
        self.load()
        new_count = len(self._stocks)
        logger.info(f"A股数据重新加载完成: {old_count}→{new_count}只")
        return (old_count, new_count)
