from collections import deque
import os
import logging
import time
from PyQt6.QtWidgets import (QMainWindow, QPlainTextEdit, QProgressBar, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QListWidget, QListWidgetItem,
                             QMessageBox, QStatusBar, QApplication)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QPalette, QColor

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
        
        # sync 任务 序列执行
        self.sync_queue = deque()          # 待执行的同步任务队列
        self._sync_running = False         # 当前是否有同步任务正在运行

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

        # 记录上一次检测到的设备序列号
        self.last_device_serial = None  

        # 添加成员变量记录自动同步时间
        self.last_auto_sync_time = {}
        self._check_workers = []  # 用于路径检查线程

        # 启动定时器检测设备
        self.device_timer = QTimer()
        self.device_timer.timeout.connect(self.check_device)
        self.device_timer.start(5000)  # 5秒
        self.check_device()  # 立即检测一次

        # 加载 Pipeline 并刷新状态
        self.refresh_pipeline_list()

        # 存储所有正在运行的路径检查线程
        self.path_check_threads = {}

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
        # self.log_text = QListWidget()
        # self.log_text.setMaximumHeight(150)
        # layout.addWidget(self.log_text)

        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(500)  # 最多显示500行
        self.log_text.setMaximumHeight(150)

        # 设置选中文本的背景色（浅蓝色）和文字颜色（黑色）
        palette = self.log_text.palette()
        highlight_color = QColor(200, 220, 255)  # 浅蓝色
        palette.setColor(QPalette.ColorRole.Highlight, highlight_color)
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
        self.log_text.setPalette(palette)

        layout.addWidget(self.log_text)

    def append_log(self, msg):
        """将日志消息添加到列表控件"""
        # self.log_text.addItem(msg)
        # self.log_text.scrollToBottom()
        self.log_text.appendPlainText(msg)
        # 滚动到底部
        cursor = self.log_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)
            

    def check_device(self):
        try:
            devices = self.adb.get_devices()
            if devices:
                new_serial = devices[0]   # 选择第一个在线设备
                # 检测设备是否从无到有，或设备序列号发生变化
                if self.last_device_serial is None or self.last_device_serial != new_serial:
                    self.adb.current_device = new_serial
                    self.device_label.setText(f"设备: 已连接 ({self.adb.current_device})")
                    self.device_label.setStyleSheet("color: green;")
                    self.refresh_pipeline_status()   # 设备变化，刷新卡片状态
                    self.trigger_auto_sync()         # 触发自动同步
                self.last_device_serial = new_serial
            else:
                # 之前有设备，现在无设备（断开连接）
                if self.last_device_serial is not None:
                    self.adb.current_device = None
                    self.device_label.setText("设备: 未连接")
                    self.device_label.setStyleSheet("color: gray;")
                    self.refresh_pipeline_status()   # 设备断开，刷新卡片状态
                self.last_device_serial = None
        except AdbError as e:
            self.adb.current_device = None
            self.device_label.setText(f"设备: 错误 - {str(e)}")
            self.device_label.setStyleSheet("color: red;")
            # 如果之前有设备，现在出错，也刷新状态
            if self.last_device_serial is not None:
                self.refresh_pipeline_status()
            self.last_device_serial = None
            
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

                self.last_auto_sync_time[i] = now
                self.sync_queue.append(i)
                logger.info(f"自动同步任务已加入队列: {self.config.pipelines[i]['name']}")

        # 如果当前没有正在运行的同步任务，则启动队列
        if not self._sync_running and self.sync_queue:
            self._start_next_sync()
            

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
                    self._start_path_check(widget, index=i)
                    continue
                else:
                    continue

            # widget.update_status() #2-23
            self._start_path_check(widget,index=i)

    def refresh_pipeline_status_by_index(self, index):
        """刷新指定索引的 pipeline 状态"""
        if index < 0 or index >= self.pipeline_list.count():
            logger.warning(f"刷新状态失败：索引 {index} 超出范围")
            return

        item = self.pipeline_list.item(index)
        if not item:
            return

        widget = self.pipeline_list.itemWidget(item)
        if not widget:
            return

        # 如果已有该索引的检查线程，先移除字典中的记录（让旧线程自行清理）
        if index in self.path_check_threads:
            del self.path_check_threads[index]
            logger.debug(f"移除索引 {index} 的旧线程引用")

        # 启动新的路径检查线程
        self._start_path_check(widget, index)

    def _start_path_check(self, widget,index=None):
        """
        启动路径检查线程，确保同一索引的检查不会重复启动。
        :param widget: PipelineCardWidget 对象
        :param index: pipeline 在列表中的索引
        """
        # 如果索引存在且已有线程在运行，则直接跳过
        if index is not None and index in self.path_check_threads:
            thread = self.path_check_threads[index]
            try:
                if thread.isRunning():
                    logger.debug(f"索引 {index} 的路径检查线程已在运行，跳过")
                    return
            except RuntimeError:
                # 线程对象已被销毁，从字典中移除
                del self.path_check_threads[index]
                logger.debug(f"索引 {index} 的线程已销毁，移除并新建")

        
        thread = QThread()
        worker = AdbWorker(self.adb,widget.pipeline['device'])
        worker.moveToThread(thread)

        # 让线程持有 worker 的引用（防止 worker 被回收）
        thread.worker = worker
        thread.index = index   # 保存索引供回调使用

        # 连接信号
        thread.started.connect(worker.run)
        worker.finished.connect(lambda result: self._on_path_check_done(result, index))
        worker.error.connect(lambda err: self._on_path_check_error(err, index))
        
        # 安全的清理逻辑（保证线程退出后再销毁对象）
        def cleanup():
            if thread in self.path_check_threads: #隐式闭包
                self.path_check_threads.remove(thread)


        # 线程清理
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)

        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        thread.finished.connect(cleanup)# 线程结束时从列表中移除

        # 将线程加入字典
        if index is not None:
            self.path_check_threads[index] = thread

        thread.start()

    def _on_path_check_done(self, result, index):
        """路径检查结果处理"""
        item = self.pipeline_list.item(index)
        if not item:
            return   # 索引无效，widget 已不存在
        widget = self.pipeline_list.itemWidget(item)
        if not widget:
            return
        
        # local_exists = os.path.isdir(widget.pipeline['local'])
        # device_exists = result[1] if len(result) > 1 else False   # 根据实际 result 结构调整
        # widget.update_status(local_exists, device_exists)
        
        if result[0] == 'path_exists':
            _, device_path, exists = result
            local_exists = os.path.isdir(widget.pipeline['local'])
            widget.update_status(local_exists, exists)

    def _on_path_check_error(self, error_msg, index):
        """路径检查失败回调"""
        item = self.pipeline_list.item(index)
        if not item:
            return
        widget = self.pipeline_list.itemWidget(item)
        if widget:
            widget.update_status(False, False)
        
        if self.last_device_serial:
            logger.error(f"检查路径失败 (索引 {index}): {error_msg}")

    def closeEvent(self, event):
        """程序关闭时清理线程"""
        self.device_timer.stop()
        # 如果正在执行同步，等待它结束（或强制终止）
        if self._sync_running and hasattr(self, 'sync_thread') and self.sync_thread.isRunning():
            self.sync_thread.quit()
            if not self.sync_thread.wait(3000):
                self.sync_thread.terminate()

        # 等待所有路径检查线程
        for thread in list(self.path_check_threads.values()):
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait(1000)
            except RuntimeError:
                # 对象已销毁，忽略
                pass
        event.accept()

    def add_pipeline(self):
        """打开新建 Pipeline 对话框"""
        dialog = PipelineDialog(self, pipeline=None, plugin_names=self.plugin_mgr.get_plugin_names())
        if dialog.exec():
            pipeline = dialog.get_pipeline()
            self.config.add_pipeline(pipeline)
            self.refresh_pipeline_list()
            logger.info(f"新建 Pipeline: {pipeline['name']}")

            new_index = len(self.config.pipelines) - 1   # 新添加的索引
            self.refresh_pipeline_status_by_index(new_index) 


    def on_edit_requested(self, index):
        """编辑指定索引的 Pipeline"""
        pipeline = self.config.pipelines[index]
        dialog = PipelineDialog(self, pipeline, plugin_names=self.plugin_mgr.get_plugin_names())
        if dialog.exec():
            updated = dialog.get_pipeline()
            self.config.update_pipeline(index, updated)
            self.refresh_pipeline_list()
            logger.info(f"更新 Pipeline: {updated['name']}")

            # self.refresh_pipeline_status_by_index(index)  # 会自动全局刷新（暂取消）

    def on_delete_requested(self, index):
        """删除指定索引的 Pipeline"""
        reply = QMessageBox.question(self, "确认删除", "确定要删除这个 Pipeline 吗？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            name = self.config.pipelines[index]['name']

            # 从队列中移除该索引的所有待执行任务
            # 注意：deque 不支持在遍历时删除，所以创建新队列
            self.sync_queue = deque([i for i in self.sync_queue if i != index])
            
            # 如果该任务正在执行，无法中断，但完成后会因 widget 不存在而跳过 UI 更新
            self.config.delete_pipeline(index)
            self.refresh_pipeline_list()
            logger.info(f"删除 Pipeline: {name}")
            self.refresh_pipeline_status()

    def on_sync_requested(self, index):
        """请求同步：将任务加入队列，并尝试启动队列"""

        if index in self.sync_queue: #同步按钮，激活已经存在队列中的任务
            QMessageBox.information(self, "提示", "该任务已在队列中等待")
            return
        
        if self._sync_running and hasattr(self, 'sync_thread') and self.sync_thread.index == index:
            QMessageBox.information(self, "提示", "该任务正在执行中")
            return

        # 检查 pipeline 是否存在
        if index < 0 or index >= len(self.config.pipelines):
            logger.error(f"无效的 pipeline 索引: {index}")
            return

        # 将任务加入队列（存储索引即可，后续通过索引获取最新 pipeline 数据）
        self.sync_queue.append(index)

        # 立即尝试启动队列
        self._start_next_sync()

    def _start_next_sync(self):
        """启动队列中的下一个同步任务（如果当前没有任务在运行且队列非空）"""
        if self._sync_running:
            return

        if not self.sync_queue:
            return

        # 取出下一个任务索引
        index = self.sync_queue.popleft()

        # 检查 pipeline 和 widget 是否仍然有效
        if index < 0 or index >= len(self.config.pipelines):
            logger.warning(f"队列中的 pipeline 索引 {index} 已不存在，跳过")
            self._start_next_sync()   # 递归检查下一个
            return

        item = self.pipeline_list.item(index)
        if not item:
            logger.warning(f"队列中的 pipeline 索引 {index} 的列表项已不存在，跳过")
            self._start_next_sync()
            return

        widget = self.pipeline_list.itemWidget(item)
        if not widget:
            logger.warning(f"队列中的 pipeline 索引 {index} 的卡片已不存在，跳过")
            self._start_next_sync()
            return

        # 禁用该卡片的同步按钮，表示正在执行或排队（这里在启动时禁用）
        widget.set_sync_button_enabled(False)

        # 获取最新的 pipeline 数据
        pipeline = self.config.pipelines[index]

        # 显示进度条
        self.sync_progress.setVisible(True)
        self.sync_progress.setValue(0)
        self.sync_progress.setMaximum(1)

        # 创建并启动同步线程
        self._sync_running = True
        self.sync_thread = SyncThread(self.sync_engine, pipeline, index, self)
        self.sync_thread.stats_updated.connect(self.on_sync_progress)
        self.sync_thread.finished.connect(self.on_sync_finished)
        self.sync_thread.error.connect(self.on_sync_error)

        # 线程结束后自动销毁
        self.sync_thread.finished.connect(self.sync_thread.deleteLater)
        self.sync_thread.error.connect(self.sync_thread.deleteLater)

        self.sync_thread.start()
        logger.info(f"开始同步 '{pipeline['name']}'，队列中还有 {len(self.sync_queue)} 个任务等待")

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
        """同步成功完成"""
        self._sync_running = False
        self.sync_progress.setVisible(False)

        # 恢复按钮
        item = self.pipeline_list.item(index)
        widget = self.pipeline_list.itemWidget(item)
        if item:
            widget = self.pipeline_list.itemWidget(item)
            if widget:
                widget.set_sync_button_enabled(True)

        self.sync_progress.setVisible(False) 
        logger.info(f"同步完成: 上传 {stats['upload']}, 下载 {stats['download']}, 跳过 {stats['skip']}, 错误 {stats['error']}")
        self.append_log('')

        # 启动队列中的下一个任务
        self._start_next_sync()

    def on_sync_error(self, index, error_msg):
        """同步失败"""
        self._sync_running = False
        self.sync_progress.setVisible(False)

        item = self.pipeline_list.item(index)
        if item:
            widget = self.pipeline_list.itemWidget(item)
            if widget:
                widget.set_sync_button_enabled(True)


        self.sync_progress.setVisible(False)
        logger.error(f"同步失败: {error_msg}")
        # 启动队列中的下一个任务
        self._start_next_sync()

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