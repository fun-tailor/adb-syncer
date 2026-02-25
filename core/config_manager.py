import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

# 配置目录：~/.adb_syncer/
# CONFIG_DIR = Path.home() / '.adb_syncer' 
def get_config_dir():
    """返回配置文件存储目录（可执行文件所在目录）"""
    if getattr(sys, 'frozen', False):
        # 打包后：sys.executable 是 exe 的路径
        exe_path = Path(sys.executable).resolve()
    else:
        # 开发时：sys.argv[0] 是主脚本路径（main.py）
        exe_path = Path(sys.argv[0]).resolve()
    return exe_path.parent

# PROJECT_ROOT = Path(__file__).parent.parent # 项目根目录
CONFIG_DIR = get_config_dir()
CONFIG_FILE = CONFIG_DIR / 'config.json'

class ConfigManager:
    def __init__(self):
        self.config_path = CONFIG_FILE
        self.pipelines = []
        self.load()

    def load(self):
        """从文件加载配置"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    pipelines = data.get('pipelines', [])
                    self.pipelines = pipelines
            except Exception as e:
                print(f"加载配置失败: {e}")
                self.pipelines = []
        else:
            self.pipelines = []

    def save(self):
        """保存配置到文件"""
        CONFIG_DIR.mkdir(exist_ok=True)
        data = {'version': '2.0', 
                'pipelines': self.pipelines}
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存配置失败: {e}")

    def add_pipeline(self, pipeline: Dict[str, Any]):
        self.pipelines.append(pipeline)
        self.save()

    def update_pipeline(self, index: int, pipeline: Dict[str, Any]):
        if 0 <= index < len(self.pipelines):
            self.pipelines[index] = pipeline
            self.save()

    def delete_pipeline(self, index: int):
        if 0 <= index < len(self.pipelines):
            del self.pipelines[index]
            self.save()