class StateManager:
    def __init__(self, db_url=None): pass
    def get_position(self, s): return 0.0
    def update_position(self, s, q, p=None): pass
    def record_signal(self, *a): pass
    def record_execution(self, *a): pass
