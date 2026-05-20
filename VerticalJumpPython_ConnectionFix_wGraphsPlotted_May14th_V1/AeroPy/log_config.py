# log_config.py
import logging

class LogListener(logging.Handler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        msg = self.format(record)
        self.callback(msg)


logger = logging.getLogger("shared_logger")
logger.setLevel(logging.INFO)

def register_listener(callback):
    handler = LogListener(callback)
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
