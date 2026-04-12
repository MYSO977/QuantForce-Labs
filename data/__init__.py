class DataSource: pass
class SimSource(DataSource):
    def stream(self, sym, interval="1m"): yield from []
class CSVReplay(DataSource): pass
class IBKRSource(DataSource): pass
class NewsCatcher:
    def __init__(self, **k): pass
    def to_signal_meta(self, items): return {}
