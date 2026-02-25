import importlib
import inspect
import pkgutil
import sys
from pathlib import Path
from typing import Dict, Type, Optional, Any

from plugins.base_plugin import BasePlugin

class PluginManager:
    """管理所有插件，根据名称实例化插件"""
    def __init__(self, plugin_dirs=None):
        self.plugin_classes: Dict[str, Type[BasePlugin]] = {}
        if plugin_dirs is None:
            # 默认插件目录：项目根目录下的 plugins 包
            # 假设当前文件在 core/，项目根目录是 parent
            project_root = Path(__file__).parent.parent
            plugin_dirs = [project_root / 'plugins']
        self.plugin_dirs = plugin_dirs
        self.discover_plugins()

    def discover_plugins(self):
        """扫描插件目录，收集所有继承 BasePlugin 的类"""
        # 将插件目录加入 sys.path 以便导入
        for plugin_dir in self.plugin_dirs:
            if plugin_dir.exists() and str(plugin_dir) not in sys.path:
                sys.path.insert(0, str(plugin_dir))

        # 动态导入 plugins 包下的模块
        try:
            import plugins
        except ImportError:
            # 如果没有 plugins 包，则创建
            plugins = None

        # 遍历所有可能的模块
        for plugin_dir in self.plugin_dirs:
            if not plugin_dir.is_dir():
                continue
            for item in plugin_dir.iterdir():
                if item.suffix == '.py' and item.stem != '__init__':
                    module_name = item.stem
                    try:
                        module = importlib.import_module(module_name)
                        # 查找模块中继承 BasePlugin 的类
                        for name, obj in inspect.getmembers(module, inspect.isclass):
                            if issubclass(obj, BasePlugin) and obj is not BasePlugin:
                                # 使用类属性 plugin_name 或类名小写作为名称
                                plugin_name = getattr(obj, 'plugin_name', module_name)
                                self.plugin_classes[plugin_name] = obj
                    except Exception as e:
                        print(f"加载插件 {module_name} 失败: {e}")

    def get_plugin_names(self) -> list:
        """返回所有可用插件的名称列表"""
        return list(self.plugin_classes.keys())

    def get_plugin(self, name: str, config: dict = None) -> Optional[BasePlugin]:
        """根据名称和配置获取插件实例"""
        cls = self.plugin_classes.get(name)
        if cls:
            return cls(config or {})
        return None