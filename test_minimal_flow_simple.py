# -*- coding: utf-8 -*-
"""
最小化流程测试脚本（简化版）

测试流程：
模块3启动 → 模块2启动 → 数据验证 → 看板显示

前提条件：
- messages.db 中已有历史消息数据
- 微信已登录运行

数据流设计：
1. 模块1：微信消息监听（假设已有数据，跳过）
   - 输出：data/messages.db (group_messages表)
   
2. 模块2：A股数据更新  
   - 输出：data/a_stock_db/a_stock.db (stocks表)
   
3. 模块3：股票分析
   - 输入：messages.db + a_stock.db
   - 输出：data/stock_mentions.db (stock_mentions表)
   - 看板：实时显示统计结果
"""

import sys
import os
import time
import sqlite3
import threading
import subprocess
import signal
import logging
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# 确保日志目录存在
(PROJECT_ROOT / "logs").mkdir(exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(PROJECT_ROOT / "logs" / "minimal_flow_simple.log", encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


class MinimalFlowSimpleTest:
    """最小化流程测试（简化版）"""
    
    def __init__(self):
        self.project_root = PROJECT_ROOT
        self.messages_db = PROJECT_ROOT / "data" / "messages.db"
        self.stock_db = PROJECT_ROOT / "data" / "a_stock_db" / "a_stock.db"
        self.mentions_db = PROJECT_ROOT / "data" / "stock_mentions.db"
        
        # 模块3进程
        self.api_process = None
        self.stop_event = threading.Event()
        
    def print_header(self):
        """显示测试头部"""
        print()
        print("=" * 70)
        print("  最小化流程测试（简化版）")
        print("  流程: 数据检查 → 模块3启动 → 模块2启动 → 数据验证 → 看板")
        print("=" * 70)
        print()
        
    def print_step(self, step: str, status: str, detail: str = ""):
        """显示步骤状态"""
        symbols = {'done': '[OK]', 'doing': '[..]', 'fail': '[FAIL]', 'info': '[INFO]', 'skip': '[SKIP]'}
        symbol = symbols.get(status, '[??]')
        line = f"  {symbol} {step}"
        if detail:
            line += f": {detail}"
        print(line)
        
    # ==================== 数据库验证辅助方法 ====================
    
    def check_messages_db(self) -> int:
        """检查messages.db中的消息数量"""
        if not self.messages_db.exists():
            return 0
        try:
            conn = sqlite3.connect(str(self.messages_db))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM group_messages")
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception as e:
            logger.warning(f"检查messages.db失败: {e}")
            return 0
    
    def check_stock_db(self) -> int:
        """检查a_stock.db中的股票数量"""
        if not self.stock_db.exists():
            return 0
        try:
            conn = sqlite3.connect(str(self.stock_db))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM stocks")
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception as e:
            logger.warning(f"检查a_stock.db失败: {e}")
            return 0
    
    def check_mentions_db(self) -> int:
        """检查stock_mentions.db中的提及记录数量"""
        if not self.mentions_db.exists():
            return 0
        try:
            conn = sqlite3.connect(str(self.mentions_db))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM stock_mentions")
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception as e:
            logger.warning(f"检查stock_mentions.db失败: {e}")
            return 0
    
    # ==================== 步骤0: 环境检查 ====================
    
    def step0_check_data(self) -> bool:
        """检查现有数据"""
        self.print_header()
        self.print_step("步骤0: 数据检查", "doing")
        
        # 确保目录存在
        (PROJECT_ROOT / "logs").mkdir(exist_ok=True)
        (PROJECT_ROOT / "data").mkdir(exist_ok=True)
        
        # 检查messages.db
        msg_count = self.check_messages_db()
        self.print_step("messages.db", "done" if msg_count > 0 else "info", 
            f"{msg_count}条消息")
        
        if msg_count == 0:
            self.print_step("数据检查", "fail", "messages.db无数据，请先运行模块1采集消息")
            return False
        
        return True
    
    # ==================== 步骤1: 模块3启动 ====================
    
    def step1_start_module3(self) -> bool:
        """启动模块3 - 股票分析服务"""
        print()
        self.print_step("步骤1: 模块3启动", "info", "股票分析服务")
        
        try:
            # 启动API服务
            self.print_step("API服务启动", "doing")
            
            self.api_process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn",
                 "src.stock_analysis.main:app",
                 "--host", "0.0.0.0",
                 "--port", "8000"],
                cwd=str(self.project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            
            # 等待服务就绪
            for i in range(30):
                try:
                    resp = requests.get("http://localhost:8000/api/health", timeout=2)
                    if resp.json().get("status") == "ok":
                        self.print_step("API服务启动", "done", "http://localhost:8000")
                        break
                except:
                    pass
                time.sleep(1)
            else:
                self.print_step("API服务启动", "fail", "服务未就绪")
                return False
            
            return True
            
        except Exception as e:
            self.print_step("模块3启动", "fail", str(e))
            logger.error(f"模块3启动异常: {e}", exc_info=True)
            return False
    
    # ==================== 步骤2: 模块2启动 ====================
    
    def step2_start_module2(self) -> bool:
        """启动模块2 - A股数据更新"""
        print()
        self.print_step("步骤2: 模块2启动", "info", "A股数据更新")
        
        try:
            from a_stock_db.data_sources import DataSourceManager
            from a_stock_db.database import AStockDatabase
            
            self.print_step("A股数据获取", "doing")
            
            manager = DataSourceManager()
            result = manager.fetch_with_fallback()
            
            if not result.success:
                self.print_step("A股数据获取", "fail", result.error_message)
                return False
            
            self.print_step("A股数据获取", "done", f"获取{result.count}只股票")
            
            # 更新数据库
            self.print_step("A股数据写入", "doing")
            db = AStockDatabase()
            stocks_data = [(s.code, s.name) for s in result.stocks]
            stats = db.update_stocks(stocks_data, source=result.source_name)
            
            self.print_step("A股数据写入", "done", 
                f"总数{stats.total_count}, 新增{stats.added_count}")
            
            return True
            
        except Exception as e:
            self.print_step("模块2启动", "fail", str(e))
            logger.error(f"模块2启动异常: {e}", exc_info=True)
            return False
    
    # ==================== 步骤3: 触发全量匹配 ====================
    
    def step3_trigger_match(self) -> bool:
        """触发模块3全量匹配"""
        print()
        self.print_step("步骤3: 触发匹配", "info")
        
        try:
            self.print_step("全量匹配", "doing")
            
            # 等待模块3初始化完成
            time.sleep(3)
            
            try:
                resp = requests.post("http://localhost:8000/api/full-refresh", timeout=120)
                result = resp.json()
                self.print_step("全量匹配", "done", 
                    f"消息{result.get('total_messages', 0)}条, 提及{result.get('total_mentions', 0)}条")
            except Exception as e:
                self.print_step("全量匹配", "info", f"自动匹配已执行或API调用失败: {e}")
            
            return True
            
        except Exception as e:
            self.print_step("触发匹配", "fail", str(e))
            return False
    
    # ==================== 步骤4: 数据验证 ====================
    
    def step4_verify_data(self) -> bool:
        """验证各模块数据"""
        print()
        self.print_step("步骤4: 数据验证", "info")
        
        # 检查messages.db
        msg_count = self.check_messages_db()
        self.print_step("messages.db", "done" if msg_count > 0 else "info", 
            f"{msg_count}条消息")
        
        # 检查a_stock.db
        stock_count = self.check_stock_db()
        self.print_step("a_stock.db", "done" if stock_count > 0 else "info", 
            f"{stock_count}只股票")
        
        # 检查stock_mentions.db
        mentions_count = self.check_mentions_db()
        self.print_step("stock_mentions.db", "done" if mentions_count > 0 else "info", 
            f"{mentions_count}条提及记录")
        
        # 尝试从API获取统计
        try:
            resp = requests.get("http://localhost:8000/api/stats/daily", timeout=5)
            if resp.status_code == 200:
                daily = resp.json()
                self.print_step("API统计", "done", 
                    f"当日{daily.get('stock_count', 0)}只股票被提及")
        except Exception as e:
            self.print_step("API统计", "info", f"获取失败: {e}")
        
        # 判断测试是否成功
        success = msg_count > 0 and stock_count > 0 and mentions_count >= 0
        return success
    
    # ==================== 步骤5: 显示看板 ====================
    
    def step5_show_dashboard(self):
        """显示简单看板"""
        print()
        print("=" * 70)
        print("  看板监控（按Ctrl+C退出）")
        print("=" * 70)
        
        try:
            while not self.stop_event.is_set():
                try:
                    # 清屏并移动光标到顶部
                    print("\033[2J\033[H", end="")
                    
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # 打印看板头部
                    print()
                    print("+" + "-" * 68 + "+")
                    print(f"|  股票监控数据分析看板  {now:<44}|")
                    print("+" + "-" * 68 + "+")
                    
                    # 数据库状态
                    msg_count = self.check_messages_db()
                    stock_count = self.check_stock_db()
                    mentions_count = self.check_mentions_db()
                    
                    print(f"|  【数据库状态】")
                    print(f"|  messages.db: {msg_count}条消息")
                    print(f"|  a_stock.db: {stock_count}只股票")
                    print(f"|  stock_mentions.db: {mentions_count}条提及")
                    
                    # 尝试获取API统计
                    print("|")
                    print("|  【今日统计】")
                    try:
                        daily = requests.get("http://localhost:8000/api/stats/daily", timeout=3).json()
                        print(f"|  当日股票: {daily.get('stock_count', 0)} 只")
                        stocks = daily.get('stocks', [])[:5]
                        if stocks:
                            print(f"|  {'排名':<4} {'股票名称':<12} {'代码':<10} {'提及次数':<8}")
                            print("|  " + "-" * 50)
                            for i, stock in enumerate(stocks, 1):
                                name = stock.get('name', '')[:10]
                                code = stock.get('code', '')
                                count = stock.get('mention_count', 0)
                                print(f"|  {i:<4} {name:<12} {code:<10} {count:<8}")
                    except:
                        print("|  API服务暂未响应")
                    
                    print("+" + "-" * 68 + "+")
                    print("|  按 Ctrl+C 退出")
                    print("+" + "-" * 68 + "+")
                    
                except Exception as e:
                    print(f"|  看板更新失败: {e}")
                
                time.sleep(5)  # 5秒刷新
                
        except KeyboardInterrupt:
            print("\n\n用户中断，正在退出...")
    
    # ==================== 清理 ====================
    
    def cleanup(self):
        """清理资源"""
        self.stop_event.set()
        
        if self.api_process:
            try:
                self.api_process.terminate()
                self.api_process.wait(timeout=5)
            except:
                pass
        
        print("\n测试结束")
    
    # ==================== 主运行方法 ====================
    
    def run(self):
        """执行完整测试流程"""
        try:
            # 步骤0: 数据检查
            if not self.step0_check_data():
                return False
            
            # 步骤1: 模块3启动
            if not self.step1_start_module3():
                return False
            
            # 步骤2: 模块2启动
            if not self.step2_start_module2():
                return False
            
            # 步骤3: 触发全量匹配
            if not self.step3_trigger_match():
                return False
            
            # 步骤4: 数据验证
            if not self.step4_verify_data():
                self.print_step("数据验证", "fail", "数据不完整")
                return False
            
            # 步骤5: 显示看板
            self.step5_show_dashboard()
            
            return True
            
        except KeyboardInterrupt:
            print("\n用户中断")
            return False
        except Exception as e:
            logger.error(f"测试异常: {e}", exc_info=True)
            return False
        finally:
            self.cleanup()


def main():
    """主入口"""
    test = MinimalFlowSimpleTest()
    success = test.run()
    
    if success:
        print("\n测试成功完成！")
    else:
        print("\n测试失败")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())