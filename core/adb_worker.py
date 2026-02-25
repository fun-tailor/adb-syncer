# core/adb_worker.py
from PyQt6.QtCore import QObject, pyqtSignal
from core.adb_manager import AdbManager

class AdbWorker(QObject):
    """在后台线程执行 ADB 查询，通过信号返回结果"""
    finished = pyqtSignal(object)  # 携带结果
    error = pyqtSignal(str)

    def __init__(self, adb: AdbManager,device_path):
        super().__init__()
        self.adb = adb
        self.device_path =device_path

    def run(self):
        self.check_path_exists(self.device_path)

    def check_path_exists(self, device_path: str):
        """检查设备路径是否存在"""
        try:
            exists = self.adb.file_exists(device_path)
            self.finished.emit(('path_exists', device_path, exists))
        except Exception as e:
            self.error.emit(str(e))

    def get_device_files(self, device_path: str):
        """获取设备文件列表（递归）"""
        try:
            files = self.adb.list_files_recursive(device_path)
            self.finished.emit(('device_files', device_path, files))
        except Exception as e:
            self.error.emit(str(e))