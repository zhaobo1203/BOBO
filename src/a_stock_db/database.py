# -*- coding: utf-8 -*-
"""
A股数据库操作模块
使用SQLite存储股票基本信息（股票代码、股票名称）
"""

import sqlite3
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# 默认数据库路径
DEFAULT_DB_DIR = Path(__file__).parent.parent.parent / "data" / "a_stock_db"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "a_stock.db"


@dataclass
class DatabaseStats:
    """数据库统计信息"""
    total_count: int
    last_update_time: Optional[str]
    added_count: int = 0  # 新增数量
    removed_count: int = 0  # 移除数量


class AStockDatabase:
    """A股数据库管理类"""
    
    def __init__(self, db_path: Optional[Path] = None):
        """初始化数据库
        
        Args:
            db_path: 数据库文件路径，默认为 data/a_stock_db/a_stock.db
        """
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._ensure_db_dir()
        self._init_database()
    
    def _ensure_db_dir(self):
        """确保数据库目录存在"""
        db_dir = self.db_path.parent
        if not db_dir.exists():
            db_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"创建数据库目录: {db_dir}")
    
    def _init_database(self):
        """初始化数据库表结构"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # 创建股票信息表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stocks (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # 创建更新记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS update_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    total_count INTEGER,
                    added_count INTEGER DEFAULT 0,
                    removed_count INTEGER DEFAULT 0,
                    source TEXT
                )
            ''')
            # 创建索引
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_stocks_code ON stocks(code)
            ''')
            conn.commit()
            logger.info(f"数据库初始化完成: {self.db_path}")
    
    def get_stock_count(self) -> int:
        """获取股票总数"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM stocks")
            return cursor.fetchone()[0]
    
    def get_all_stocks(self) -> list[tuple[str, str]]:
        """获取所有股票信息
        
        Returns:
            股票列表，每个元素为 (股票代码, 股票名称)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT code, name FROM stocks ORDER BY code")
            return cursor.fetchall()
    
    def get_stock_by_code(self, code: str) -> Optional[tuple[str, str]]:
        """根据股票代码查询股票
        
        Args:
            code: 股票代码
            
        Returns:
            (股票代码, 股票名称) 或 None
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT code, name FROM stocks WHERE code = ?", (code,))
            result = cursor.fetchone()
            return result if result else None
    
    def get_stock_by_name(self, name: str) -> list[tuple[str, str]]:
        """根据股票名称查询股票（支持模糊查询）
        
        Args:
            name: 股票名称（支持模糊匹配）
            
        Returns:
            匹配的股票列表
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT code, name FROM stocks WHERE name LIKE ? ORDER BY code",
                (f"%{name}%",)
            )
            return cursor.fetchall()
    
    def search_by_name(self, name: str) -> list[dict]:
        """根据股票名称搜索股票（返回字典列表，兼容测试接口）
        
        Args:
            name: 股票名称（支持模糊匹配）
            
        Returns:
            匹配的股票字典列表 [{'code': ..., 'name': ...}]
        """
        results = self.get_stock_by_name(name)
        return [{'code': code, 'name': name} for code, name in results]
    
    def search_by_code(self, code: str) -> Optional[dict]:
        """根据股票代码搜索股票（返回字典，兼容测试接口）
        
        Args:
            code: 股票代码（精确匹配）
            
        Returns:
            匹配的股票字典 {'code': ..., 'name': ...} 或 None
        """
        result = self.get_stock_by_code(code)
        if result:
            return {'code': result[0], 'name': result[1]}
        return None
    
    def update_stocks(self, stocks: list[tuple[str, str]], source: str = "unknown") -> DatabaseStats:
        """更新股票数据（增量更新）
        
        Args:
            stocks: 股票列表，每个元素为 (股票代码, 股票名称)
            source: 数据来源
            
        Returns:
            更新统计信息
        """
        # 获取现有股票代码
        existing_codes = set()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT code FROM stocks")
            existing_codes = {row[0] for row in cursor.fetchall()}
        
        # 计算新增和移除
        new_codes = {code for code, _ in stocks}
        added_codes = new_codes - existing_codes
        # 只有数据源返回足够完整时才执行退市删除
        # 避免小范围数据源误删正常股票（阈值：至少4000只才算完整覆盖）
        removed_codes = set()
        if len(stocks) >= 4000:
            removed_codes = existing_codes - new_codes
        else:
            logger.warning(
                f"数据源返回{len(stocks)}只股票，不足4000只阈值，"
                f"跳过退市删除以避免误删正常股票"
            )
        
        # 获取新增的股票信息
        added_stocks = [(code, name) for code, name in stocks if code in added_codes]
        
        # 更新数据库
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 删除已退市的股票
            if removed_codes:
                cursor.executemany(
                    "DELETE FROM stocks WHERE code = ?",
                    [(code,) for code in removed_codes]
                )
            
            # 插入新股票（已存在的更新名称）
            for code, name in stocks:
                cursor.execute('''
                    INSERT INTO stocks (code, name, updated_at) 
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(code) DO UPDATE SET 
                        name = excluded.name,
                        updated_at = CURRENT_TIMESTAMP
                ''', (code, name))
            
            # 记录更新日志
            cursor.execute('''
                INSERT INTO update_log (total_count, added_count, removed_count, source)
                VALUES (?, ?, ?, ?)
            ''', (len(stocks), len(added_codes), len(removed_codes), source))
            
            conn.commit()
        
        # 获取最后更新时间
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT update_time FROM update_log ORDER BY id DESC LIMIT 1")
            last_update = cursor.fetchone()
            last_update_time = last_update[0] if last_update else None
        
        return DatabaseStats(
            total_count=len(stocks),
            last_update_time=last_update_time,
            added_count=len(added_codes),
            removed_count=len(removed_codes)
        )
    
    def get_stats(self) -> DatabaseStats:
        """获取数据库统计信息"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 获取股票总数
            cursor.execute("SELECT COUNT(*) FROM stocks")
            total_count = cursor.fetchone()[0]
            
            # 获取最后更新时间
            cursor.execute("SELECT update_time FROM update_log ORDER BY id DESC LIMIT 1")
            last_update = cursor.fetchone()
            last_update_time = last_update[0] if last_update else None
        
        return DatabaseStats(
            total_count=total_count,
            last_update_time=last_update_time
        )
    
    def get_recent_new_stocks(self, days: int = 7) -> list[tuple[str, str, str]]:
        """获取最近N天内新增的股票（数据校准用）
        
        Args:
            days: 往前追溯天数，默认7天
            
        Returns:
            新增股票列表，每个元素为 (股票代码, 股票名称, 创建时间)
        """
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT code, name, created_at FROM stocks WHERE created_at >= ? ORDER BY created_at DESC",
                (cutoff,)
            )
            return cursor.fetchall()
    
    def calibrate_with_data(self, stocks: list[tuple[str, str]], source: str = "calibration") -> DatabaseStats:
        """数据校准：用外部数据源补充遗漏的新股
        
        与 update_stocks 不同，此方法只添加不删除，专门用于校准遗漏的新股。
        适用于：主数据源更新后，用备用数据源补充可能遗漏的近期新股。
        
        Args:
            stocks: 股票列表，每个元素为 (股票代码, 股票名称)
            source: 数据来源标识
            
        Returns:
            校准统计信息（added_count为校准新增的数量）
        """
        existing_codes = {code for code, _ in self.get_all_stocks()}
        new_codes = {code for code, _ in stocks}
        added_codes = new_codes - existing_codes
        
        if not added_codes:
            logger.info("数据校准完成：无遗漏股票")
            stats = self.get_stats()
            return DatabaseStats(
                total_count=stats.total_count,
                last_update_time=stats.last_update_time,
                added_count=0,
                removed_count=0
            )
        
        # 记录校准新增的股票
        for code, name in stocks:
            if code in added_codes:
                logger.info(f"校准新增股票: {code} {name}")
        
        # 复用 update_stocks 进行插入（传一个较大的列表让它认为不足4000只从而跳过删除）
        # 更稳妥的方式：只传新增股票列表，确保不会触发删除逻辑
        added_stocks = [(code, name) for code, name in stocks if code in added_codes]
        # added_stocks 数量一定小于4000，update_stocks 会跳过删除
        result = self.update_stocks(added_stocks, source=source)
        
        total = self.get_stock_count()
        logger.info(f"数据校准完成：新增 {len(added_codes)} 只遗漏股票，当前总数 {total}")
        
        return DatabaseStats(
            total_count=total,
            last_update_time=result.last_update_time,
            added_count=len(added_codes),
            removed_count=0
        )
    
    def clear_all(self):
        """清空所有数据"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM stocks")
            cursor.execute("DELETE FROM update_log")
            conn.commit()
            logger.info("数据库已清空")


def main():
    """测试数据库模块"""
    db = AStockDatabase()
    
    # 测试插入数据
    test_stocks = [
        ("000001", "平安银行"),
        ("000002", "万科A"),
        ("600000", "浦发银行"),
    ]
    
    stats = db.update_stocks(test_stocks, source="test")
    print(f"更新完成: 总数={stats.total_count}, 新增={stats.added_count}, 移除={stats.removed_count}")
    
    # 查询所有股票
    stocks = db.get_all_stocks()
    print(f"\n当前股票列表 ({len(stocks)}只):")
    for code, name in stocks:
        print(f"  {code} | {name}")


if __name__ == "__main__":
    main()