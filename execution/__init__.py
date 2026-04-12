class Executor: pass
class SimExecutor(Executor):
    def send(self, order): return type('R',(),{'approved':True,'reason':'sim_ok'})()
