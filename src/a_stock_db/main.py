
# -*- coding: utf-8 -*-
"""
A股数据库主程序
交互式菜单：1.更新数据  2.查看数据
支持命令行参数：--update, --view, --test
"""

import sys
import argparse
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

from a_stock_db.data_sources import DataSourceManager, DataSourceResult
from a_stock_db.database import AStockDatabase, DatabaseStats


def print_header():
    """打印程序头部信息"""
    print("\n" + "=" * 50)
    print("        A股数据库管理系统")
    print("=" * 50)


def print_menu():
    """打印菜单选项"""
    print("\n请选择操作:")
    print("  1. 更新数据")
    print("  2. 查看数据")
    print("  0. 退出")
    print("-" * 50)


def update_data(db: AStockDatabase):
    """更新股票数据
    
    首次更新：下载所有A股股票数据
    后续更新：只修改替换有变化的数据
    """
    print("\n" + "=" * 50)
    print("【更新数据】")
    print("=" * 50)
    
    # 获取当前数据库状态
    current_count = db.get_stock_count()
    if current_count == 0:
        print("首次更新，将下载所有A股股票数据...")
    else:
        print(f"当前数据库已有 {current_count} 只股票，将进行增量更新...")
    
    # 使用数据源管理器获取数据
    manager = DataSourceManager()
    
    print("\n开始获取股票数据...")
    result = manager.fetch_with_fallback()
    
    if not result.success:
        print(f"\n✗ 更新失败: {result.error_message}")
        print("请检查网络连接后重试。")
        return
    
    # 保存到数据库
    print("\n正在保存到数据库...")
    stocks_data = [(stock.code, stock.name) for stock in result.stocks]
    stats = db.update_stocks(stocks_data, source="akshare")  # 记录实际使用的数据源
    
    # 显示更新结果
    print("\n" + "-" * 50)
    print("更新完成!")
    print("-" * 50)
    
    if current_count == 0:
        # 首次更新
        print(f"[OK] 已下载 {stats.total_count} 只A股股票数据")
    else:
        # 增量更新
        print(f"[OK] 当前总数: {stats.total_count} 只股票")
        if stats.added_count > 0:
            print(f"[+] 新增: {stats.added_count} 只股票")
        if stats.removed_count > 0:
            print(f"[-] 移除: {stats.removed_count} 只股票（已退市）")
        if stats.added_count == 0 and stats.removed_count == 0:
            print("[OK] 数据无变化")
    
    print(f"\n数据库位置: {db.db_path}")


def view_data(db: AStockDatabase):
    """查看股票数据
    
    显示A股总数和更新信息
    """
    print("\n" + "=" * 50)
    print("【查看数据】")
    print("=" * 50)
    
    stats = db.get_stats()
    
    if stats.total_count == 0:
        print("\n数据库为空，请先执行「更新数据」")
        return
    
    print(f"\nA股股票总数: {stats.total_count} 只")
    
    if stats.last_update_time:
        print(f"最后更新时间: {stats.last_update_time}")
    
    # 显示部分股票示例
    print("\n前10只股票示例:")
    print("-" * 30)
    stocks = db.get_all_stocks()[:10]
    for code, name in stocks:
        print(f"  {code} | {name}")
    
    if stats.total_count > 10:
        print(f"  ... 共 {stats.total_count} 只股票")
    
    print("-" * 30)
    print(f"\n数据库位置: {db.db_path}")


def test_sources():
    """测试数据源速度和稳定性"""
    print("\n" + "=" * 50)
    print("【数据源测试】")
    print("=" * 50)
    
    manager = DataSourceManager()
    results = manager.test_all_sources()
    
    # 找出最优数据源
    best_name, _ = manager.get_best_source()
    if best_name:
        print(f"\n推荐数据源: {best_name}")
    else:
        print("\n警告: 没有可用的数据源!")


def main():
    """主程序入口"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='A股数据库管理系统')
    parser.add_argument('--update', action='store_true', help='更新数据')
    parser.add_argument('--view', action='store_true', help='查看数据')
    parser.add_argument('--test', action='store_true', help='测试数据源')
    args = parser.parse_args()
    
    # 初始化数据库
    db = AStockDatabase()
    
    # 命令行模式
    if args.update:
        update_data(db)
        return
    elif args.view:
        view_data(db)
        return
    elif args.test:
        test_sources()
        return
    
    # 交互式菜单模式
    while True:
        print_header()
        print_menu()
        
        try:
            choice = input("请输入选项 (0-2): ").strip()
            
            if choice == "1":
                update_data(db)
            elif choice == "2":
                view_data(db)
            elif choice == "0":
                print("\n感谢使用，再见！")
                break
            else:
                print("\n无效选项，请重新输入")
            
            input("\n按回车键继续...")
            
        except KeyboardInterrupt:
            print("\n\n程序已退出")
            break
        except Exception as e:
            print(f"\n发生错误: {e}")
            input("按回车键继续...")


if __name__ == "__main__":
    main()
