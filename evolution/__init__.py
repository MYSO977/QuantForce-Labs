class PerformanceTracker:
    def __init__(self, log_dir="evolution/trades"): pass
    def log_trade(self, *a): pass
    def calc_metrics(self, w=86400*7): return {"sharpe":0,"count":0}
class AutoIterator:
    def __init__(self, cfg, space): pass
    def check_and_iterate(self, m): return False
    def promote_best(self, t=0.8): pass
