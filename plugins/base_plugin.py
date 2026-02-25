class BasePlugin:
    """所有插件必须继承此类，并实现需要的钩子方法"""

    def __init__(self, config: dict):
        """
        :param config: 插件配置字典
        """
        self.config = config

    def on_path_resolve(self, pipeline: dict, context: dict) -> tuple:
        """
        路径解析阶段调用，返回 (本地路径, 设备路径)
        :param pipeline: 原始 Pipeline 配置
        :param context: 上下文，包含 'adb', 'logger', 'pipeline'
        :return: (local_path, device_path)
        """
        return pipeline['local'], pipeline['device']

    def on_file_filter(self, file_info: dict, context: dict) -> bool:
        """
        文件过滤，返回 True 表示包含该文件
        :param file_info: 包含 'rel_path', 'size', 'mtime', 'is_dir' 等
        """
        return True

    def on_conflict(self, local_info: dict, device_info: dict, context: dict) -> str:
        """
        冲突处理（仅双向同步时调用），返回决策：'local', 'device', 'skip'
        """
        return 'skip'

    def on_sync_start(self, pipeline: dict, context: dict):
        """同步开始前调用"""
        pass

    def on_sync_end(self, pipeline: dict, context: dict, stats: dict):
        """同步结束后调用，stats 包含 upload/download/skip/error 计数"""
        pass

    def on_sync_error(self, pipeline: dict, context: dict, error: str):
        """同步出错时调用"""
        pass