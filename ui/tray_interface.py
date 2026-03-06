# from abc import ABC, abstractmethod
from typing import Protocol

class TrayInterface(Protocol):
    """系统托盘接口协议（仅用于类型提示）"""
    def show(self) -> None:
        ...

    def update_connection_state(self, connected: bool) -> None:
        ...

    def update_sync_state(self, syncing: bool) -> None:
        ...

    def is_auto_sync_paused(self) -> bool:
        ...

    def show_message(self, title: str, message: str, icon=None, timeout: int = 3000) -> None:
        ...