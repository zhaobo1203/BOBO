"""
模块3 FastAPI应用入口
启动全量匹配 + 手动刷新API + 5分钟定时增量更新 + 终端看板
"""
import logging
import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from contextlib import asynccontextmanager

from .config.settings import (
    API_HOST, API_PORT, LOG_DIR,
    INCREMENTAL_UPDATE_INTERVAL,
)
from .services.stock_loader import StockLoader
from .services.matcher import Matcher
from .services.statistics import StatisticsService
from .services.storage import StorageService
from .api.routes import router, init_services
from .dashboard import start_dashboard_thread

# 全局服务实例
stock_loader = StockLoader()
storage_service = StorageService()
statistics_service = StatisticsService()
matcher = None  # 需要stock_loader加载后初始化


def setup_logging():
    """配置日志系统（仅文件输出）"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"stock_analysis_{datetime.now().strftime('%Y-%m-%d')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(str(log_file), encoding="utf-8"),
        ],
    )
    logger = logging.getLogger(__name__)
    logger.info(f"日志系统初始化完成，日志文件: {log_file}")
    return logger


def run_full_match() -> dict:
    """执行全量匹配"""
    global matcher
    logger = logging.getLogger(__name__)
    logger.info("开始全量匹配...")

    # 1. 加载A股数据
    stocks = stock_loader.load()
    if not stocks:
        logger.error("A股数据加载失败")
        return {"error": "A股数据加载失败"}

    # 2. 初始化匹配引擎
    matcher = Matcher(
        name_index=stock_loader.get_name_index(),
        code_index=stock_loader.get_code_index(),
    )

    # 3. 清空旧数据
    storage_service.clear_all()

    # 4. 获取所有消息
    messages = storage_service.get_all_messages()
    logger.info(f"获取到{len(messages)}条消息")

    # 5. 执行匹配
    mentions = matcher.match_messages_batch(messages)

    # 6. 保存结果
    saved = storage_service.save_mentions(mentions, process_type="full")

    result = {
        "total_stocks": len(stocks),
        "total_messages": len(messages),
        "total_mentions": len(mentions),
        "saved_records": saved,
    }
    logger.info(f"全量匹配完成: {result}")
    return result


def update_stock_db_and_reload() -> dict:
    """
    更新A股数据库并重新加载匹配引擎索引
    端到端流程：模块2更新数据 → 模块3重新加载索引
    
    Returns:
        更新结果字典
    """
    global matcher
    logger = logging.getLogger(__name__)
    logger.info("开始更新A股数据库...")
    
    try:
        # 1. 调用模块2的数据源管理器获取最新数据
        from ..a_stock_db.data_sources import DataSourceManager
        from ..a_stock_db.database import AStockDatabase
        
        manager = DataSourceManager()
        result = manager.fetch_with_fallback()
        
        if not result.success:
            logger.error(f"A股数据获取失败: {result.error_message}")
            return {
                "status": "error",
                "message": f"A股数据获取失败: {result.error_message}",
            }
        
        # 2. 更新数据库
        db = AStockDatabase()
        stocks_data = [(s.code, s.name) for s in result.stocks]
        db_stats = db.update_stocks(stocks_data, source=result.source if hasattr(result, 'source') else "unknown")
        
        logger.info(f"A股数据库更新完成: 获取{result.count}只, 耗时{result.elapsed_time:.1f}秒")
        
        # 3. 重新加载匹配引擎索引
        old_count, new_count = stock_loader.reload()
        
        # 4. 重建匹配引擎
        matcher = Matcher(
            name_index=stock_loader.get_name_index(),
            code_index=stock_loader.get_code_index(),
        )
        
        logger.info(f"匹配引擎索引已重新加载: {old_count}→{new_count}只")
        
        return {
            "status": "ok",
            "old_count": old_count,
            "new_count": new_count,
            "fetched_count": result.count,
            "elapsed_time": round(result.elapsed_time, 1),
        }
        
    except Exception as e:
        logger.error(f"A股数据更新失败: {e}")
        return {
            "status": "error",
            "message": f"更新失败: {str(e)}",
        }


def run_incremental_match() -> dict:
    """执行增量匹配"""
    global matcher
    logger = logging.getLogger(__name__)

    if matcher is None:
        logger.warning("匹配引擎未初始化，执行全量匹配")
        return run_full_match()

    # 1. 获取新消息
    new_messages = storage_service.get_new_messages()
    if not new_messages:
        logger.info("无新消息，跳过增量匹配")
        return {"new_messages": 0, "new_mentions": 0}

    # 2. 执行匹配
    mentions = matcher.match_messages_batch(new_messages)

    # 3. 保存结果
    saved = storage_service.save_mentions(mentions, process_type="incremental")

    result = {
        "new_messages": len(new_messages),
        "new_mentions": len(mentions),
        "saved_records": saved,
    }
    logger.info(f"增量匹配完成: {result}")
    return result


async def periodic_incremental_update():
    """定时增量更新任务（每5分钟）"""
    logger = logging.getLogger(__name__)
    while True:
        await asyncio.sleep(INCREMENTAL_UPDATE_INTERVAL)
        try:
            logger.info("定时增量更新触发...")
            run_incremental_match()
        except Exception as e:
            logger.error(f"定时增量更新失败: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("模块3 数据分析服务启动中...")
    logger.info("=" * 60)

    # 启动时全量匹配
    try:
        result = run_full_match()
        logger.info(f"启动全量匹配结果: {result}")
    except Exception as e:
        logger.error(f"启动全量匹配失败: {e}")

    # 启动定时增量更新
    task = asyncio.create_task(periodic_incremental_update())
    logger.info(f"定时增量更新已启动，间隔{INCREMENTAL_UPDATE_INTERVAL}秒")

    # 启动终端看板（独立线程，在PowerShell中显示）
    dashboard_thread = start_dashboard_thread()
    logger.info("终端看板已启动（独立线程），10秒刷新间隔")

    yield

    # 关闭时取消定时任务和看板线程
    task.cancel()
    if dashboard_thread and dashboard_thread.is_alive():
        dashboard_thread.join(timeout=3)
    logger.info("模块3 数据分析服务已停止")


def create_app() -> FastAPI:
    """创建FastAPI应用"""
    # 初始化日志
    setup_logging()

    # 创建应用
    app = FastAPI(
        title="微信群股票数据分析API",
        description="模块3：微信群消息与A股股票匹配统计",
        version="0.1.0",
        lifespan=lifespan,
    )

    # 初始化API路由服务
    init_services(storage_service, statistics_service)

    # 注册路由
    app.include_router(router)

    return app


# 创建应用实例
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.stock_analysis.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
    )