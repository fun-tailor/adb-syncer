from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QPainter, QColor, QPixmap
from PyQt6.QtCore import QRectF, QTimer, pyqtSignal, Qt, QSize
from PyQt6.QtSvg import QSvgRenderer


import importlib.resources
from PyQt6.QtCore import QByteArray

# 从 myapp.resources 包中读取 arrows.svg 的二进制数据
DATA_ICON = importlib.resources.files('res.icons').joinpath('arrows-down-up.svg').read_bytes()

class SystemTray(QSystemTrayIcon):
    # 信号：通知主窗口暂停状态改变（可选）
    auto_sync_paused = pyqtSignal(bool)


    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent  # MainWindow 实例

        # 状态变量
        self._connected = False
        self._syncing = False
        self._sync_paused = False          # 暂停自动同步标志
        # self._pause_until = 0               # 暂停结束时间戳
        self._rotation_angle = 0

        # 加载 SVG 渲染器
        # self.renderer = QSvgRenderer(":/icons/arrows.svg")  # 使用资源文件路径
        self.renderer = QSvgRenderer(QByteArray(DATA_ICON))  # 使用资源文件路径

        # 设置默认图标（未连接）
        self._update_icon()

        # 动画定时器（同步时启动）
        self.anim_timer = QTimer()
        self.anim_timer.timeout.connect(self._rotate_icon)
        self.anim_timer.setInterval(200)  # 200ms 旋转一次

        # 暂停定时器（30分钟后自动恢复）
        self.pause_timer = QTimer()
        self.pause_timer.setSingleShot(True)
        self.pause_timer.timeout.connect(self._resume_auto_sync)

        # 创建右键菜单
        self.menu = QMenu()
        self.show_action = self.menu.addAction("显示窗口")
        self.show_action.triggered.connect(self.show_window)
        self.menu.addSeparator()

        # 暂停/恢复菜单项
        self.pause_action = self.menu.addAction("暂停自动同步 30 分钟")
        self.pause_action.triggered.connect(self.pause_auto_sync)
        self.resume_action = self.menu.addAction("取消暂停")
        self.resume_action.triggered.connect(self.resume_auto_sync)
        self.resume_action.setVisible(False)  # 初始隐藏

        self.menu.addSeparator()

        # 设置：显示通知复选框
        self.settings_action = self.menu.addAction("同步完成时 显示通知")
        self.settings_action.setCheckable(True)
        self.settings_action.setChecked(self.parent.config.get('show_sync_notification', False))
        self.settings_action.triggered.connect(self.toggle_notification)

        self.quit_action = self.menu.addAction("退出")
        self.quit_action.triggered.connect(self.quit_app)

        self.setContextMenu(self.menu)

        # 连接托盘点击事件
        self.activated.connect(self.on_activated)

    def on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_window()

    def show_window(self):
        self.parent.show()
        self.parent.raise_() #前台
        self.parent.activateWindow()

    def quit_app(self):
        self.parent._force_exit = True
        self.parent.show()  #不显示，则被忽略
        self.parent.close()  # 触发 closeEvent，让主窗口清理资源

    # ---------- 状态更新 ----------
    def update_connection_state(self, connected: bool):
        self._connected = connected
        self._update_icon()

    def update_sync_state(self, syncing: bool):
        if self._syncing == syncing:
            return
        self._syncing = syncing
        if syncing:
            self._rotation_angle = 0
            self.anim_timer.start()
        else:
            self.anim_timer.stop()
        self._update_icon()

    def _rotate_icon(self):
        # 递增旋转角度
        self._rotation_angle = (self._rotation_angle + 30) % 360
        self._update_icon()

    # ---------- 图标绘制 ----------
    def _update_icon(self):
        size = 32  # 托盘图标常用尺寸
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制箭头（支持旋转）
        painter.save()
        if self._syncing:
            # 旋转中心为图片中心
            painter.translate(size / 2, size / 2)
            painter.rotate(self._rotation_angle)
            painter.translate(-size / 2, -size / 2)

        # 使用渲染器绘制 SVG（自动缩放以适应矩形）
        self.renderer.render(painter,  QRectF(painter.viewport()))  # 或指定 QRect(0,0,size,size)
        painter.restore()

        # 绘制绿点（如果已连接）
        if self._connected:
            painter.setBrush(QColor(0, 255, 0))  # 纯绿
            painter.setPen(Qt.PenStyle.NoPen)
            dot_size = 8
            painter.drawEllipse(size - dot_size, size - dot_size, dot_size, dot_size)

        painter.end()

        self.setIcon(QIcon(pixmap))

        self._update_tooltip()

    def _update_tooltip(self):
        if self._connected:
            device = self.parent.adb.current_device or "未知"
            tip = f"ADB 同步器 - 已连接: {device}"
        else:
            tip = "ADB 同步器 - 未连接"
        if self._syncing:
            tip += "\n同步中..."
        self.setToolTip(tip)

    # ---------- 暂停自动同步 ----------
    def pause_auto_sync(self):
        self._sync_paused = True
        self.pause_timer.start(30 * 60 * 1000)  # 30 分钟
        # 更新菜单项显示
        self.pause_action.setVisible(False)
        self.resume_action.setVisible(True)
        self.auto_sync_paused.emit(True)  # 通知主窗口

    def resume_auto_sync(self):
        self.pause_timer.stop()
        self._resume_auto_sync()

    def _resume_auto_sync(self):
        self.pause_timer.stop() #
        self._sync_paused = False
        self.pause_action.setVisible(True)
        self.resume_action.setVisible(False)
        self.auto_sync_paused.emit(False)  # 通知主窗口

    def is_auto_sync_paused(self) -> bool:
        return self._sync_paused
    
    def show_message(self, title: str, message: str, icon=None, timeout: int = 3000):
        super().showMessage(title, message, icon or QSystemTrayIcon.MessageIcon.Information, timeout)

    def toggle_notification(self, checked):
        self.parent.config.set('show_sync_notification', checked)