import json
from PyQt6.QtWidgets import (QDialog, QPushButton, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QLineEdit, QComboBox, QSpinBox, QDialogButtonBox,
                             QGroupBox, QLabel, QPlainTextEdit, QCheckBox)
from PyQt6.QtCore import QThread, Qt

from core.adb_worker import AdbWorker

# combobox 或改为 lineEdit

class PipelineDialog(QDialog):
    def __init__(self, parent=None, pipeline=None, plugin_names=None):
        super().__init__(parent)
        self.setWindowTitle("新建 Pipeline" if pipeline is None else "编辑 Pipeline")
        self.pipeline = pipeline or {}
        self.plugin_names = plugin_names or []
        self.setup_ui()

        self._test_worker = None
        self._test_thread = None

    def setup_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        # 名称
        self.name_edit = QLineEdit()
        self.name_edit.setText(self.pipeline.get('name', ''))
        form.addRow("名称:", self.name_edit)

        # 本地路径
        local_layout = QHBoxLayout()
        self.local_edit = QLineEdit()
        self.local_edit.setText(self.pipeline.get('local', ''))
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_local)
        local_layout.addWidget(self.local_edit)
        local_layout.addWidget(browse_btn)
        form.addRow("本地路径:", local_layout)

        # 设备路径
        device_layout = QHBoxLayout()
        self.device_edit = QLineEdit()
        self.device_edit.setText(self.pipeline.get('device', ''))
        self.device_edit.setPlaceholderText("例如: /sdcard/DCIM/")
        device_layout.addWidget(self.device_edit)
        test_btn = QPushButton("测试")
        test_btn.clicked.connect(self.test_device_path)
        device_layout.addWidget(test_btn)
        form.addRow("设备路径:", device_layout)

        # 设备序列号选择
        serial_layout = QHBoxLayout()
        self.device_serial_edit = QLineEdit()
        self.device_serial_edit.setPlaceholderText("默认不设置")

        self.device_serial_edit.setText(self.pipeline.get('device_serial', ''))
        serial_layout.addWidget(self.device_serial_edit)
        use_current_btn = QPushButton("使用当前设备")
        use_current_btn.clicked.connect(self.use_current_device)
        serial_layout.addWidget(use_current_btn)

        form.addRow("设备序列号:", serial_layout)


        # 添加一个状态标签显示测试结果
        self.test_result_label = QLabel("")
        form.addRow("", self.test_result_label)

        # 同步方向
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["local_to_device", "device_to_local", "bidirectional"])
        self.direction_combo.setCurrentText(self.pipeline.get('direction', 'local_to_device'))
        form.addRow("同步方向:", self.direction_combo)

        # 包含扩展名
        self.include_edit = QLineEdit()
        self.include_edit.setText(','.join(self.pipeline.get('include_extensions', [])))
        self.include_edit.setPlaceholderText("例如: .jpg,.png，留空表示所有")
        form.addRow("包含扩展名:", self.include_edit)

        # 排除扩展名
        self.exclude_edit = QLineEdit()
        self.exclude_edit.setText(','.join(self.pipeline.get('exclude_extensions', [])))
        self.exclude_edit.setPlaceholderText("例如: .tmp")
        form.addRow("排除扩展名:", self.exclude_edit)

        # 同步天数
        self.sync_days_spin = QSpinBox()
        self.sync_days_spin.setRange(0, 999)
        self.sync_days_spin.setValue(self.pipeline.get('sync_days', 1))
        self.sync_days_spin.setSpecialValueText("全部")
        form.addRow("同步最近天数(0=全部):", self.sync_days_spin)

        # 插件选择
        self.plugin_combo = QComboBox()
        self.plugin_combo.addItem("(无)", None)
        for name in self.plugin_names:
            self.plugin_combo.addItem(name, name)
        current_plugin = self.pipeline.get('plugin')
        if current_plugin in self.plugin_names:
            self.plugin_combo.setCurrentText(current_plugin)
        else:
            self.plugin_combo.setCurrentIndex(0)
        form.addRow("插件:", self.plugin_combo)

        # 插件配置 JSON 输入
        self.plugin_config_edit = QPlainTextEdit()
        self.plugin_config_edit.setPlaceholderText("请输入插件配置 JSON，例如 {\"interval_days\": 10, \"date_format\": \"%m-%d\"}")
        plugin_config = self.pipeline.get('plugin_config', {})
        if plugin_config:
            self.plugin_config_edit.setPlainText(json.dumps(plugin_config, indent=2, ensure_ascii=False))
        self.plugin_config_edit.setMaximumHeight(150)
        form.addRow("插件配置:", self.plugin_config_edit)

        layout.addLayout(form)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def use_current_device(self):
        adb = self.parent().adb  # 假设 parent 是 MainWindow，且有 adb 属性
        current_device = adb.current_device
        if current_device:
            self.device_serial_edit.setText(current_device)

    def browse_local(self):
        from PyQt6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "选择本地文件夹")
        if folder:
            self.local_edit.setText(folder)

    def test_device_path(self):
        device_path = self.device_edit.text().strip()
        if not device_path:
            return
        
        # 获取设备序列号
        device_serial = self.device_serial_edit.text().strip()
        
        adb = self.parent().adb  # 假设 parent 是 MainWindow，且有 adb 属性
        current_device = adb.current_device

        if not current_device:
            self.test_result_label.setText("设备未连接")
            self.test_result_label.setStyleSheet("color: grey;")
            return
        
        if device_serial:
            if current_device != device_serial:
                self.test_result_label.setText("设备序列不一致")
                self.test_result_label.setStyleSheet("color: red;")
                return
                # device_serial = self.parent().adb.current_device
        
        # 如果已有正在运行的测试，先停止（可选）
        if self._test_thread:
            if self._test_thread.isRunning():
                self._test_thread.quit()
                self._test_thread.wait(1000)

        self._test_thread = QThread()
        self._test_worker = AdbWorker(adb,device_path=device_path)
        self._test_worker.moveToThread(self._test_thread)

        self._test_thread.started.connect(self._test_worker.run)
        self._test_worker.finished.connect(self.on_test_done)
        self._test_worker.error.connect(self.on_test_error)

        # 安全的清理逻辑（保证线程退出后再销毁对象）
        def cleanup():
            # 清理实例属性（避免内存泄漏）
            if hasattr(self, '_test_worker'):
                self._test_worker = None
            if hasattr(self, '_test_thread'):
                self._test_thread = None


        # 结束退出
        self._test_worker.finished.connect(self._test_thread.quit)
        self._test_worker.error.connect(self._test_thread.quit)

        # 清理
        self._test_worker.finished.connect(self._test_worker.deleteLater)
        self._test_worker.error.connect(self._test_worker.deleteLater)
        self._test_thread.finished.connect(self._test_thread.deleteLater)

        # 清理实例绑定
        self._test_thread.finished.connect(cleanup)

        self._test_thread.start()
        self.test_result_label.setText("检查中...")
        self.test_result_label.setStyleSheet("color: grey;")
        

    def on_test_done(self, result):
        if result[0] == 'path_exists':
            exists = result[2]
            if exists:
                self.test_result_label.setText("存在")
                self.test_result_label.setStyleSheet("color: green;") # 取代 green，或标准淡绿("color: #90EE90;"))
            else:
                self.test_result_label.setText("不存在")
                self.test_result_label.setStyleSheet("color: red;")

    def on_test_error(self, error_msg):
        self.test_result_label.setText(f"错误: {error_msg}")
        self.test_result_label.setStyleSheet("color: lightred;")

    def get_pipeline(self):
        """返回填写的 pipeline 字典"""
        include = [ext.strip() for ext in self.include_edit.text().split(',') if ext.strip()]
        exclude = [ext.strip() for ext in self.exclude_edit.text().split(',') if ext.strip()]

        plugin = self.plugin_combo.currentData()
        plugin_config = {}
        if plugin:
            try:
                plugin_config = json.loads(self.plugin_config_edit.toPlainText())
            except json.JSONDecodeError:
                # 如果 JSON 无效，则使用空字典
                pass
        
        # 获取设备序列号
        device_serial = self.device_serial_edit.text().strip()

        return {
            'name': self.name_edit.text(),
            'local': self.local_edit.text(),
            'device': self.device_edit.text(),
            'device_serial': device_serial,
            'direction': self.direction_combo.currentText(),
            'include_extensions': include,
            'exclude_extensions': exclude,
            'sync_days': self.sync_days_spin.value(),
            'plugin': plugin,
            'plugin_config': plugin_config,
            'auto_sync': self.pipeline.get('auto_sync', False)  # 保持原值，新建时为 False

        }