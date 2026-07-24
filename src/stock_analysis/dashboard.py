# -*- coding: utf-8 -*-
"""
终端看板模块
在终端以三列（日/周/月）表格形式实时展示股票提及统计数据
30秒自动刷新，支持键盘交互：R=手动刷新，M=月份选择，Q=退出
"""
import os
import sys
import time
import json
import threading
import logging
import multiprocessing
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

# Windows终端UTF-8支持
if sys.platform == 'win32':
    os.system('chcp 65001 >nul 2>&1')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

logger = logging.getLogger(__name__)

# 看板刷新间隔（秒）
DASHBOARD_REFRESH_INTERVAL = 10  # 10秒（与增量更新同步）

# API基础URL
API_BASE = "http://localhost:8000"

# 全局月份选择状态（线程安全通过GIL保证）
_selected_year = None
_selected_month = None


def clear_screen():
    """清屏"""
    os.system('cls' if os.name == 'nt' else 'clear')


def fetch_api(endpoint: str, method: str = "GET") -> dict:
    """调用API获取数据"""
    try:
        url = f"{API_BASE}{endpoint}"
        req = Request(url, method=method)
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except URLError:
        return None
    except Exception as e:
        logger.debug(f"API调用失败: {endpoint}, 错误: {e}")
        return None


def format_stock_table(stocks: list, max_rows: int = 10) -> list:
    """格式化股票统计表格行"""
    lines = []
    lines.append(f"  {'排名':<4} {'股票名称':<10} {'代码':<8} {'提及次数':<8}")
    lines.append("  " + "-" * 34)

    if not stocks:
        lines.append("  暂无数据")
        return lines

    for stock in stocks[:max_rows]:
        rank = stock.get('rank', '-')
        name = stock.get('name', '')[:8]
        code = stock.get('code', '')
        count = stock.get('mention_count', 0)
        lines.append(f"  {rank:<4} {name:<10} {code:<8} {count:<8}")

    if len(stocks) > max_rows:
        lines.append(f"  ... 共{len(stocks)}只股票")

    return lines


def render_dashboard(refresh_msg: str = "", month_label: str = ""):
    """渲染终端看板"""
    global _selected_year, _selected_month

    now = datetime.now()
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # 确定月统计查询参数
    query_year = _selected_year if _selected_year else now.year
    query_month = _selected_month if _selected_month else now.month

    # 获取三个维度的数据
    daily_data = fetch_api("/api/stats/daily")
    weekly_data = fetch_api("/api/stats/weekly")
    monthly_data = fetch_api(f"/api/stats/monthly?year={query_year}&month={query_month}")

    # 构建看板（使用ASCII字符，兼容Windows终端）
    lines = []
    lines.append("+" + "-" * 62 + "+")
    lines.append(f"|  股票监控数据分析看板  {time_str:<20}|")
    lines.append("+" + "-" * 62 + "+")

    # 日统计 - 当日股票去重数量
    if daily_data:
        period = daily_data.get('period', '')
        count = daily_data.get('stock_count', 0)
        lines.append(f"|  【日统计】{period}  当日股票 {count} 只")
    else:
        lines.append("|  【日统计】获取数据中...")

    lines.append("|")

    if daily_data and daily_data.get('stocks'):
        for line in format_stock_table(daily_data['stocks'], max_rows=8):
            lines.append(f"|{line:<63}|")
    else:
        lines.append("|  暂无数据" + " " * 53 + "|")

    lines.append("+" + "-" * 62 + "+")

    # 周统计 - 本周股票去重数量
    if weekly_data:
        period = weekly_data.get('period', '')
        count = weekly_data.get('stock_count', 0)
        lines.append(f"|  【周统计】{period}  本周股票 {count} 只")
    else:
        lines.append("|  【周统计】获取数据中...")

    lines.append("|")

    if weekly_data and weekly_data.get('stocks'):
        for line in format_stock_table(weekly_data['stocks'], max_rows=8):
            lines.append(f"|{line:<63}|")
    else:
        lines.append("|  暂无数据" + " " * 53 + "|")

    lines.append("+" + "-" * 62 + "+")

    # 月统计 - 当月股票去重数量
    if monthly_data:
        period = monthly_data.get('period', '')
        count = monthly_data.get('stock_count', 0)
        lines.append(f"|  【月统计】{period}  当月股票 {count} 只")
    else:
        lines.append("|  【月统计】获取数据中...")

    # 月份选择提示
    if month_label:
        lines.append(f"|  {month_label:<60}|")
    elif _selected_year and _selected_month:
        if _selected_year != now.year or _selected_month != now.month:
            lines.append(f"|  当前查看: {_selected_year}年{_selected_month}月  按[M]切换月份")
        else:
            lines.append("|  按[M]切换月份查看历史")
    else:
        lines.append("|  按[M]切换月份查看历史")

    lines.append("|")

    if monthly_data and monthly_data.get('stocks'):
        for line in format_stock_table(monthly_data['stocks'], max_rows=8):
            lines.append(f"|{line:<63}|")
    else:
        lines.append("|  暂无数据" + " " * 53 + "|")

    lines.append("+" + "-" * 62 + "+")

    # 操作提示（始终显示快捷键）
    lines.append("|  [R]刷新 [M]月份 [Q]退出  10秒自动刷新")

    # 刷新结果消息（在快捷键下方单独一行）
    if refresh_msg:
        lines.append(f"|  {refresh_msg:<60}|")

    lines.append(f"|  API服务: {API_BASE}")
    lines.append("+" + "-" * 62 + "+")

    # 清屏并输出
    clear_screen()
    print("\n".join(lines))


def do_incremental_refresh() -> str:
    """执行增量刷新并返回结果消息"""
    result = fetch_api("/api/incremental-refresh", method="POST")
    if result and result.get('status') == 'ok':
        details = result.get('details', {})
        new_msgs = details.get('new_messages', 0)
        new_mentions = details.get('new_mentions', 0)
        return f"增量刷新完成: {new_msgs}条新消息, {new_mentions}条新提及"
    else:
        return "刷新请求失败，请检查API服务"


def show_month_selector() -> tuple:
    """
    显示月份选择交互界面
    返回 (year, month) 或 None表示取消
    """
    global _selected_year, _selected_month

    now = datetime.now()
    current_year = now.year
    current_month = now.month

    # 默认从当前选中的月份开始
    sel_year = _selected_year if _selected_year else current_year
    sel_month = _selected_month if _selected_month else current_month

    while True:
        clear_screen()
        print("+" + "-" * 40 + "+")
        print(f"|  月份选择  {sel_year}年{sel_month}月")
        print("+" + "-" * 40 + "+")
        print("|")
        print("|  [1]1月  [2]2月  [3]3月  [4]4月")
        print("|  [5]5月  [6]6月  [7]7月  [8]8月")
        print("|  [9]9月  [0]10月 [A]11月 [B]12月")
        print("|")
        print("|  [Enter] 确认当前  [Esc] 取消返回")
        print("+" + "-" * 40 + "+")

        if sys.platform == 'win32':
            import msvcrt
            key = msvcrt.getch()
            if key == b'\r' or key == b'\n':
                # Enter确认
                return (sel_year, sel_month)
            elif key == b'\x1b':
                # Esc取消
                return None
            elif key == b'0':
                sel_month = 10
            elif key == b'1':
                sel_month = 1
            elif key == b'2':
                sel_month = 2
            elif key == b'3':
                sel_month = 3
            elif key == b'4':
                sel_month = 4
            elif key == b'5':
                sel_month = 5
            elif key == b'6':
                sel_month = 6
            elif key == b'7':
                sel_month = 7
            elif key == b'8':
                sel_month = 8
            elif key == b'9':
                sel_month = 9
            elif key.upper() == b'A':
                sel_month = 11
            elif key.upper() == b'B':
                sel_month = 12


def keyboard_listener(stop_event: threading.Event, refresh_event: threading.Event,
                      month_event: threading.Event):
    """
    键盘监听线程
    R = 手动刷新（触发增量更新+看板刷新）
    M = 月份选择
    Q = 退出
    """
    if sys.platform == 'win32':
        import msvcrt
        while not stop_event.is_set():
            if msvcrt.kbhit():
                key = msvcrt.getch().decode('ascii', errors='ignore').upper()
                if key == 'R':
                    logger.info("用户按R键，触发手动刷新")
                    refresh_event.set()
                elif key == 'M':
                    logger.info("用户按M键，触发月份选择")
                    month_event.set()
                elif key == 'Q':
                    logger.info("用户按Q键，退出看板")
                    stop_event.set()
                    break
            time.sleep(0.1)
    else:
        import select
        while not stop_event.is_set():
            if select.select([sys.stdin], [], [], 0.1)[0]:
                key = sys.stdin.readline().strip().upper()
                if key == 'R':
                    logger.info("用户按R键，触发手动刷新")
                    refresh_event.set()
                elif key == 'M':
                    logger.info("用户按M键，触发月份选择")
                    month_event.set()
                elif key == 'Q':
                    logger.info("用户按Q键，退出看板")
                    stop_event.set()
                    break


def dashboard_loop(stop_event: threading.Event):
    """
    看板主循环（在独立线程中运行）

    Args:
        stop_event: 停止事件，设置后退出循环
    """
    global _selected_year, _selected_month

    logger.info("终端看板线程启动")

    # 创建事件
    refresh_event = threading.Event()
    month_event = threading.Event()

    # 启动键盘监听线程
    kb_thread = threading.Thread(
        target=keyboard_listener,
        args=(stop_event, refresh_event, month_event),
        name="keyboard-listener",
        daemon=True,
    )
    kb_thread.start()

    # 等待API服务就绪（最多等30秒）
    for i in range(30):
        if stop_event.is_set():
            return
        try:
            result = fetch_api("/api/health")
            if result and result.get('status') == 'ok':
                logger.info("API服务已就绪，启动看板显示")
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        logger.warning("API服务未就绪，看板将尝试显示")

    refresh_msg = ""
    month_label = ""
    while not stop_event.is_set():
        try:
            render_dashboard(refresh_msg=refresh_msg, month_label=month_label)
            refresh_msg = ""
            month_label = ""
        except Exception as e:
            logger.error(f"看板渲染失败: {e}")

        # 等待刷新间隔，但可被事件中断
        start_time = time.time()
        while time.time() - start_time < DASHBOARD_REFRESH_INTERVAL:
            if stop_event.is_set():
                break
            if refresh_event.is_set():
                refresh_event.clear()
                refresh_msg = do_incremental_refresh()
                break
            if month_event.is_set():
                month_event.clear()
                # 进入月份选择界面
                result = show_month_selector()
                if result:
                    _selected_year, _selected_month = result
                    month_label = f"已切换到 {_selected_year}年{_selected_month}月"
                break
            time.sleep(0.5)
        else:
            # 正常30秒到，自动刷新
            continue

        if stop_event.is_set():
            break

    # 退出时显示提示
    clear_screen()
    print("=" * 50)
    print("  看板已退出")
    print("  API服务仍在运行: http://localhost:8000")
    print("  按Ctrl+C停止API服务")
    print("=" * 50)
    
    logger.info("终端看板线程退出")


def _dashboard_process_main():
    """看板子进程入口函数"""
    # Windows多进程必须调用freeze_support
    multiprocessing.freeze_support()
    
    # 子进程中重新配置UTF-8
    if sys.platform == 'win32':
        os.system('chcp 65001 >nul 2>&1')
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    # 子进程日志配置
    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"stock_analysis_{datetime.now().strftime('%Y-%m-%d')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler(str(log_file), encoding="utf-8")],
    )

    stop_event = threading.Event()
    dashboard_loop(stop_event)


def start_dashboard_thread():
    """
    启动看板独立线程（供main.py调用）
    线程在主进程中运行，共享终端输出，在PowerShell中显示看板
    返回Thread对象
    """
    stop_event = threading.Event()
    t = threading.Thread(
        target=dashboard_loop,
        args=(stop_event,),
        name="dashboard-thread",
        daemon=True,
    )
    t.start()
    return t
