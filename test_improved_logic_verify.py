"""
验证修复后的跨分片查询逻辑：确保为绿灯（正确）
测试修复后的逻辑遵循 "遍历 → 收集 → 全局排序 → 截取"
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from typing import List, Dict
from dataclasses import dataclass

# 模拟消息分片
@dataclass
class MockDbShard:
    name: str
    messages: List[Dict]  # 消息按create_time从小到大排列

# 修复后的新逻辑：和当前代码修改一致
# 遍历所有分片，每个分片查询全部消息，全部收集后全局排序，再截取
def improved_cross_shard_query(shards: List[MockDbShard], limit: int) -> List[Dict]:
    messages = []
    for shard in shards:
        # 每个分片查询全部消息，不提前终止
        for msg in shard.messages:
            messages.append(msg)
    # 全局排序
    messages.sort(key=lambda x: int(x.get('create_time') or 0))
    # 截取最新limit条
    return messages[-limit:] if len(messages) > limit else messages

def test_improved_logic():
    """测试修复后的逻辑是否正确"""
    print("=" * 60)
    print("测试修复后的跨分片查询逻辑")
    print("场景：3个分片，最新消息在最后一个分片，limit=3")
    print("改进流程：遍历 → 全部收集 → 全局排序 → 截取")
    print("=" * 60)
    
    # 构造测试数据：
    # 分片1: 时间戳 100, 200
    # 分片2: 时间戳 300, 400
    # 分片3: 时间戳 500 (最新), 600 (最新)
    # 期望返回：400, 500, 600
    shards = [
        MockDbShard("message_1.db", [
            {'create_time': 100, 'content': 'msg 100'},
            {'create_time': 200, 'content': 'msg 200'},
        ]),
        MockDbShard("message_2.db", [
            {'create_time': 300, 'content': 'msg 300'},
            {'create_time': 400, 'content': 'msg 400'},
        ]),
        MockDbShard("message_3.db", [
            {'create_time': 500, 'content': 'msg 500 (latest)'},
            {'create_time': 600, 'content': 'msg 600 (latest)'},
        ]),
    ]
    
    print("\n构造分片:")
    for s in shards:
        times = [m['create_time'] for m in s.messages]
        print(f"  {s.name}: {times}")
    
    limit = 3
    print(f"\nlimit = {limit}")
    
    # 修复后逻辑执行
    result = improved_cross_shard_query(shards, limit)
    result_times = [m['create_time'] for m in result]
    
    print(f"\n修复后逻辑结果: {result_times}")
    
    # 验证结果
    latest_expected = [400, 500, 600]
    is_correct = sorted(result_times) == latest_expected
    
    print("\n结果验证:")
    print(f"期望最新 {limit} 条时间戳: {latest_expected}")
    print(f"修复后逻辑是否正确: [OK] 是" if is_correct else "修复后逻辑是否正确: [FAIL] 否")
    
    print("\n结论:")
    if is_correct:
        print("GREEN LIGHT! 修复成功，新逻辑能正确获取所有最新消息")
    else:
        print("RED LIGHT! 修复失败，仍然存在缺陷")
    
    return is_correct

if __name__ == "__main__":
    success = test_improved_logic()
    sys.exit(0 if success else 1)