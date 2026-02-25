import os
import logging
import time
from PyQt6.QtWidgets import (QMainWindow, QProgressBar, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QListWidget, QListWidgetItem,
                             QMessageBox, QStatusBar, QApplication)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread

from core.adb_manager import AdbManager, AdbError
from core.adb_worker import AdbWorker
from core.config_manager import ConfigManager
from core.sync_engine import SyncEngine
from core.plugin_manager import PluginManager
from utils.logger import QTextEditLogger
from ui.pipeline_card import PipelineCardWidget
from ui.pipeline_dialog import PipelineDialog

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ADB 同步器")
        self.resize(800, 600)

        self.device_was_connected = False  #记录设备上一次连接状态
        self.last_auto_sync_time = {}  # {pipeline_index: timestamp}

        # 初始化核心模块
        self.adb = AdbManager()
        self.config = ConfigManager()
        self.plugin_mgr = PluginManager()
        self.sync_engine = SyncEngine(self.adb, self.plugin_mgr)

        # 设置日志
        self.log_handler = QTextEditLogger(self)
        self.log_handler.new_log.connect(self.append_log)
        logging.getLogger().addHandler(self.log_handler)
        logging.getLogger().setLevel(logging.INFO)

        # 初始化UI
        self.setup_ui()

        self.current_check_thread = None
        self.current_check_worker = None

        self.device_connected_now = False
        self.refreshed_pipe_item = False # 记录 pipe 的设备状态显示

        # 添加成员变量记录自动同步时间
        self.device_was_connected = False
        self.last_auto_sync_time = {}
        self._check_workers = []  # 用于路径检查线程

        # 启动定时器检测设备
        self.device_timer = QTimer()
        self.device_timer.timeout.connect(self.check_device)
        self.device_timer.start(5000)  # 5秒
        self.check_device()  # 立即检测一次

        # 加载 Pipeline 并刷新状态
        self.refresh_pipeline_list()


    def setup_ui(self):
        # 中央部件
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # 顶部设备状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.device_label = QLabel("设备: 未连接")
        self.status_bar.addWidget(self.device_label)

        # 在状态栏添加进度条
        self.sync_progress = QProgressBar()
        self.sync_progress.setVisible(False)
        self.sync_progress.setMaximumWidth(200)
        self.status_bar.addPermanentWidget(self.sync_progress)

        # 刷新设备按钮
        refresh_btn = QPushButton("刷新设备")
        refresh_btn.clicked.connect(self.check_device)
        self.status_bar.addPermanentWidget(refresh_btn)

        # Pipeline 区域标题
        pipeline_label = QLabel("同步 Pipelines")
        pipeline_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(pipeline_label)

        # Pipeline 卡片列表
        self.pipeline_list = QListWidget()
        self.pipeline_list.setMaximumHeight(400)
        layout.addWidget(self.pipeline_list)

        # 添加 Pipeline 按钮
        add_pipeline_btn = QPushButton("+ 新建 Pipeline")
        add_pipeline_btn.clicked.connect(self.add_pipeline)
        layout.addWidget(add_pipeline_btn)

        # 日志区域标题
        log_label = QLabel("日志")
        log_label.setStyleSheet("font-weight: bold; font-size: 14px; margin-top: 10px;")
        layout.addWidget(log_label)

        # 日志显示
        self.log_text = QListWidget()
        self.log_text.setMaximumHeight(150)
        layout.addWidget(self.log_text)



    def append_log(self, msg):
        """将日志消息添加到列表控件"""
        self.log_text.addItem(msg)
        self.log_text.scrollToBottom()

    def check_device(self):
        # 在 check_device 中检测设备从断开变为连接时，触发自动同步扫描。
        try:
            devices = self.adb.get_devices()
            if devices:
                # 选择第一个在线设备
                if self.adb.current_device not in devices:
                    self.adb.current_device = devices[0]
                    self.device_label.setText(f"设备: 已连接 ({self.adb.current_device})")
                    self.device_label.setStyleSheet("color: green;")
                    self.device_connected_now = True

                    # 刷新状态(每次有新设备时)
                    self.refresh_pipeline_status()
                    self.refreshed_pipe_item = False

                else:
                    pass
            else:
                self.adb.current_device = None
                self.device_label.setText("设备: 未连接")
                self.device_label.setStyleSheet("color: gray;")
                self.device_connected_now = False

                if not self.refreshed_pipe_item:
                    self.refresh_pipeline_status()
                    self.refreshed_pipe_item = True
        except AdbError as e:
            # print('red')
            self.adb.current_device = None
            self.device_label.setText(f"设备: 错误 - {str(e)}")
            self.device_label.setStyleSheet("color: red;")
            self.device_connected_now = False

        # 检测设备刚连接
        if self.device_connected_now and not self.device_was_connected:
            self.trigger_auto_sync()
        self.device_was_connected = self.device_connected_now

            
    def trigger_auto_sync(self):
        """设备刚连接时，检查所有开启自动同步的 Pipeline 是否需要执行同步"""
        now = time.time()
        for i in range(self.pipeline_list.count()):
            item = self.pipeline_list.item(i)
            widget = self.pipeline_list.itemWidget(item)
            if widget and widget.auto_check.isChecked(): # widget 的同步按钮是否启用
                
                # 检查间隔（30分钟）
                last = self.last_auto_sync_time.get(i, 0)
                if last != 0 and (now - last <= 1800): # 冷却时间（1800秒），0或30分钟以外，都执行同步
                    continue
            
                self.on_sync_requested(i)
                self.last_auto_sync_time[i] = now
                logger.info(f"自动触发同步: {widget.pipeline['name']}")

    def refresh_pipeline_list(self):
        """从配置加载所有 Pipeline，并显示卡片"""
        self.pipeline_list.clear()
        for idx, pipe in enumerate(self.config.pipelines):
            card = PipelineCardWidget(pipe, idx, self.adb, self.plugin_mgr, self)
            # 连接信号
            card.sync_requested.connect(self.on_sync_requested)
            card.edit_requested.connect(self.on_edit_requested)
            card.delete_requested.connect(self.on_delete_requested)
            card.auto_sync_changed.connect(self.on_auto_sync_changed)  # 新增 自动同步配置
            item = QListWidgetItem()
            item.setSizeHint(card.sizeHint())
            self.pipeline_list.addItem(item)
            self.pipeline_list.setItemWidget(item, card)

    def on_auto_sync_changed(self, index, checked):
        """自动同步状态改变，更新配置"""
        if 0 <= index < len(self.config.pipelines):
            self.config.pipelines[index]['auto_sync'] = checked
            self.config.save()
            logger.info(f"Pipeline {index} 自动同步状态改为: {checked}")

    def refresh_pipeline_status(self):
        """更新每个 Pipeline 卡片的连接状态 （异步执行 ADB 查询）"""

        for i in range(self.pipeline_list.count()):
            item = self.pipeline_list.item(i)
            widget = self.pipeline_list.itemWidget(item)

            if not widget:
                continue

            if not self.adb.current_device: #设备没有连接 提前返回
                widget.update_status(None,False)
                continue
            
            # 这里做 设备序列号 判断，不涉及 adb_manager
            serial = widget.pipeline['device_serial']
            if serial: 
                if serial == self.adb.current_device:
                    self._start_path_check(widget)
                    continue
                else:
                    continue

            # widget.update_status() #2-23
            self._start_path_check(widget)

    def _start_path_check(self, widget):
        
        thread = QThread()
        worker = AdbWorker(self.adb,widget.pipeline['device'])
        worker.moveToThread(thread)

        # 连接信号
        thread.started.connect(worker.run)
        worker.finished.connect(lambda result: self._on_path_check_done(result, widget))
        worker.error.connect(lambda err: self._on_path_check_error(err, widget))
        
        # 安全的清理逻辑（保证线程退出后再销毁对象）
        def cleanup():
            # 清理实例属性（避免内存泄漏）
            if hasattr(self, 'current_check_thread'):
                self.current_check_thread = None
            if hasattr(self, 'current_check_worker'):
                self.current_check_worker = None


        # 线程清理
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)


        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        thread.finished.connect(cleanup)

        # 6. 存储为实例属性，避免被GC回收
        self.current_check_thread = thread
        self.current_check_worker = worker

        thread.start()

    def _on_path_check_done(self, result, widget):
        """路径检查结果处理"""
        if result[0] == 'path_exists':
            _, device_path, exists = result
            local_exists = os.path.isdir(widget.pipeline['local'])
            widget.update_status(local_exists, exists)

    def _on_path_check_error(self, error_msg, widget):
        """路径检查失败回调"""
        logger.error(f"检查路径失败: {error_msg}")
        # 更新状态为红色未知
        widget.update_status(False, False)

    def closeEvent(self, event):
        """程序关闭时清理线程"""
        self.device_timer.stop()
        if hasattr(self, 'sync_thread') and self.sync_thread.isRunning():
            self.sync_thread.quit()
            self.sync_thread.wait(2000)
        # 等待所有检查线程结束（简单起见，直接标记）
        event.accept()

    def add_pipeline(self):
        """打开新建 Pipeline 对话框"""
        dialog = PipelineDialog(self, pipeline=None, plugin_names=self.plugin_mgr.get_plugin_names())
        if dialog.exec():
            pipeline = dialog.get_pipeline()
            self.config.add_pipeline(pipeline)
            self.refresh_pipeline_list()
            logger.info(f"新建 Pipeline: {pipeline['name']}")

    def on_edit_requested(self, index):
        """编辑指定索引的 Pipeline"""
        pipeline = self.config.pipelines[index]
        dialog = PipelineDialog(self, pipeline, plugin_names=self.plugin_mgr.get_plugin_names())
        if dialog.exec():
            updated = dialog.get_pipeline()
            self.config.update_pipeline(index, updated)
            self.refresh_pipeline_list()
            logger.info(f"更新 Pipeline: {updated['name']}")

    def on_delete_requested(self, index):
        """删除指定索引的 Pipeline"""
        reply = QMessageBox.question(self, "确认删除", "确定要删除这个 Pipeline 吗？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            name = self.config.pipelines[index]['name']
            self.config.delete_pipeline(index)
            self.refresh_pipeline_list()
            logger.info(f"删除 Pipeline: {name}")

    def on_sync_requested(self, index):
        """执行同步"""
        # 获取卡片widget
        item = self.pipeline_list.item(index)
        widget = self.pipeline_list.itemWidget(item)
        if not widget:
            return
        # 禁用同步按钮
        widget.set_sync_button_enabled(False)


        pipeline = self.config.pipelines[index]
        self.sync_progress.setVisible(True)
        self.sync_progress.setValue(0)
        self.sync_progress.setMaximum(1)  # 临时，后续更新

        # 在后台线程中执行同步
        self.sync_thread = SyncThread(self.sync_engine, pipeline,index, self)
        self.sync_thread.stats_updated.connect(self.on_sync_progress)
        self.sync_thread.finished.connect(self.on_sync_finished)
        self.sync_thread.error.connect(self.on_sync_error)
        self.sync_thread.start()
        logger.info(f"开始同步: {pipeline['name']}")

    def on_sync_progress(self, msg, current, total):
        """同步进度更新"""
        # 简单在日志中显示
        if current % 10 == 0 or current == total:
            logger.info(f"进度: {current}/{total} - {msg}")

        if total > 0:
            self.sync_progress.setMaximum(total)
            self.sync_progress.setValue(current)

        # 可选：更新状态栏消息
        # self.status_bar.showMessage(msg)

    def on_sync_finished(self, index, stats):
        # 恢复按钮
        item = self.pipeline_list.item(index)
        widget = self.pipeline_list.itemWidget(item)
        if widget:
            widget.set_sync_button_enabled(True)

        self.sync_progress.setVisible(False)
        logger.info(f"同步完成: 上传 {stats['upload']}, 下载 {stats['download']}, 跳过 {stats['skip']}, 错误 {stats['error']}")
        self.log_text.addItem('')

    def on_sync_error(self, index, error_msg):
        item = self.pipeline_list.item(index)
        widget = self.pipeline_list.itemWidget(item)
        if widget:
            widget.set_sync_button_enabled(True)


        self.sync_progress.setVisible(False)
        logger.error(f"同步失败: {error_msg}")



class SyncThread(QThread):
    finished = pyqtSignal(int, dict)
    error = pyqtSignal(int, str)
    stats_updated = pyqtSignal(str, int, int)  # 当前操作描述, 当前索引, 总数

    def __init__(self, engine, pipeline, index, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.pipeline = pipeline
        self.index = index

    def run(self):
        try:
            stats = self.engine.sync(self.pipeline, progress_callback=self.stats_updated.emit)
            self.finished.emit(self.index, stats)
        except Exception as e:
            self.error.emit(self.index, str(e))