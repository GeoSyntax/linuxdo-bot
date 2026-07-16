"""布隆过滤器测试：去重正确性 + 无假阴性 + 内存估算。"""
from zhihu_crawler.distributed.dedup import BloomFilter, _optimal_params


def test_no_false_negatives():
    """加入过的元素一定判为存在（布隆不产生假阴性）。"""
    bf = BloomFilter(capacity=10000, error_rate=0.01)
    items = [f"url-{i}" for i in range(1000)]
    for it in items:
        bf.add(it)
    for it in items:
        assert it in bf


def test_add_returns_seen_flag():
    bf = BloomFilter(capacity=1000)
    assert bf.add("x") is False   # 首次：未见过
    assert bf.add("x") is True    # 再次：已见过


def test_dedup_count():
    bf = BloomFilter(capacity=10000)
    for _ in range(3):
        bf.add("same")
    bf.add("other")
    assert len(bf) == 2


def test_optimal_params():
    """1 亿、1% 误判 -> 位数约 9.58 亿，内存约 114MB。"""
    m, k = _optimal_params(100_000_000, 0.01)
    assert 9.0e8 < m < 1.0e9
    assert 6 <= k <= 8
    assert m / 8 / 1024 / 1024 < 130  # < 130MB


def test_false_positive_rate_reasonable():
    """未加入元素的误判率应接近设定值。"""
    bf = BloomFilter(capacity=10000, error_rate=0.01)
    for i in range(5000):
        bf.add(f"seen-{i}")
    fp = sum(1 for i in range(5000) if f"unseen-{i}" in bf)
    assert fp / 5000 < 0.05  # 宽松上界
