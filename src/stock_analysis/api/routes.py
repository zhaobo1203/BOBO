"""
API路由定义
"""
import logging
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Query

from ..services.statistics import StatisticsService
from ..services.storage import StorageService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# 全局服务实例（由main.py注入）
_storage_service: Optional[StorageService] = None
_statistics_service: Optional[StatisticsService] = None


def init_services(storage_service: StorageService,
                  statistics_service: StatisticsService):
    """初始化服务实例"""
    global _storage_service, _statistics_service
    _storage_service = storage_service
    _statistics_service = statistics_service
    logger.info("API路由服务初始化完成")


@router.get("/stats/daily")
def get_daily_stats():
    """获取当天股票提及统计"""
    mentions = _storage_service.get_all_mentions()
    return _statistics_service.get_daily_stats(mentions)


@router.get("/stats/weekly")
def get_weekly_stats():
    """获取本周股票提及统计"""
    mentions = _storage_service.get_all_mentions()
    return _statistics_service.get_weekly_stats(mentions)


@router.get("/stats/monthly")
def get_monthly_stats(
    year: Optional[int] = Query(None, description="年份，默认今年"),
    month: Optional[int] = Query(None, description="月份，默认当月"),
):
    """获取指定月份股票提及统计"""
    mentions = _storage_service.get_all_mentions()
    return _statistics_service.get_monthly_stats(mentions, year=year, month=month)


@router.get("/stock/{code}/details")
def get_stock_details(
    code: str,
    period_type: str = Query("daily", description="统计类型: daily/weekly/monthly"),
    date_str: Optional[str] = Query(None, alias="date", description="目标日期 YYYY-MM-DD"),
    year: Optional[int] = Query(None, description="年份"),
    month: Optional[int] = Query(None, description="月份"),
):
    """获取指定股票在指定时段的提及详情"""
    mentions = _storage_service.get_all_mentions()
    target_date = None
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            pass
    return _statistics_service.get_stock_details(
        mentions, code, period_type,
        target_date=target_date, year=year, month=month,
    )


@router.get("/week-info")
def get_week_info(
    year: int = Query(..., description="年份"),
    month: int = Query(..., description="月份"),
):
    """获取指定月份的周标注信息"""
    return _statistics_service.get_week_info(year, month)


@router.post("/refresh")
def refresh_data():
    """手动刷新：重新全量匹配"""
    from ..main import run_full_match
    result = run_full_match()
    return {"status": "ok", "message": "全量刷新完成", "details": result}


@router.post("/incremental-refresh")
def incremental_refresh_data():
    """手动增量刷新：仅匹配新消息"""
    from ..main import run_incremental_match
    result = run_incremental_match()
    return {"status": "ok", "message": "增量刷新完成", "details": result}


@router.get("/health")
def health_check():
    """健康检查"""
    mentions = _storage_service.get_all_mentions()
    return {
        "status": "ok",
        "total_mentions": len(mentions),
        "last_processed_id": _storage_service.get_last_processed_id(),
    }