import datetime
import shlex
import subprocess
import sys
import threading
import time
from typing import List, Optional, Dict, Any, Tuple

# Windows 下隐藏子进程窗口(不然打包后，cmd窗口会闪现)
startupinfo = None
creationflags = 0
if sys.platform == 'win32':
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    creationflags = subprocess.CREATE_NO_WINDOW  # 0x08000000

STARTUPINFO_C = startupinfo
CREATIONFLAGS_C = creationflags

class AdbError(Exception):
    pass

class AdbManager:
    """ADB 命令封装，单例模式管理当前设备"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.current_device = None  # 设备序列号  每次连接的第一个设备

        self._lock = threading.Lock()

    def get_devices(self) -> List[str]:
        """执行 adb devices，返回在线设备列表"""
        try:
            result = subprocess.run(['adb', 'devices'], capture_output=True, text=True, timeout=5,
                                     startupinfo=STARTUPINFO_C, creationflags=CREATIONFLAGS_C)
            if result.returncode != 0:
                raise AdbError(f"adb devices failed: {result.stderr}")
            lines = result.stdout.strip().split('\n')[1:]
            devices = []
            for line in lines:
                if line.strip() and '\tdevice' in line:
                    serial = line.split('\t')[0]
                    devices.append(serial)
            return devices
        except subprocess.TimeoutExpired:
            raise AdbError("adb devices timeout")
        except FileNotFoundError:
            raise AdbError("adb not found in PATH")

    def select_first_device(self):
        """选择第一个在线设备作为当前设备"""
        devices = self.get_devices()
        if devices:
            self.current_device = devices[0]
        else:
            self.current_device = None
        return self.current_device

    def is_connected(self) -> bool:
        """检查当前设备是否在线"""
        if not self.current_device:
            return False
        try:
            result = subprocess.run(['adb', '-s', self.current_device, 'shell', 'echo', 'online'],
                                    capture_output=True, text=True, timeout=5,
                                     startupinfo=STARTUPINFO_C, creationflags=CREATIONFLAGS_C)
            return result.returncode == 0 and 'online' in result.stdout
        except:
            return False

    def _run_adb(self, args: List[str], timeout: int = 10) -> subprocess.CompletedProcess:
        """运行 adb 命令，自动添加 -s 序列号"""

        if not self.current_device:
            raise AdbError("No device selected")
        cmd = ['adb', '-s', self.current_device] + args
        # 调试时可打印命令
        # print(f"ADB: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                    check=False, encoding='utf-8', errors='ignore',
                                    startupinfo=STARTUPINFO_C, creationflags=CREATIONFLAGS_C)
            
            # print('reuslt_adb',result)
            return result
        except subprocess.TimeoutExpired:
            raise AdbError(f"adb command timeout: {' '.join(cmd)}")
        except FileNotFoundError:
            raise AdbError("adb not found in PATH")

    def file_exists(self, device_path: str) -> bool:
        """检查设备上路径是否存在"""
        # quoted = shlex.quote(device_path)
        result = self._run_adb(['shell', 'test', '-e', device_path, '&&', 'echo', 'exists'])
        return 'exists' in result.stdout

    def list_directory(self, device_path: str) -> List[Dict[str, Any]]:
        """列出设备目录内容，返回文件信息列表（非递归）"""
        result = self._run_adb(['shell', 'ls', '-la', device_path])
        if result.returncode != 0:
            return []
        
        # ...\n-rw-rw---- 1 u0_a199 media_rw  30761 2026-02-22 11:47 How I Use Claude Code.html\n
        lines = result.stdout.strip().split('\n') 
        files = []
        for line in lines:
            if not line.strip():
                continue
            parts = line.split(maxsplit=7)
            if len(parts) < 8:
                continue
            perm = parts[0]
            is_dir = perm.startswith('d')
            name = parts[-1]
            if name in ('.', '..'):
                continue
            
            # 解析日期部分 (假设格式为 YYYY-MM-DD HH:MM)
            date_str = ' '.join(parts[5:7])  # 例如 "2026-02-09 13:24"
            mtime_timestamp = None
            try:
                dt = datetime.datetime.strptime(date_str, '%Y-%m-%d %H:%M')
                mtime_timestamp = int(dt.timestamp())
            except:
                pass  # 解析失败则保留为 None
                
            
            files.append({
                'name': name,
                'is_dir': is_dir,
                'size': int(parts[4]) if parts[4].isdigit() else 0,
                'mtime_str': date_str,
                'mtime': mtime_timestamp  # 添加数值时间戳
            })
        return files

    def list_files_recursive(self, device_path: str) -> List[Dict[str, Any]]:
        """
        递归列出设备路径下所有文件，返回列表，每个元素包含：
        rel_path: 相对于 device_path 的路径（含文件名）
        size: 文件大小（字节）
        mtime: 修改时间戳（整数秒）
        优先使用 find + stat，若失败则回退到递归 ls（较慢）
        """
        # 尝试使用 find -printf (如果支持)
        # 常见格式: find %path% -type f -printf '%P %s %T@\n'
        # 但 Android 的 find 可能不支持 -printf，改用 -exec stat
        test_cmd = ['shell', 'find', device_path, '-type', 'f', '-printf', '%P\\t%s\\t%T@\\n']
        result = self._run_adb(test_cmd, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            # 解析
            files = []
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                parts = line.split('\t')
                if len(parts) >= 3:
                    rel_path = parts[0]
                    size = int(parts[1])
                    mtime = float(parts[2])
                    files.append({
                        'rel_path': rel_path,
                        'size': size,
                        'mtime': int(mtime)  # 转为整数秒
                    })
            return files

        # 备选方案：使用 find 结合 stat
        # find %path% -type f -exec stat -c '%n %s %Y' {} \;
        # 但需要解析输出，且文件名可能包含空格
        # 简化：只返回当前目录，暂不实现复杂递归，避免复杂
        # 这里简单返回空，后续可用其他方法
        # 实际开发中可考虑递归调用 list_directory，但性能较差
        # 为简化，我们仅支持单层目录，或者留待以后实现
        # 返回空列表，表示不支持递归
        return []

    def pull(self, remote: str, local: str) -> bool:
        """从设备拉取文件到本地"""
        result = self._run_adb(['pull', remote, local], timeout=60)
        return result.returncode == 0

    def push(self, local: str, remote: str) -> bool:
        """推送本地文件到设备"""
        result = self._run_adb(['push', local, remote], timeout=60)
        return result.returncode == 0

    def delete(self, device_path: str, recursive: bool = False) -> bool:
        """删除设备上的文件或目录"""
        if recursive:
            result = self._run_adb(['shell', 'rm', '-rf', device_path])
        else:
            result = self._run_adb(['shell', 'rm', device_path])
        return result.returncode == 0

    def mkdir(self, device_path: str) -> bool:
        """在设备上创建目录（包括父目录）"""
        result = self._run_adb(['shell', 'mkdir', '-p', device_path])
        return result.returncode == 0

    def get_file_info(self, device_path: str) -> Optional[Dict[str, Any]]:
        """获取文件详细信息，使用 stat 命令"""
        result = self._run_adb(['shell', 'stat', '-c', shlex.quote('%F %s %Y'), device_path])
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            if len(parts) >= 3:
                file_type = parts[0]
                size = int(parts[1])
                mtime = int(parts[2])
                return {
                    'is_dir': 'directory' in file_type,
                    'size': size,
                    'mtime': mtime
                }
        return None