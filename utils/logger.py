import logging
from PyQt6.QtCore import QObject, pyqtSignal

class QTextEditLogger(logging.Handler, QObject):
    """将日志输出到 QTextEdit 的自定义 Handler"""
    new_log = pyqtSignal(str)

    def __init__(self, parent=None):
        logging.Handler.__init__(self)
        QObject.__init__(self, parent)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
        self.setFormatter(formatter)
        self.setLevel(logging.INFO)

    def emit(self, record):
        msg = self.format(record)
        self.new_log.emit(msg)