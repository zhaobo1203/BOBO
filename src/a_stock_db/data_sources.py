# -*- coding: utf-8 -*-
"""
A股数据源模块
支持五个数据源：
- Baostock（主）
- 新浪财经（备1）
- 腾讯财经（备2）
- AKShare（备3）
- Efinance（备4）
自动测试速度和稳定性，选择最优数据源
"""

import time
from typing import Optional
from dataclasses import dataclass
import logging
import requests
import json

logger = logging.getLogger(__name__)


@dataclass
class StockInfo:
    """股票信息数据类"""
    code: str  # 股票代码
    name: str  # 股票名称


@dataclass
class DataSourceResult:
    """数据源获取结果"""
    success: bool
    stocks: list[StockInfo]
    count: int
    elapsed_time: float  # 耗时（秒）
    error_message: Optional[str] = None


class DataSourceBase:
    """数据源基类"""
    
    def fetch_stock_list(self) -> DataSourceResult:
        """获取股票列表"""
        raise NotImplementedError
    
    def _is_valid_stock(self, code: str) -> bool:
        """判断是否为有效股票（沪深主板、创业板、科创板、ETF）"""
        if not code:
            return False
        
        # 沪主板: 60xxxx
        if code.startswith('60') and len(code) == 6:
            return True
        # 深主板: 00xxxx (不含指数)
        if code.startswith('00') and len(code) == 6:
            return True
        # 创业板: 30xxxx
        if code.startswith('30') and len(code) == 6:
            return True
        # 科创板: 68xxxx
        if code.startswith('68') and len(code) == 6:
            return True
        # 沪市ETF: 51xxxx, 56xxxx, 58xxxx
        if code.startswith(('51', '56', '58')) and len(code) == 6:
            return True
        # 深市ETF: 15xxxx, 16xxxx
        if code.startswith(('15', '16')) and len(code) == 6:
            return True
        
        return False


class SinaFinanceSource(DataSourceBase):
    """新浪财经数据源 - 免费、无需注册"""
    
    def fetch_stock_list(self) -> DataSourceResult:
        start_time = time.time()
        try:
            stocks = []
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Referer": "http://vip.stock.finance.sina.com.cn/"
            }
            
            # 新浪财经A股列表接口 - 沪市和深市分别获取
            base_url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
            
            # 获取沪市A股 (node=hs_a)
            params_sh = {
                "page": 1,
                "num": 6000,
                "sort": "symbol",
                "asc": 1,
                "node": "hs_a",
                "symbol": "",
                "_s_r_a": "page"
            }
            
            try:
                resp_sh = requests.get(base_url, params=params_sh, headers=headers, timeout=30)
                if resp_sh.status_code == 200:
                    data_sh = resp_sh.json()
                    if data_sh:
                        for item in data_sh:
                            code = item.get('symbol', '')
                            name = item.get('name', '')
                            if self._is_valid_stock(code):
                                stocks.append(StockInfo(code=code, name=name))
            except Exception as e:
                logger.warning(f"新浪财经沪市接口失败: {e}")
            
            # 获取深市A股 (node=sz_a)
            params_sz = {
                "page": 1,
                "num": 6000,
                "sort": "symbol",
                "asc": 1,
                "node": "sz_a",
                "symbol": "",
                "_s_r_a": "page"
            }
            
            try:
                resp_sz = requests.get(base_url, params=params_sz, headers=headers, timeout=30)
                if resp_sz.status_code == 200:
                    data_sz = resp_sz.json()
                    if data_sz:
                        for item in data_sz:
                            code = item.get('symbol', '')
                            name = item.get('name', '')
                            if self._is_valid_stock(code):
                                stocks.append(StockInfo(code=code, name=name))
            except Exception as e:
                logger.warning(f"新浪财经深市接口失败: {e}")
            
            # 去重
            seen = set()
            unique_stocks = []
            for s in stocks:
                if s.code not in seen:
                    seen.add(s.code)
                    unique_stocks.append(s)
            
            # 如果没有获取到数据，抛出异常
            if not unique_stocks:
                raise Exception("新浪财经接口未返回有效数据")
            
            elapsed = time.time() - start_time
            return DataSourceResult(
                success=True,
                stocks=unique_stocks,
                count=len(unique_stocks),
                elapsed_time=elapsed
            )
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"新浪财经获取数据失败: {e}")
            return DataSourceResult(
                success=False,
                stocks=[],
                count=0,
                elapsed_time=elapsed,
                error_message=str(e)
            )


class TencentFinanceSource(DataSourceBase):
    """腾讯财经数据源 - 免费、无需注册"""
    
    def fetch_stock_list(self) -> DataSourceResult:
        start_time = time.time()
        try:
            stocks = []
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            }
            
            # 使用东方财富Web接口 - 这是一个公开的API
            # 获取沪深A股列表
            east_url = "http://82.push2.eastmoney.com/api/qt/clist/get"
            
            # 沪深A股参数
            params = {
                "pn": 1,
                "pz": 6000,
                "po": 1,
                "np": 1,
                "fltt": 2,
                "invt": 2,
                "fid": "f12",
                "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024",  # 沪深A股
                "fields": "f12,f14"  # f12=代码, f14=名称
            }
            
            try:
                resp = requests.get(east_url, params=params, headers=headers, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    if data and 'data' in data and 'diff' in data['data']:
                        for item in data['data']['diff']:
                            code = item.get('f12', '')
                            name = item.get('f14', '')
                            if self._is_valid_stock(code):
                                stocks.append(StockInfo(code=code, name=name))
            except Exception as e:
                logger.warning(f"东方财富接口失败: {e}")
            
            # 如果东方财富失败，尝试备用接口
            if not stocks:
                # 使用同花顺接口
                ths_url = "http://q.10jqka.com.cn/index/index/board/all/field/zdf/dir/desc/p/1"
                headers_ths = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "http://q.10jqka.com.cn/"
                }
                try:
                    resp = requests.get(ths_url, headers=headers_ths, timeout=30)
                    if resp.status_code == 200:
                        # 解析HTML（简单处理）
                        import re
                        pattern = r'<td>(\d{6})</td>.*?<td>(.*?)</td>'
                        matches = re.findall(pattern, resp.text, re.DOTALL)
                        for code, name in matches[:100]:  # 限制数量避免过多
                            if self._is_valid_stock(code):
                                stocks.append(StockInfo(code=code.strip(), name=name.strip()))
                except Exception as e:
                    logger.warning(f"同花顺接口失败: {e}")
            
            if not stocks:
                raise Exception("无法从任何免费接口获取数据")
            
            elapsed = time.time() - start_time
            return DataSourceResult(
                success=True,
                stocks=stocks,
                count=len(stocks),
                elapsed_time=elapsed
            )
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"腾讯财经获取数据失败: {e}")
            return DataSourceResult(
                success=False,
                stocks=[],
                count=0,
                elapsed_time=elapsed,
                error_message=str(e)
            )


class BaostockSource(DataSourceBase):
    """Baostock数据源"""
    
    def fetch_stock_list(self) -> DataSourceResult:
        start_time = time.time()
        try:
            import baostock as bs
            
            # 登录系统
            lg = bs.login()
            if lg.error_code != '0':
                raise Exception(f"Baostock登录失败: {lg.error_msg}")
            
            # 获取所有证券基本信息
            rs = bs.query_stock_basic()
            
            stocks = []
            while (rs.error_code == '0') & rs.next():
                row = rs.get_row_data()
                code = str(row[0]).strip()  # 代码格式: sh.600000 或 sz.000001
                name = str(row[1]).strip() if len(row) > 1 else ""
                
                # 转换代码格式
                if '.' in code:
                    pure_code = code.split('.')[1]
                else:
                    pure_code = code[2:] if len(code) > 6 else code
                
                if self._is_valid_stock(pure_code):
                    stocks.append(StockInfo(code=pure_code, name=name))
            
            bs.logout()
            
            elapsed = time.time() - start_time
            return DataSourceResult(
                success=True,
                stocks=stocks,
                count=len(stocks),
                elapsed_time=elapsed
            )
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Baostock获取数据失败: {e}")
            return DataSourceResult(
                success=False,
                stocks=[],
                count=0,
                elapsed_time=elapsed,
                error_message=str(e)
            )


class AKShareSource(DataSourceBase):
    """AKShare数据源 - 使用官方聚合接口获取完整A股列表"""
    
    def fetch_stock_list(self) -> DataSourceResult:
        start_time = time.time()
        stocks = []
        
        try:
            import akshare as ak
            
            # 使用 stock_info_a_code_name 获取沪深京A股完整列表
            # 该接口自动合并：上交所主板 + 科创板 + 深交所A股 + 北交所A股
            try:
                df = ak.stock_info_a_code_name()
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        code = str(row.get('code', '')).strip()
                        name = str(row.get('name', '')).strip()
                        if self._is_valid_stock(code):
                            stocks.append(StockInfo(code=code, name=name))
                    logger.info(f"AKShare聚合接口获取 {len(stocks)} 只股票")
            except Exception as e:
                logger.warning(f"AKShare聚合接口失败: {e}")
            
            # 备用方案：分步获取各交易所数据
            if len(stocks) < 3000:
                seen_codes = {s.code for s in stocks}
                
                # 获取深交所A股
                try:
                    sz_df = ak.stock_info_sz_name_code(symbol="A股列表")
                    if sz_df is not None and not sz_df.empty:
                        sz_count = 0
                        for _, row in sz_df.iterrows():
                            code = str(row.get('A股代码', '')).strip()
                            name = str(row.get('A股简称', '')).strip()
                            if self._is_valid_stock(code) and code not in seen_codes:
                                stocks.append(StockInfo(code=code, name=name))
                                seen_codes.add(code)
                                sz_count += 1
                        logger.info(f"深交所接口补充 {sz_count} 只股票")
                except Exception as e:
                    logger.warning(f"深交所接口失败: {e}")
                
                # 获取上交所主板A股
                try:
                    sh_df = ak.stock_info_sh_name_code(symbol="主板A股")
                    if sh_df is not None and not sh_df.empty:
                        sh_count = 0
                        for _, row in sh_df.iterrows():
                            code = str(row.get('证券代码', '')).strip()
                            name = str(row.get('证券简称', '')).strip()
                            if self._is_valid_stock(code) and code not in seen_codes:
                                stocks.append(StockInfo(code=code, name=name))
                                seen_codes.add(code)
                                sh_count += 1
                        logger.info(f"上交所主板接口补充 {sh_count} 只股票")
                except Exception as e:
                    logger.warning(f"上交所主板接口失败: {e}")
                
                # 获取科创板
                try:
                    kcb_df = ak.stock_info_sh_name_code(symbol="科创板")
                    if kcb_df is not None and not kcb_df.empty:
                        kcb_count = 0
                        for _, row in kcb_df.iterrows():
                            code = str(row.get('证券代码', '')).strip()
                            name = str(row.get('证券简称', '')).strip()
                            if self._is_valid_stock(code) and code not in seen_codes:
                                stocks.append(StockInfo(code=code, name=name))
                                seen_codes.add(code)
                                kcb_count += 1
                        logger.info(f"科创板接口补充 {kcb_count} 只股票")
                except Exception as e:
                    logger.warning(f"科创板接口失败: {e}")
            
            if not stocks:
                raise Exception("AKShare所有接口均获取失败")
            
            elapsed = time.time() - start_time
            return DataSourceResult(
                success=True,
                stocks=stocks,
                count=len(stocks),
                elapsed_time=elapsed
            )
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"AKShare获取数据失败: {e}")
            return DataSourceResult(
                success=False,
                stocks=[],
                count=0,
                elapsed_time=elapsed,
                error_message=str(e)
            )


class EfinanceSource(DataSourceBase):
    """Efinance数据源（东方财富）"""
    
    def fetch_stock_list(self) -> DataSourceResult:
        start_time = time.time()
        try:
            import efinance as ef
            
            df = ef.stock.get_realtime_quotes()
            
            stocks = []
            for _, row in df.iterrows():
                code = str(row['股票代码']).strip()
                name = str(row['股票名称']).strip()
                
                if self._is_valid_stock(code):
                    stocks.append(StockInfo(code=code, name=name))
            
            elapsed = time.time() - start_time
            return DataSourceResult(
                success=True,
                stocks=stocks,
                count=len(stocks),
                elapsed_time=elapsed
            )
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Efinance获取数据失败: {e}")
            return DataSourceResult(
                success=False,
                stocks=[],
                count=0,
                elapsed_time=elapsed,
                error_message=str(e)
            )


class TuShareSource(DataSourceBase):
    """TuShare数据源 - 需要注册获取token，免费使用"""
    
    def fetch_stock_list(self) -> DataSourceResult:
        start_time = time.time()
        try:
            import tushare as ts
            
            # TuShare需要token，如果未设置则跳过
            # 用户需要在 tushare.pro 注册并设置 token
            try:
                pro = ts.pro_api()
            except Exception as e:
                raise Exception("TuShare需要配置token，请先注册 https://tushare.pro 并设置token")
            
            # 获取股票列表
            df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name')
            
            stocks = []
            for _, row in df.iterrows():
                code = str(row['symbol']).strip()
                name = str(row['name']).strip()
                
                if self._is_valid_stock(code):
                    stocks.append(StockInfo(code=code, name=name))
            
            elapsed = time.time() - start_time
            return DataSourceResult(
                success=True,
                stocks=stocks,
                count=len(stocks),
                elapsed_time=elapsed
            )
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"TuShare获取数据失败: {e}")
            return DataSourceResult(
                success=False,
                stocks=[],
                count=0,
                elapsed_time=elapsed,
                error_message=str(e)
            )


class SinaSpotSource(DataSourceBase):
    """新浪财经实时行情数据源 - 通过AKShare调用"""
    
    def fetch_stock_list(self) -> DataSourceResult:
        start_time = time.time()
        try:
            import akshare as ak
            
            # 使用 stock_zh_a_spot 获取A股实时行情（包含代码和名称）
            df = ak.stock_zh_a_spot()
            
            stocks = []
            for _, row in df.iterrows():
                code_raw = str(row.get('代码', '')).strip()
                name = str(row.get('名称', '')).strip()
                
                # 新浪返回的代码带前缀如 sz301550，需要去掉前缀
                if len(code_raw) > 6:
                    code = code_raw[-6:]  # 取后6位
                else:
                    code = code_raw
                
                if self._is_valid_stock(code):
                    stocks.append(StockInfo(code=code, name=name))
            
            elapsed = time.time() - start_time
            return DataSourceResult(
                success=True,
                stocks=stocks,
                count=len(stocks),
                elapsed_time=elapsed
            )
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"新浪实时行情获取数据失败: {e}")
            return DataSourceResult(
                success=False,
                stocks=[],
                count=0,
                elapsed_time=elapsed,
                error_message=str(e)
            )


class DataSourceManager:
    """数据源管理器 - 自动测试并选择最优数据源"""
    
    def __init__(self):
        # 数据源优先级：
        # 主数据源：Baostock
        # 备用数据源：AKShare聚合、新浪实时行情、TuShare、Efinance、新浪财经、腾讯财经
        self.sources = [
            ("Baostock", BaostockSource()),                    # 主数据源
            ("AKShare聚合", AKShareSource()),                   # 备用1 - 官方聚合接口
            ("新浪实时行情", SinaSpotSource()),                  # 备用2 - 新浪实时行情
            ("TuShare", TuShareSource()),                      # 备用3 - 需要token
            ("Efinance", EfinanceSource()),                    # 备用4 - 东方财富
            ("新浪财经", SinaFinanceSource()),                  # 备用5 - 新浪接口
            ("腾讯财经", TencentFinanceSource()),               # 备用6 - 腾讯接口
        ]
        self.test_results: dict[str, DataSourceResult] = {}
    
    def test_all_sources(self) -> dict[str, DataSourceResult]:
        """测试所有数据源的速度和稳定性"""
        print("\n正在测试各数据源的速度和稳定性...")
        print("-" * 60)
        
        for name, source in self.sources:
            print(f"测试 {name}...", end=" ")
            result = source.fetch_stock_list()
            self.test_results[name] = result
            
            if result.success:
                print(f"[OK] 成功 | 获取 {result.count} 只股票 | 耗时 {result.elapsed_time:.2f}秒")
            else:
                print(f"[FAIL] 失败 | 错误: {result.error_message}")
        
        print("-" * 60)
        return self.test_results
    
    def get_best_source(self) -> tuple[Optional[str], Optional[DataSourceBase]]:
        """获取最优数据源"""
        successful = [
            (name, result) 
            for name, result in self.test_results.items() 
            if result.success
        ]
        
        if not successful:
            return None, None
        
        successful.sort(key=lambda x: x[1].elapsed_time)
        best_name = successful[0][0]
        
        for name, source in self.sources:
            if name == best_name:
                return best_name, source
        
        return None, None
    
    def fetch_with_fallback(self) -> DataSourceResult:
        """按优先级依次尝试获取数据"""
        for name, source in self.sources:
            print(f"尝试从 {name} 获取数据...")
            result = source.fetch_stock_list()
            
            if result.success:
                print(f"[OK] {name} 获取成功: {result.count} 只股票, 耗时 {result.elapsed_time:.2f}秒")
                return result
            else:
                print(f"[FAIL] {name} 获取失败: {result.error_message}")
        
        return DataSourceResult(
            success=False,
            stocks=[],
            count=0,
            elapsed_time=0,
            error_message="所有数据源均获取失败"
        )


def test_data_sources():
    """测试数据源函数"""
    manager = DataSourceManager()
    results = manager.test_all_sources()
    
    print("\n测试结果汇总:")
    print("=" * 60)
    for name, result in results.items():
        status = "[OK] 成功" if result.success else "[FAIL] 失败"
        print(f"{name}: {status}")
        if result.success:
            print(f"  - 股票数量: {result.count}")
            print(f"  - 耗时: {result.elapsed_time:.2f}秒")
        else:
            print(f"  - 错误: {result.error_message}")
    
    best_name, _ = manager.get_best_source()
    if best_name:
        print(f"\n推荐使用: {best_name}")
    else:
        print("\n警告: 没有可用的数据源!")


if __name__ == "__main__":
    test_data_sources()