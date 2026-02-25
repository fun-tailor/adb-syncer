import os
import time
from datetime import datetime, timedelta
from plugins.base_plugin import BasePlugin

class DateIntervalPlugin(BasePlugin):
    """
    根据间隔天数自动切换日期子目录。
    配置示例:
    {
        "base_path": "/sdcard/资料",
        "interval_days": 10,
        "date_format": "%m-%d",
        "start_date": "2026-01-01"   # 可选，默认为 2026-01-01
    }
    """
    plugin_name = "date_interval"

    def __init__(self, config):
        super().__init__(config)
        self.base_path = self.config.get('base_path', '')
        self.interval_days = self.config.get('interval_days', 10)
        self.date_format = self.config.get('date_format', '%m-%d')
        start_str = self.config.get('start_date', '2026-01-01')
        try:
            self.start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        except:
            self.start_date = datetime(2026, 1, 1).date()

    def on_path_resolve(self, pipeline: dict, context: dict) -> tuple:
        """根据当前日期计算设备路径"""
        today = datetime.now().date()
        days_since_start = (today - self.start_date).days
        period_index = days_since_start // self.interval_days
        period_start = self.start_date + timedelta(days=period_index * self.interval_days)
        date_str = period_start.strftime(self.date_format)
        # 设备路径 = base_path/date_str
        device_path = os.path.join(self.base_path, date_str).replace('\\', '/')
        # 本地路径保持不变
        return pipeline['local'], device_path

    def on_sync_start(self, pipeline: dict, context: dict):
        """确保设备目录存在"""
        adb = context['adb']
        local_path, device_path = self.on_path_resolve(pipeline, context)
        if not adb.file_exists(device_path):
            adb.mkdir(device_path)
            context['logger'].info(f"插件创建设备目录: {device_path}")