# -*- coding: utf-8 -*-
"""
终端看板模块 - 固定顶部模式
看板始终在终端顶部，刷新时原地更新，不重复输出
120秒自动刷新，支持键盘交互：R=手动刷新，M=月份选择，U=更新A股数据，Q=退出
"""
import os
import sys
import time
import json
import threading
import logging
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError

# Windows终端UTF-8和ANSI转义序列支持
if sys.platform == 'win32':
    os.system('chcp 65001 >nul 2>&1')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    # 启用Windows虚拟终端处理（支持ANSI光标控制）
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        if not (mode.value & 0x0004):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass

logger = logging.getLogger(__name__)

DASHBOARD_REFRESH_INTERVAL = 120
API_BASE = "http://localhost:8000"

_selected_year = None
_selected_month = None
_DASHBOARD_LINES = 0
_DASHBOARD_RENDERED = False

# 输出锁：防止看板刷新和消息输出同时写stdout导致光标混乱
_output_lock = threading.Lock()


def fetch_api(endpoint: str, method: str = "GET") -> dict:
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


def format_stock_table(stocks: list, max_rows: int = 5) -> list:
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


def _build_dashboard_lines(refresh_msg: str = "", month_label: str = "") -> list:
    global _selected_year, _selected_month
    now = datetime.now()
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")
    query_year = _selected_year if _selected_year else now.year
    query_month = _selected_month if _selected_month else now.month

    daily_data = fetch_api("/api/stats/daily")
    weekly_data = fetch_api("/api/stats/weekly")
    monthly_data = fetch_api(f"/api/stats/monthly?year={query_year}&month={query_month}")

    lines = []
    lines.append("+" + "-" * 62 + "+")
    lines.append(f"|  股票监控数据分析看板  {time_str:<20}|")
    lines.append("+" + "-" * 62 + "+")

    if daily_data:
        period = daily_data.get('period', '')
        count = daily_data.get('stock_count', 0)
        lines.append(f"|  【日统计】{period}  当日股票 {count} 只")
    else:
        lines.append("|  【日统计】获取数据中...")
    lines.append("|")
    if daily_data and daily_data.get('stocks'):
        for line in format_stock_table(daily_data['stocks'], max_rows=5):
            lines.append(f"|{line:<63}|")
    else:
        lines.append("|  暂无数据" + " " * 53 + "|")
    lines.append("+" + "-" * 62 + "+")

    if weekly_data:
        period = weekly_data.get('period', '')
        count = weekly_data.get('stock_count', 0)
        lines.append(f"|  【周统计】{period}  本周股票 {count} 只")
    else:
        lines.append("|  【周统计】获取数据中...")
    lines.append("|")
    if weekly_data and weekly_data.get('stocks'):
        for line in format_stock_table(weekly_data['stocks'], max_rows=5):
            lines.append(f"|{line:<63}|")
    else:
        lines.append("|  暂无数据" + " " * 53 + "|")
    lines.append("+" + "-" * 62 + "+")

    if monthly_data:
        period = monthly_data.get('period', '')
        count = monthly_data.get('stock_count', 0)
        lines.append(f"|  【月统计】{period}  当月股票 {count} 只")
    else:
        lines.append("|  【月统计】获取数据中...")
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
        for line in format_stock_table(monthly_data['stocks'], max_rows=5):
            lines.append(f"|{line:<63}|")
    else:
        lines.append("|  暂无数据" + " " * 53 + "|")
    lines.append("+" + "-" * 62 + "+")

    lines.append("|  [R]刷新看板 [M]上月 [N]下月 [Q]退出  120秒自动刷新")
    lines.append("|  [U]更新A股数据库并重新加载索引")
    if refresh_msg:
        lines.append(f"|  {refresh_msg:<60}|")
    lines.append(f"|  API服务: {API_BASE}")
    lines.append("+" + "-" * 62 + "+")
    return lines


def render_dashboard(refresh_msg: str = "", month_label: str = "", force_redraw: bool = False):
    """渲染终端看板
    首次渲染：输出完整看板
    后续刷新：只输出一行增量更新信息
    force_redraw=True时：重新输出完整看板（用于月份切换等需要看板变化的场景）
    """
    global _DASHBOARD_RENDERED

    if not _DASHBOARD_RENDERED or force_redraw:
        # 首次或强制重绘：输出完整看板
        lines = _build_dashboard_lines(refresh_msg=refresh_msg, month_label=month_label)
        print("\n".join(lines))
        sys.stdout.flush()
        _DASHBOARD_RENDERED = True
    else:
        # 后续：只输出一行增量更新摘要
        if refresh_msg:
            print(f"  [{datetime.now().strftime('%H:%M:%S')}] {refresh_msg}", flush=True)
        elif month_label:
            print(f"  [{datetime.now().strftime('%H:%M:%S')}] {month_label}", flush=True)


def get_output_lock():
    """获取输出锁（供simple_monitor等模块使用，防止输出冲突）"""
    return _output_lock


def do_incremental_refresh() -> str:
    result = fetch_api("/api/incremental-refresh", method="POST")
    if result and result.get('status') == 'ok':
        details = result.get('details', {})
        new_msgs = details.get('new_messages', 0)
        new_mentions = details.get('new_mentions', 0)
        return f"增量刷新完成: {new_msgs}条新消息, {new_mentions}条新提及"
    return "刷新请求失败，请检查API服务"


def do_update_stock_db() -> str:
    try:
        url = f"{API_BASE}/api/update-stock-db"
        req = Request(url, method="POST")
        with urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        logger.error(f"A股数据更新请求失败: {e}")
        return f"更新失败: {str(e)[:40]}"
    if result and result.get('status') == 'ok':
        msg = result.get('message', '')
        return f"完成: {msg}"
    error_msg = result.get('message', '未知错误') if result else 'API无响应'
    return f"失败: {error_msg[:50]}"


def show_month_selector(direction: int = -1) -> tuple:
    """月份选择：按M往前推一个月，按N往后推一个月"""
    global _selected_year, _selected_month
    now = datetime.now()
    sel_year = _selected_year if _selected_year else now.year
    sel_month = _selected_month if _selected_month else now.month

    # direction=-1往前推, direction=1往后推
    sel_month += direction
    if sel_month < 1:
        sel_month = 12
        sel_year -= 1
    elif sel_month > 12:
        sel_month = 1
        sel_year += 1
    # 不超过当前月份
    if (sel_year, sel_month) > (now.year, now.month):
        sel_year = now.year
        sel_month = now.month
    _selected_year = sel_year
    _selected_month = sel_month
    return (sel_year, sel_month)


def keyboard_listener(stop_event, refresh_event, month_event, month_forward_event, update_event):
    """键盘监听线程"""
    if sys.platform == 'win32':
        import msvcrt
        while not stop_event.is_set():
            if msvcrt.kbhit():
                key = msvcrt.getch().decode('ascii', errors='ignore').upper()
                if key == 'R':
                    refresh_event.set()
                elif key == 'M':
                    month_event.set()
                elif key == 'N':
                    month_forward_event.set()
                elif key == 'U':
                    update_event.set()
                elif key == 'Q':
                    stop_event.set()
                    break
            time.sleep(0.1)


class DashboardController:
    """看板控制器"""
    def __init__(self, stop_event, refresh_event):
        self.stop_event = stop_event
        self.refresh_event = refresh_event

    def trigger_refresh(self):
        if self.refresh_event:
            self.refresh_event.set()

    def stop(self):
        if self.stop_event:
            self.stop_event.set()


_dashboard_instance = None


def get_dashboard():
    """获取全局看板控制器实例"""
    return _dashboard_instance


def start_dashboard_thread():
    """启动看板独立线程"""
    global _dashboard_instance

    if _dashboard_instance is not None:
        logger.warning("看板已启动，跳过重复启动")
        return _dashboard_instance

    stop_event = threading.Event()
    refresh_event = threading.Event()
    controller = DashboardController(stop_event, refresh_event)
    _dashboard_instance = controller

    t = threading.Thread(
        target=_dashboard_loop_with_external_refresh,
        args=(stop_event, refresh_event),
        name="dashboard-thread",
        daemon=True,
    )
    t.start()
    return controller


def _dashboard_loop_with_external_refresh(stop_event, external_refresh_event):
    """看板主循环（固定顶部模式）"""
    global _selected_year, _selected_month

    logger.info("终端看板线程启动（固定顶部模式）")

    month_event = threading.Event()
    month_forward_event = threading.Event()
    update_event = threading.Event()

    kb_thread = threading.Thread(
        target=keyboard_listener,
        args=(stop_event, external_refresh_event, month_event, month_forward_event, update_event),
        name="keyboard-listener",
        daemon=True,
    )
    kb_thread.start()

    # 等待API服务就绪
    for i in range(30):
        if stop_event.is_set():
            return
        try:
            result = fetch_api("/api/health")
            if result and result.get('status') == 'ok':
                break
        except Exception:
            pass
        time.sleep(1)

    first_render = True

    while not stop_event.is_set():
        try:
            # 首次渲染：API就绪后立即显示看板（不等数据，让看板在消息上方）
            if first_render:
                # 短暂等待3秒让API完全初始化
                time.sleep(3)
                render_dashboard(force_redraw=True)
                first_render = False
        except Exception as e:
            logger.error(f"看板渲染失败: {e}")

        # 等待刷新间隔或事件触发
        start_time = time.time()
        while time.time() - start_time < DASHBOARD_REFRESH_INTERVAL:
            if stop_event.is_set():
                break
            if external_refresh_event.is_set():
                external_refresh_event.clear()
                msg = do_incremental_refresh()
                render_dashboard(refresh_msg=msg, force_redraw=True)
                break
            if month_event.is_set():
                month_event.clear()
                result = show_month_selector(direction=-1)
                if result:
                    _selected_year, _selected_month = result
                month_label = f"已切换到 {_selected_year}年{_selected_month}月"
                render_dashboard(month_label=month_label, force_redraw=True)
                break
            if month_forward_event.is_set():
                month_forward_event.clear()
                result = show_month_selector(direction=1)
                if result:
                    _selected_year, _selected_month = result
                month_label = f"已切换到 {_selected_year}年{_selected_month}月"
                render_dashboard(month_label=month_label, force_redraw=True)
                break
            if update_event.is_set():
                update_event.clear()
                msg = do_update_stock_db()
                render_dashboard(refresh_msg=f"A股数据更新: {msg}", force_redraw=True)
                break
            time.sleep(0.5)
        else:
            # 定时刷新（120秒到期）
            msg = do_incremental_refresh()
            render_dashboard(refresh_msg=msg, force_redraw=True)
            continue

        if stop_event.is_set():
            break

    print("\n" + "=" * 50)
    print("  看板已退出")
    print("  API服务仍在运行: http://localhost:8000")
    print("  按Ctrl+C停止API服务")
    print("=" * 50)
    logger.info("终端看板线程退出")
