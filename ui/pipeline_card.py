import os
import logging
from PyQt6.QtWidgets import QCheckBox, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QFrame
from PyQt6.QtCore import Qt, pyqtSignal

from core.adb_manager import AdbManager
from core.sync_engine import SyncEngine
from core.plugin_manager import PluginManager

logger = logging.getLogger(__name__)

class PipelineCardWidget(QFrame):
    sync_requested = pyqtSignal(int)
    edit_requested = pyqtSignal(int)
    delete_requested = pyqtSignal(int)
    auto_sync_changed = pyqtSignal(int,bool) # 新增信号：索引，新状态

    def __init__(self, pipeline, index, adb: AdbManager, plugin_mgr: PluginManager, parent=None):
        super().__init__(parent)
        self.pipeline = pipeline
        self.index = index
        self.adb = adb
        self.plugin_mgr = plugin_mgr
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setLineWidth(1)
        self.setup_ui()
        self.update_status()  # 初始状态

    def setup_ui(self):
        layout = QHBoxLayout(self)

        # 状态指示圆点
        self.status_label = QLabel("●")
        self.status_label.setStyleSheet("color: gray; font-size: 16px;")
        layout.addWidget(self.status_label)

        # 文本信息
        text_layout = QVBoxLayout()
        self.name_label = QLabel(f"<b>{self.pipeline['name']}</b>")
        self.path_label = QLabel(self._get_display_path())
        self.path_label.setStyleSheet("color: gray; font-size: 10px;")
        self.path_label.setWordWrap(True)
        text_layout.addWidget(self.name_label)
        text_layout.addWidget(self.path_label)
        layout.addLayout(text_layout, stretch=1)


        self.auto_check = QCheckBox("自动")
        self.auto_check.setChecked(self.pipeline.get('auto_sync', False))
        self.auto_check.checkStateChanged.connect(self.on_auto_changed)
        layout.addWidget(self.auto_check)  # 放在同步按钮左侧或右侧

        # 按钮
        self.sync_btn = QPushButton("同步")
        self.sync_btn.clicked.connect(lambda: self.sync_requested.emit(self.index))
        layout.addWidget(self.sync_btn)

        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.index))
        layout.addWidget(edit_btn)

        delete_btn = QPushButton("删除")
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.index))
        layout.addWidget(delete_btn)

    def set_sync_button_enabled(self, enabled: bool):
        self.sync_btn.setEnabled(enabled)

    def on_auto_changed(self, state):
        self.pipeline['auto_sync'] = (state == Qt.CheckState.Checked) 
        # 保存到配置？可以通过信号通知 MainWindow 保存
        self.auto_sync_changed.emit(self.index, self.pipeline['auto_sync'])

    def _get_display_path(self):
        """生成显示路径（如果插件则显示解析后的实际路径）"""
        # 简单显示原始路径，实际可动态解析
        return f"{self.pipeline['local']}  ↔  {self.pipeline['device']}"

    # def update_status(self):
    #     """根据当前设备状态和路径存在性更新圆点和同步按钮"""
    #     if not self.adb.current_device or not self.adb.is_connected():
    #         self.status_label.setStyleSheet("color: gray; font-size: 16px;")
    #         self.sync_btn.setEnabled(False)
    #         return

    #     # 获取实际路径（可能被插件修改）
    #     local_path, device_path = self._resolve_paths()
    #     if not local_path or not device_path:
    #         self.status_label.setStyleSheet("color: red; font-size: 16px;")
    #         self.sync_btn.setEnabled(False)
    #         return

    #     local_exists = os.path.isdir(local_path)
    #     device_exists = self.adb.file_exists(device_path)

    #     if local_exists and device_exists:
    #         self.status_label.setStyleSheet("color: green; font-size: 16px;")
    #         self.sync_btn.setEnabled(True)
    #     else:
    #         self.status_label.setStyleSheet("color: red; font-size: 16px;")
    #         self.sync_btn.setEnabled(False)

    def update_status(self, local_exists=None, device_exists=None):
        """根据路径存在性更新状态（如果未提供，则基于当前设备状态）"""
        if not self.adb.current_device or not self.adb.is_connected():
            self.status_label.setStyleSheet("color: gray; font-size: 16px;")
            self.sync_btn.setEnabled(False)
            return

        if local_exists is None or device_exists is None:
            # 如果未提供，则自己检查（同步方式，用于非异步场景）
            local_exists = os.path.isdir(self.pipeline['local'])
            device_exists = self.adb.file_exists(self.pipeline['device'])

        if local_exists and device_exists:
            self.status_label.setStyleSheet("color: green; font-size: 16px;")
            self.sync_btn.setEnabled(True)
        else:
            self.status_label.setStyleSheet("color: red; font-size: 16px;")
            self.sync_btn.setEnabled(False)


    def _resolve_paths(self):
        """使用插件解析路径（如果有）"""
        plugin = None
        if self.pipeline.get('plugin'):
            plugin = self.plugin_mgr.get_plugin(self.pipeline['plugin'], self.pipeline.get('plugin_config', {}))
        if plugin and hasattr(plugin, 'on_path_resolve'):
            try:
                local, device = plugin.on_path_resolve(self.pipeline, {'adb': self.adb})
                return local, device
            except Exception as e:
                logger.error(f"插件路径解析失败: {e}")
                return None, None
        return self.pipeline['local'], self.pipeline['device']