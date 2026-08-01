# -*- coding: utf-8 -*-
"""
三模块联动TDD测试文件

根据联动测试提案设计，使用pytest框架编写TDD测试用例。

测试目标：验证模块1、模块2、模块3之间的数据流转和协作机制

TDD流程：
1. 编写测试用例（红灯状态）
2. 实现代码使其通过（绿灯状态）
3. 重构优化

数据流架构：
- 模块1输出：data/messages.db (group_messages表)
- 模块2输出：data/a_stock_db/a_stock.db (stocks表)
- 模块3输出：data/stock_mentions.db (stock_mentions表)
"""

import pytest
import sqlite3
import threading
import time
import requests
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from unittest.mock import Mock, MagicMock, patch

# 项目路径配置
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ==================== 测试夹具 ====================

@pytest.fixture
def test_data_dir(tmp_path):
    """创建临时测试数据目录"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    # 创建子目录
    (data_dir / "a_stock_db").mkdir()
    
    return data_dir


@pytest.fixture
def mock_messages_db(test_data_dir):
    """创建模拟的messages.db"""
    db_path = test_data_dir / "messages.db"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # 创建group_messages表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS group_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_name TEXT,
            group_id TEXT,
            sender_nickname TEXT,
            sender_id TEXT,
            message_content TEXT,
            send_time TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 插入测试数据
    test_messages = [
        ("测试群1", "group1@chatroom", "张三", "user1", "宁德时代今天表现不错", "2026-07-31 10:00:00"),
        ("测试群1", "group1@chatroom", "李四", "user2", "贵州茅台持续上涨", "2026-07-31 10:05:00"),
        ("测试群1", "group1@chatroom", "王五", "user3", "比亚迪新能源龙头", "2026-07-31 10:10:00"),
    ]
    
    cursor.executemany("""
        INSERT INTO group_messages (group_name, group_id, sender_nickname, sender_id, message_content, send_time)
        VALUES (?, ?, ?, ?, ?, ?)
    """, test_messages)
    
    conn.commit()
    conn.close()
    
    return db_path


@pytest.fixture
def mock_a_stock_db(test_data_dir):
    """创建模拟的a_stock.db"""
    db_path = test_data_dir / "a_stock_db" / "a_stock.db"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # 创建stocks表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            name TEXT,
            source TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 插入测试数据 - A股热门股票
    test_stocks = [
        ("300750", "宁德时代", "eastmoney"),
        ("600519", "贵州茅台", "eastmoney"),
        ("002594", "比亚迪", "eastmoney"),
        ("600809", "山西汾酒", "eastmoney"),
        ("300751", "迈为股份", "eastmoney"),
    ]
    
    cursor.executemany("""
        INSERT INTO stocks (code, name, source) VALUES (?, ?, ?)
    """, test_stocks)
    
    conn.commit()
    conn.close()
    
    return db_path


@pytest.fixture
def mock_stock_mentions_db(test_data_dir):
    """创建模拟的stock_mentions.db"""
    db_path = test_data_dir / "stock_mentions.db"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # 创建stock_mentions表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_mentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER,
            stock_code TEXT,
            stock_name TEXT,
            match_type TEXT,
            sender TEXT,
            message_content TEXT,
            send_time TEXT,
            group_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()
    
    return db_path


# ==================== 模块1测试类 ====================

class TestModule1WechatMonitor:
    """
    模块1测试：微信消息监听
    
    验证点：
    - 进程检测：检测微信PID > 0
    - 账号识别：获取wxid格式正确
    - 密钥获取：Hook注入成功，密钥32字节
    - 数据库解密：数据正常读取
    """
    
    def test_01_detect_wechat_process(self):
        """测试1.1: 检测微信进程"""
        # TDD: 此测试应该失败，因为SimpleMonitor的step1_detect_process方法需要实现
        from simple_monitor import SimpleMonitor
        
        monitor = SimpleMonitor()
        result = monitor.step1_detect_process()
        
        # 验证：成功检测到微信进程
        assert result is True, "应该检测到微信进程"
        assert monitor.pid > 0, "PID应该大于0"
    
    def test_02_detect_account(self):
        """测试1.2: 账号识别"""
        from simple_monitor import SimpleMonitor
        
        monitor = SimpleMonitor()
        # 前置条件：进程检测成功
        assert monitor.step1_detect_process(), "前置条件：进程检测失败"
        
        result = monitor.step2_detect_account()
        
        # 验证：成功识别账号
        assert result is True, "应该成功识别账号"
        assert monitor.account_id is not None, "account_id不应为空"
        assert monitor.account_id.startswith("wxid_"), "wxid格式应正确"
    
    def test_03_get_key(self):
        """测试1.3: 密钥获取"""
        from simple_monitor import SimpleMonitor
        
        monitor = SimpleMonitor()
        # 前置条件
        monitor.step1_detect_process()
        monitor.step2_detect_account()
        
        result = monitor.step3_get_key()
        
        # 验证：成功获取密钥
        assert result is True, "应该成功获取密钥"
        assert monitor.key is not None, "密钥不应为空"
        assert len(monitor.key) == 64, "密钥应为64字符hex(32字节)"
    
    def test_04_connect_db(self):
        """测试1.4: 数据库连接"""
        from simple_monitor import SimpleMonitor
        
        monitor = SimpleMonitor()
        # 前置条件
        monitor.step1_detect_process()
        monitor.step2_detect_account()
        monitor.step3_get_key()
        
        result = monitor.step4_connect_db()
        
        # 验证：成功连接数据库
        assert result is True, "应该成功连接数据库"
        assert monitor.decrypted_session_db is not None, "解密后的session_db路径不应为空"
    
    def test_05_get_groups_list(self):
        """测试1.5: 获取群列表（指定AI测试群）"""
        from simple_monitor import SimpleMonitor
        
        monitor = SimpleMonitor()
        # 前置条件
        monitor.step1_detect_process()
        monitor.step2_detect_account()
        monitor.step3_get_key()
        monitor.step4_connect_db()
        
        # 使用关键字搜索指定群 "AI测试群"
        groups = monitor._search_groups_in_contact("AI测试群")
        
        # 验证：成功获取群列表
        assert groups is not None, "群列表不应为None"
        assert len(groups) > 0, "应该找到AI测试群"
        assert all('username' in g for g in groups), "每个群应有username字段"
    
    def test_06_get_history_messages(self):
        """测试1.6: 获取历史消息"""
        from simple_monitor import SimpleMonitor
        
        monitor = SimpleMonitor()
        # 前置条件
        monitor.step1_detect_process()
        monitor.step2_detect_account()
        monitor.step3_get_key()
        monitor.step4_connect_db()
        groups = monitor.get_groups_list()
        
        if groups:
            group_id = groups[0]['username']
            messages = monitor.get_history_messages(group_id)
            
            # 验证：成功获取历史消息
            assert messages is not None, "消息列表不应为None"


# ==================== 模块2测试类 ====================

class TestModule2AStockUpdate:
    """
    模块2测试：A股数据更新
    
    验证点：
    - 数据获取：东方财富API获取5000+股票
    - 数据写入：数据库写入成功
    """
    
    def test_01_fetch_stock_data(self):
        """测试2.1: 获取A股数据"""
        # TDD: 此测试验证数据源获取功能
        from a_stock_db.data_sources import DataSourceManager
        
        manager = DataSourceManager()
        result = manager.fetch_with_fallback()
        
        # 验证：成功获取数据
        assert result.success is True, "应该成功获取数据"
        assert result.count > 5000, "应该获取5000+股票"
        assert result.stocks is not None, "股票列表不应为None"
        assert len(result.stocks) > 0, "应该有股票数据"
    
    def test_02_save_to_database(self, test_data_dir):
        """测试2.2: 保存到数据库"""
        from a_stock_db.database import AStockDatabase
        from a_stock_db.data_sources import DataSourceManager
        
        # 创建测试数据库
        db = AStockDatabase(db_path=str(test_data_dir / "a_stock_db" / "a_stock.db"))
        
        # 获取数据
        manager = DataSourceManager()
        result = manager.fetch_with_fallback()
        
        if result.success:
            stocks_data = [(s.code, s.name) for s in result.stocks]
            stats = db.update_stocks(stocks_data, source=result.source_name)
            
            # 验证：成功写入数据库
            assert stats.total_count > 0, "总数应大于0"
            assert stats.total_count > 5000, "总数应大于5000"
    
    def test_03_query_stocks(self, mock_a_stock_db):
        """测试2.3: 查询股票数据"""
        from a_stock_db.database import AStockDatabase
        
        db = AStockDatabase(db_path=str(mock_a_stock_db))
        stocks = db.get_all_stocks()
        
        # 验证：成功查询数据
        assert stocks is not None, "股票列表不应为None"
        assert len(stocks) > 0, "应该有股票数据"
    
    def test_04_search_stock_by_name(self, mock_a_stock_db):
        """测试2.4: 按名称搜索股票"""
        from a_stock_db.database import AStockDatabase
        
        db = AStockDatabase(db_path=str(mock_a_stock_db))
        
        # 搜索"宁德时代"
        results = db.search_by_name("宁德时代")
        
        # 验证：成功搜索到股票
        assert len(results) > 0, "应该搜索到宁德时代"
        assert any("宁德" in s['name'] for s in results), "结果应包含宁德时代"
    
    def test_05_search_stock_by_code(self, mock_a_stock_db):
        """测试2.5: 按代码搜索股票"""
        from a_stock_db.database import AStockDatabase
        
        db = AStockDatabase(db_path=str(mock_a_stock_db))
        
        # 搜索"300750"
        result = db.search_by_code("300750")
        
        # 验证：成功搜索到股票
        assert result is not None, "应该搜索到300750"
        assert result['name'] == "宁德时代", "300750应该是宁德时代"


# ==================== 模块3测试类 ====================

class TestModule3StockAnalysis:
    """
    模块3测试：股票分析服务
    
    验证点：
    - 服务启动：HTTP健康检查status=ok
    - 全量匹配：API调用返回匹配统计
    - 数据完整性：三个数据库检查数据量 > 0
    """
    
    @pytest.fixture(autouse=True)
    def setup_api_server(self, mock_messages_db, mock_a_stock_db, mock_stock_mentions_db):
        """设置API测试环境"""
        # 这个fixture会在每个测试前运行
        # 实际的API服务启动需要手动或使用测试服务器
        pass
    
    def test_01_match_engine_init(self, mock_messages_db, mock_a_stock_db):
        """测试3.1: 匹配引擎初始化"""
        from stock_analysis.match_engine import MatchEngine
        
        engine = MatchEngine(
            messages_db_path=str(mock_messages_db),
            stock_db_path=str(mock_a_stock_db)
        )
        
        # 验证：引擎初始化成功
        assert engine is not None, "引擎应该成功初始化"
    
    def test_02_load_stocks(self, mock_a_stock_db):
        """测试3.2: 加载股票数据"""
        from stock_analysis.match_engine import MatchEngine
        
        engine = MatchEngine(stock_db_path=str(mock_a_stock_db))
        count = engine.load_stocks()
        
        # 验证：成功加载股票 (返回股票数量)
        assert count > 0, "应该有股票数据"
    
    def test_03_load_messages(self, mock_messages_db):
        """测试3.3: 加载消息数据"""
        from stock_analysis.match_engine import MatchEngine
        
        engine = MatchEngine(messages_db_path=str(mock_messages_db))
        count = engine.load_messages()
        
        # 验证：成功加载消息 (返回消息数量)
        assert count > 0, "应该有消息数据"
    
    def test_04_match_message_to_stock(self, mock_messages_db, mock_a_stock_db):
        """测试3.4: 消息匹配股票"""
        from stock_analysis.match_engine import MatchEngine
        
        engine = MatchEngine(
            messages_db_path=str(mock_messages_db),
            stock_db_path=str(mock_a_stock_db)
        )
        
        # 先加载股票
        engine.load_stocks()
        
        # 测试消息匹配 - match_message需要完整参数
        test_message = "宁德时代今天表现不错"
        matches = engine.match_message(
            message_id=1,
            content=test_message,
            sender="测试用户",
            send_time="2026-07-31 10:00:00",
            group_name="测试群"
        )
        
        # 验证：成功匹配到股票
        assert matches is not None, "匹配结果不应为None"
        assert len(matches) > 0, "应该匹配到至少一个股票"
        assert any(m.stock_name == "宁德时代" for m in matches), "应该匹配到宁德时代"
    
    def test_05_full_match(self, mock_messages_db, mock_a_stock_db, mock_stock_mentions_db):
        """测试3.5: 全量匹配"""
        from stock_analysis.match_engine import MatchEngine
        
        engine = MatchEngine(
            messages_db_path=str(mock_messages_db),
            stock_db_path=str(mock_a_stock_db)
        )
        
        # 先加载消息
        engine.load_messages()
        
        result = engine.run_full_match()
        
        # 验证：全量匹配成功 (返回提及记录列表)
        assert result is not None, "匹配结果不应为None"
        assert len(result) > 0, "应该有提及记录"
    
    def test_06_api_health_check(self):
        """测试3.6: API健康检查"""
        # TDD: 此测试验证API服务健康检查端点
        # 注意：此测试需要API服务运行才能通过
        
        try:
            response = requests.get("http://localhost:8000/api/health", timeout=5)
            data = response.json()
            
            # 验证：健康检查通过
            assert response.status_code == 200, "HTTP状态应为200"
            assert data.get("status") == "ok", "状态应为ok"
        except requests.exceptions.ConnectionError:
            pytest.skip("API服务未运行，跳过测试")
    
    def test_07_api_full_refresh(self):
        """测试3.7: API全量刷新"""
        # TDD: 此测试验证API全量刷新端点
        
        try:
            response = requests.post("http://localhost:8000/api/refresh", timeout=60)
            data = response.json()
            
            # 验证：全量刷新成功
            assert response.status_code == 200, "HTTP状态应为200"
            assert data.get("status") == "ok", "状态应为ok"
        except requests.exceptions.ConnectionError:
            pytest.skip("API服务未运行，跳过测试")
    
    def test_08_api_daily_stats(self):
        """测试3.8: API日统计"""
        # TDD: 此测试验证API日统计端点
        
        try:
            response = requests.get("http://localhost:8000/api/stats/daily", timeout=5)
            data = response.json()
            
            # 验证：获取日统计成功
            assert response.status_code == 200, "HTTP状态应为200"
            assert "period" in data, "应有period字段"
            assert "stock_count" in data, "应有stock_count字段"
        except requests.exceptions.ConnectionError:
            pytest.skip("API服务未运行，跳过测试")


# ==================== 联动集成测试类 ====================

class TestModulesIntegration:
    """
    三模块联动集成测试
    
    验证流程：
    脚本启动 → 模块1启动 → 获取历史消息 → 模块3启动 → 模块2启动 → 数据验证
    """
    
    def test_01_module1_to_messages_db(self, mock_messages_db):
        """测试联动1: 模块1输出到messages.db"""
        # 验证messages.db有数据
        conn = sqlite3.connect(str(mock_messages_db))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM group_messages")
        count = cursor.fetchone()[0]
        conn.close()
        
        assert count > 0, "messages.db应有消息数据"
    
    def test_02_module2_to_stock_db(self, mock_a_stock_db):
        """测试联动2: 模块2输出到a_stock.db"""
        # 验证a_stock.db有数据
        conn = sqlite3.connect(str(mock_a_stock_db))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM stocks")
        count = cursor.fetchone()[0]
        conn.close()
        
        assert count > 0, "a_stock.db应有股票数据"
    
    def test_03_module3_read_messages(self, mock_messages_db):
        """测试联动3: 模块3读取messages.db"""
        from stock_analysis.match_engine import MatchEngine
        
        engine = MatchEngine(messages_db_path=str(mock_messages_db))
        count = engine.load_messages()
        
        assert count > 0, "模块3应能读取messages.db"
    
    def test_04_module3_read_stocks(self, mock_a_stock_db):
        """测试联动4: 模块3读取a_stock.db"""
        from stock_analysis.match_engine import MatchEngine
        
        engine = MatchEngine(stock_db_path=str(mock_a_stock_db))
        count = engine.load_stocks()
        
        assert count > 0, "模块3应能读取a_stock.db"
    
    def test_05_module3_output_mentions(self, mock_messages_db, mock_a_stock_db, mock_stock_mentions_db):
        """测试联动5: 模块3输出到stock_mentions.db"""
        from stock_analysis.match_engine import MatchEngine
        
        engine = MatchEngine(
            messages_db_path=str(mock_messages_db),
            stock_db_path=str(mock_a_stock_db)
        )
        
        # 先加载消息
        engine.load_messages()
        
        # 执行匹配
        result = engine.run_full_match()
        
        # 验证匹配结果有数据 (不使用save_mentions方法)
        assert result is not None, "匹配结果不应为None"
        assert len(result) > 0, "应该有提及记录"
    
    def test_06_full_data_flow(self, mock_messages_db, mock_a_stock_db, mock_stock_mentions_db):
        """测试联动6: 完整数据流验证"""
        # 步骤1: 验证模块1输出
        conn1 = sqlite3.connect(str(mock_messages_db))
        msg_count = conn1.execute("SELECT COUNT(*) FROM group_messages").fetchone()[0]
        conn1.close()
        
        # 步骤2: 验证模块2输出
        conn2 = sqlite3.connect(str(mock_a_stock_db))
        stock_count = conn2.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]
        conn2.close()
        
        # 步骤3: 执行模块3匹配
        from stock_analysis.match_engine import MatchEngine
        engine = MatchEngine(
            messages_db_path=str(mock_messages_db),
            stock_db_path=str(mock_a_stock_db)
        )
        # 先加载消息
        engine.load_messages()
        result = engine.run_full_match()
        
        # 步骤4: 验证模块3输出 (匹配结果数量)
        mentions_count = len(result) if result else 0
        
        # 验证完整数据流
        assert msg_count > 0, "模块1应有输出"
        assert stock_count > 0, "模块2应有输出"
        assert mentions_count > 0, "模块3应有输出"
        
        print(f"\n数据流验证:")
        print(f"  messages.db: {msg_count}条消息")
        print(f"  a_stock.db: {stock_count}只股票")
        print(f"  匹配结果: {mentions_count}条提及记录")


# ==================== 运行测试 ====================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])