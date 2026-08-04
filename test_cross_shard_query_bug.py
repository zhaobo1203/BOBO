"""
单元测试：验证 message_db 跨分片查询原逻辑的缺陷
测试目标：模拟多个分片，验证提前终止逻辑会导致遗漏最新消息
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

# 原逻辑：边查询边收集，达到limit提前终止
def original_cross_shard_query(shards: List[MockDbShard], limit: int) -> List[Dict]:
    messages = []
    for shard in shards:
        # 每个分片查询消息
        for msg in shard.messages:
            messages.append(msg)
            # 如果已经获取到足够消息，跳出循环
            if len(messages) >= limit:
                break
        if len(messages) >= limit:
            break
    # 排序返回前limit
    messages.sort(key=lambda x: int(x.get('create_time') or 0))
    return messages[:limit]

# 新逻辑：遍历所有分片，全部收集，全局排序，再截取
def new_cross_shard_query(shards: List[MockDbShard], limit: int) -> List[Dict]:
    messages = []
    for shard in shards:
        # 必须遍历完所有分片，不提前终止
        for msg in shard.messages:
            messages.append(msg)
    # 全局排序
    messages.sort(key=lambda x: int(x.get('create_time') or 0))
    # 截取最新的limit条
    return messages[-limit:] if len(messages) > limit else messages

def test_bug_scenario():
    """测试缺陷场景：最新消息在后面的分片，原逻辑会遗漏"""
    print("=" * 60)
    print("测试跨分片查询缺陷场景")
    print("场景：3个分片，最新消息在最后一个分片，limit=3")
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
    
    # 原逻辑执行
    original_result = original_cross_shard_query(shards, limit)
    original_times = [m['create_time'] for m in original_result]
    
    # 新逻辑执行
    new_result = new_cross_shard_query(shards, limit)
    new_times = [m['create_time'] for m in new_result]
    
    print(f"\n原逻辑结果（提前终止）: {original_times}")
    print(f"新逻辑结果（全部收集）: {new_times}")
    
    # 验证缺陷
    latest_expected = [400, 500, 600]
    is_correct_original = sorted(original_times) == latest_expected
    is_correct_new = sorted(new_times) == latest_expected
    
    print("\n结果验证:")
    print(f"期望最新 {limit} 条时间戳: {latest_expected}")
    print(f"原逻辑是否正确: [OK] 是" if is_correct_original else "原逻辑是否正确: [FAIL] 否 - 遗漏了最新消息")
    print(f"新逻辑是否正确: [OK] 是" if is_correct_new else "新逻辑是否正确: [FAIL] 否")
    
    print("\n结论:")
    if not is_correct_original:
        print("RED LIGHT! 原逻辑存在缺陷，最新消息在后面分片中被遗漏了")
    else:
        print("GREEN LIGHT! 原逻辑工作正常")
    
    return not is_correct_original

if __name__ == "__main__":
    has_bug = test_bug_scenario()
    sys.exit(1 if has_bug else 0)