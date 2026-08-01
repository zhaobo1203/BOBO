# -*- coding: utf-8 -*-
"""
临时测试脚本 - 最小化流程（只登录一次微信）

核心思路：
1. 只初始化一次 SimpleMonitor 实例
2. 密钥获取只执行一次，后续步骤复用
3. 测试模块1、模块2、模块3的联动

运行方式：python test_minimal_flow_once.py

前提条件：
- 微信已登录运行
- 微信进程已启动

数据流：
模块1（微信监听）→ messages.db → 模块3（股票分析）← a_stock.db ← 模块2（A股数据）
"""

import sys
import os
import time
import sqlite3
import threading
import subprocess
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
        logging.FileHandler(PROJECT_ROOT / "logs" / "minimal_flow_once.log", encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


class MinimalFlowOnceTest:
    """最小化流程测试 - 只登录一次微信"""
    
    def __init__(self):
        self.project_root = PROJECT_ROOT
        self.messages_db = PROJECT_ROOT / "data" / "messages.db"
        self.stock_db = PROJECT_ROOT / "data" / "a_stock_db" / "a_stock.db"
        self.mentions_db = PROJECT_ROOT / "data" / "stock_mentions.db"
        
        # 共享的 Monitor 实例（只初始化一次）
        self.monitor_instance = None
        self.selected_group_id = None
        self.selected_group_name = None
        
        # 模块3进程
        self.api_process = None
        self.stop_event = threading.Event()
        
    def print_header(self):
        """显示测试头部"""
        print()
        print("=" * 70)
        print("  最小化流程测试（只登录一次微信）")
        print("  流程: 初始化一次 → 复用密钥 → 模块3 → 模块2 → 数据验证")
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
    
    # ==================== 步骤1: 一次性初始化 ====================
    
    def step1_init_once(self) -> bool:
        """步骤1: 一次性初始化 - 进程检测、账号识别、密钥获取、数据库连接（只执行一次）"""
        print()
        self.print_step("步骤1: 一次性初始化", "info", "只执行一次，后续复用")
        
        try:
            from simple_monitor import SimpleMonitor
            
            # 创建唯一的实例
            self.monitor_instance = SimpleMonitor()
            
            # 1.1 进程检测
            self.print_step("1.1 进程检测", "doing")
            if not self.monitor_instance.step1_detect_process():
                self.print_step("1.1 进程检测", "fail", "请先启动微信客户端")
                return False
            self.print_step("1.1 进程检测", "done", f"PID={self.monitor_instance.pid}")
            
            # 1.2 账号识别
            self.print_step("1.2 账号识别", "doing")
            if not self.monitor_instance.step2_detect_account():
                self.print_step("1.2 账号识别", "fail")
                return False
            self.print_step("1.2 账号识别", "done", self.monitor_instance.account_id)
            
            # 1.3 密钥获取（只执行一次！）
            self.print_step("1.3 密钥获取", "doing", "Hook注入中（只执行一次）...")
            if not self.monitor_instance.step3_get_key():
                self.print_step("1.3 密钥获取", "fail")
                return False
            self.print_step("1.3 密钥获取", "done", "成功（已缓存）")
            
            # 1.4 数据库连接
            self.print_step("1.4 数据库连接", "doing")
            if not self.monitor_instance.step4_connect_db():
                self.print_step("1.4 数据库连接", "fail")
                return False
            self.print_step("1.4 数据库连接", "done", "解密成功")
            
            # 打印密钥信息（用于验证复用）
            print()
            self.print_step("初始化完成", "done", f"密钥已获取，长度={len(self.monitor_instance.db_key) if self.monitor_instance.db_key else 0}")
            
            return True
            
        except Exception as e:
            self.print_step("一次性初始化", "fail", str(e))
            logger.error(f"初始化异常: {e}", exc_info=True)
            return False
    
    # ==================== 步骤2: 获取历史消息 ====================
    
    def step2_get_history_messages(self) -> bool:
        """步骤2: 获取历史消息（复用已初始化的实例）"""
        print()
        self.print_step("步骤2: 获取历史消息", "info", "复用已获取的密钥")
        
        if not self.monitor_instance:
            self.print_step("获取历史消息", "fail", "Monitor实例未初始化")
            return False
        
        try:
            # 获取群列表
            self.print_step("加载群列表", "doing")
            
            groups = self._get_groups_list()
            if not groups:
                self.print_step("加载群列表", "fail", "未找到群聊")
                return False
            
            self.print_step("加载群列表", "done", f"共{len(groups)}个群聊")
            
            # 自动选择第一个群（或搜索特定群）
            target_group = None
            for group in groups:
                name = group.get('displayName', '')
                # 优先选择AI测试群或市场资讯群
                if 'AI测试' in name or '市场资讯' in name or '测试' in name:
                    target_group = group
                    break
            
            if not target_group:
                target_group = groups[0]
            
            self.selected_group_id = target_group.get('username', '')
            self.selected_group_name = target_group.get('displayName', '')
            self.print_step("选择群聊", "done", self.selected_group_name)
            
            # 获取历史消息
            self.print_step("获取历史消息", "doing")
            messages = self._fetch_history_messages(self.selected_group_id)
            
            if not messages:
                self.print_step("获取历史消息", "info", "无历史消息")
                return True
            
            self.print_step("获取历史消息", "done", f"获取{len(messages)}条")
            
            # 保存到messages.db
            self.print_step("保存历史消息", "doing")
            saved = self._save_messages_to_db(messages)
            self.print_step("保存历史消息", "done", f"保存{saved}条")
            
            return True
            
        except Exception as e:
            self.print_step("获取历史消息", "fail", str(e))
            logger.error(f"获取历史消息异常: {e}", exc_info=True)
            return False
    
    def _get_groups_list(self) -> List[Dict]:
        """获取群列表（复用 SimpleMonitor 的 SessionTable 正查方式）

        保持不变采用 SessionTable 表读方式。
        微信 4.x 的 SessionTable 已无 displayName 字段，直接复用主程序已兼容的方法，
        避免因表结构变化导致查询失败。
        """
        # 优先复用 SimpleMonitor._get_groups_from_session（已兼容 4.x schema）
        if self.monitor_instance and hasattr(self.monitor_instance, '_get_groups_from_session'):
            try:
                groups = self.monitor_instance._get_groups_from_session()
                if groups:
                    logger.info(f"复用 SessionTable 正查加载{len(groups)}个群聊")
                    return groups
            except Exception as e:
                logger.warning(f"复用 _get_groups_from_session 失败: {e}")

        # 兜底：nickname_cache
        groups = []
        if self.monitor_instance and self.monitor_instance.nickname_cache:
            for wxid, name in self.monitor_instance.nickname_cache.items():
                if wxid.endswith('@chatroom'):
                    groups.append({
                        'username': wxid,
                        'displayName': name
                    })
            logger.info(f"从nickname_cache加载{len(groups)}个群聊")

        return groups
    
    def _fetch_history_messages(self, group_id: str) -> List[Dict]:
        """从数据库读取历史消息（复用 SimpleMonitor 的 SessionTable 正查方式）

        保持不变采用 SessionTable 表读方式。
        微信 4.x 已无 SessionContent 表与 strTalker 字段，直接复用主程序已兼容的方法，
        通过 SessionTable 群ID → MD5 → Msg_<MD5> 表 → 遍历定位 message db。
        """
        messages = []

        try:
            # 优先复用 SimpleMonitor._get_messages_static（已兼容 4.x schema）
            if self.monitor_instance and hasattr(self.monitor_instance, '_get_messages_static'):
                static_messages = self.monitor_instance._get_messages_static(group_id, limit=100)
                if static_messages:
                    for msg in static_messages:
                        try:
                            content = msg.get('message_content', '')
                            if not content or not content.strip():
                                continue

                            create_time = msg.get('create_time', 0)
                            if isinstance(create_time, (int, float)):
                                send_time = datetime.fromtimestamp(create_time) if create_time else datetime.now()
                            else:
                                send_time = datetime.now()

                            sender_name = msg.get('sender_username') or '未知'

                            messages.append({
                                'local_id': msg.get('local_id'),
                                'time': send_time,
                                'sender': sender_name,
                                'sender_id': msg.get('sender_username') or '',
                                'content': content,
                            })
                        except Exception as e:
                            logger.warning(f"解析消息失败: {e}")

                    logger.info(f"复用 _get_messages_static 从群{self.selected_group_name}获取{len(messages)}条历史消息")
                    return messages

        except Exception as e:
            logger.error(f"读取历史消息失败: {e}", exc_info=True)

        return messages
    
    def _get_sender_name(self, sender_id: str) -> str:
        """获取发送者昵称（复用monitor实例）"""
        if not sender_id:
            return '未知'
        
        # 尝试从contact表获取
        try:
            if self.monitor_instance.decrypted_contact_db:
                conn = sqlite3.connect(self.monitor_instance.decrypted_contact_db)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT nick_name, remark
                    FROM contact
                    WHERE username = ?
                """, (sender_id,))
                row = cursor.fetchone()
                conn.close()
                
                if row:
                    return row[1] or row[0] or sender_id
        except:
            pass
        
        return sender_id
    
    def _save_messages_to_db(self, messages: List[Dict]) -> int:
        """保存消息到messages.db"""
        from wechat_decrypt_tool.message_storage import MessageStorage
        
        storage = MessageStorage(str(self.messages_db))
        saved_count = 0
        
        for msg in messages:
            try:
                storage.save_message(
                    sender_nickname=msg['sender'],
                    message_content=msg['content'],
                    send_time=msg['time'],
                    group_name=self.selected_group_name,
                    group_id=self.selected_group_id,
                    sender_id=msg.get('sender_id')
                )
                saved_count += 1
            except Exception as e:
                logger.warning(f"保存消息失败: {e}")
        
        return saved_count
    
    # ==================== 步骤3: 模块3启动 ====================
    
    def step3_start_module3(self) -> bool:
        """步骤3: 启动模块3 - 股票分析服务"""
        print()
        self.print_step("步骤3: 模块3启动", "info", "股票分析服务")
        
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
    
    # ==================== 步骤4: 模块2启动 ====================
    
    def step4_start_module2(self) -> bool:
        """步骤4: 启动模块2 - A股数据更新"""
        print()
        self.print_step("步骤4: 模块2启动", "info", "A股数据更新")
        
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
    
    # ==================== 步骤5: 触发全量匹配 ====================
    
    def step5_trigger_match(self) -> bool:
        """步骤5: 触发模块3全量匹配"""
        print()
        self.print_step("步骤5: 触发匹配", "info")
        
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
    
    # ==================== 步骤6: 数据验证 ====================
    
    def step6_verify_data(self) -> bool:
        """步骤6: 验证各模块数据"""
        print()
        self.print_step("步骤6: 数据验证", "info")
        
        # 检查messages.db
        msg_count = self._check_messages_db()
        self.print_step("messages.db", "done" if msg_count > 0 else "info", 
            f"{msg_count}条消息")
        
        # 检查a_stock.db
        stock_count = self._check_stock_db()
        self.print_step("a_stock.db", "done" if stock_count > 0 else "info", 
            f"{stock_count}只股票")
        
        # 检查stock_mentions.db
        mentions_count = self._check_mentions_db()
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
        success = msg_count > 0 and stock_count > 0
        return success
    
    def _check_messages_db(self) -> int:
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
    
    def _check_stock_db(self) -> int:
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
    
    def _check_mentions_db(self) -> int:
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
    
    # ==================== 步骤7: 显示看板 ====================
    
    def step7_show_dashboard(self):
        """步骤7: 显示简单看板"""
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
                    msg_count = self._check_messages_db()
                    stock_count = self._check_stock_db()
                    mentions_count = self._check_mentions_db()
                    
                    print(f"|  【数据库状态】")
                    print(f"|  messages.db: {msg_count}条消息")
                    print(f"|  a_stock.db: {stock_count}只股票")
                    print(f"|  stock_mentions.db: {mentions_count}条提及")
                    
                    # 显示密钥状态（验证只获取一次）
                    print("|")
                    print(f"|  【密钥状态】")
                    if self.monitor_instance and self.monitor_instance.db_key:
                        key_preview = self.monitor_instance.db_key[:8] + "..." + self.monitor_instance.db_key[-8:]
                        print(f"|  密钥: {key_preview} (已缓存)")
                    else:
                        print(f"|  密钥: 未获取")
                    
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
            # 步骤1: 一次性初始化（密钥只获取一次）
            if not self.step1_init_once():
                return False
            
            # 步骤2: 获取历史消息（复用密钥）
            if not self.step2_get_history_messages():
                return False
            
            # 步骤3: 模块3启动
            if not self.step3_start_module3():
                return False
            
            # 步骤4: 模块2启动
            if not self.step4_start_module2():
                return False
            
            # 步骤5: 触发全量匹配
            if not self.step5_trigger_match():
                return False
            
            # 步骤6: 数据验证
            if not self.step6_verify_data():
                self.print_step("数据验证", "fail", "数据不完整")
                return False
            
            # 步骤7: 显示看板
            self.step7_show_dashboard()
            
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
    test = MinimalFlowOnceTest()
    success = test.run()
    
    if success:
        print("\n测试成功完成！")
        print("关键点：微信只登录一次，密钥获取只执行一次")
    else:
        print("\n测试失败")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())