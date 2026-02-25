import os
import time
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

from core.adb_manager import AdbManager
from core.plugin_manager import PluginManager

logger = logging.getLogger(__name__)

class SyncEngine:
    def __init__(self, adb: AdbManager, plugin_mgr: PluginManager):
        self.adb = adb
        self.plugin_mgr = plugin_mgr
        self.stop_requested = False

    def sync(self, pipeline: Dict[str, Any],
             progress_callback: Optional[Callable[[str, int, int], None]] = None,
             conflict_callback: Optional[Callable[[str, dict, dict], str]] = None) -> Dict[str, int]:
        """
        执行同步任务
        :param pipeline: Pipeline 配置
        :param progress_callback: 进度回调，参数 (当前操作描述, 当前文件索引, 总文件数)
        :param conflict_callback: 冲突回调，参数 (相对路径, 本地文件信息, 设备文件信息)，返回决策 'local','device','skip'
        :return: 统计信息 {'upload': x, 'download': y, 'skip': z, 'error': w}
        """
        stats = {'upload': 0, 'download': 0, 'skip': 0, 'error': 0}

        # 获取插件实例（如果有）
        plugin = None
        if pipeline.get('plugin'):
            plugin = self.plugin_mgr.get_plugin(pipeline['plugin'], pipeline.get('plugin_config', {}))
            if plugin:
                logger.info(f"使用插件: {pipeline['plugin']}")

        # 上下文对象，传递给插件
        context = {
            'adb': self.adb,
            'logger': logger,
            'pipeline': pipeline
        }

        try:
            # 1. 路径解析（插件可修改）
            local_path, device_path = pipeline['local'], pipeline['device']
            if plugin and hasattr(plugin, 'on_path_resolve'):
                local_path, device_path = plugin.on_path_resolve(pipeline, context)
                logger.info(f"插件解析后路径: 本地={local_path}, 设备={device_path}")

            # 2. 验证路径存在性
            if not os.path.isdir(local_path):
                raise Exception(f"本地路径不存在: {local_path}")
            if not self.adb.file_exists(device_path):
                # 尝试创建设备目录
                if not self.adb.mkdir(device_path):
                    raise Exception(f"无法创建设备路径: {device_path}")

            # 3. 获取同步参数
            direction = pipeline.get('direction', 'local_to_device')
            include_ext = pipeline.get('include_extensions', [])
            exclude_ext = pipeline.get('exclude_extensions', [])
            sync_days = pipeline.get('sync_days', 1)  # 0 表示全部

            # 4. 计算时间阈值
            if sync_days > 0:
                threshold = time.time() - sync_days * 24 * 3600
            else:
                threshold = 0

            # 5. 收集本地文件
            local_files = self._collect_local_files(local_path, include_ext, exclude_ext, threshold, plugin, context)
            logger.info(f"本地待处理文件数: {len(local_files)}")

            # 6. 收集设备文件
            device_files = self._collect_device_files(device_path, include_ext, exclude_ext, threshold, plugin, context)
            logger.info(f"设备待处理文件数: {len(device_files)}")

            # 7. 比较生成操作列表
            operations = self._compare_files(local_files, device_files, direction, plugin, context, conflict_callback)
            logger.info(f"待执行操作数: {len(operations)}")

            # 在生成 operations 之后，执行之前
            if operations:
                # 收集需要创建的远程目录（仅上传操作）
                remote_dirs = set()
                for op, file_info, _ in operations:
                    if op == 'upload':
                        remote_dir = os.path.dirname(f"{device_path}/{file_info['rel_path']}")
                        remote_dirs.add(remote_dir)
                # 批量检查/创建目录
                for remote_dir in remote_dirs:
                    if not self.adb.file_exists(remote_dir):
                        self.adb.mkdir(remote_dir)
                        logger.info(f"创建远程目录: {remote_dir}")

            # 8. 执行操作
            total = len(operations)
            for idx, (op, file_info, target_path) in enumerate(operations):
                if self.stop_requested:
                    logger.warning("同步被用户中止")
                    break
                if progress_callback:
                    progress_callback(f"{op} {file_info['rel_path']}", idx, total)

                try:
                    if op == 'upload':
                        remote_full = f"{device_path}/{file_info['rel_path']}"
                        # 确保远程目录存在
                        # remote_dir = os.path.dirname(remote_full)
                        # self.adb.mkdir(remote_dir)
                        if self.adb.push(file_info['full_path'], remote_full):
                            stats['upload'] += 1
                        else:
                            stats['error'] += 1
                            logger.error(f"上传失败: {file_info['rel_path']}")
                    elif op == 'download':
                        local_full = os.path.join(local_path, file_info['rel_path'])
                        os.makedirs(os.path.dirname(local_full), exist_ok=True)
                        if self.adb.pull(target_path, local_full):
                            stats['download'] += 1
                        else:
                            stats['error'] += 1
                            logger.error(f"下载失败: {file_info['rel_path']}")
                except Exception as e:
                    stats['error'] += 1
                    logger.error(f"操作异常 {file_info['rel_path']}: {e}")

            # 9. 插件结束钩子
            if plugin and hasattr(plugin, 'on_sync_end'):
                plugin.on_sync_end(pipeline, context, stats)

        except Exception as e:
            logger.error(f"同步过程出错: {e}")
            if plugin and hasattr(plugin, 'on_sync_error'):
                plugin.on_sync_error(pipeline, context, str(e))
            raise

        return stats

    def _collect_local_files(self, local_path, include_ext, exclude_ext, threshold, plugin, context):
        """收集本地文件，应用过滤"""
        files = []
        for root, dirs, filenames in os.walk(local_path):
            for file in filenames:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, local_path).replace('\\', '/')
                stat = os.stat(full_path)
                mtime = stat.st_mtime
                size = stat.st_size

                # 时间过滤
                if threshold > 0 and mtime < threshold:
                    continue

                # 扩展名过滤
                ext = os.path.splitext(file)[1].lower()
                if include_ext and ext not in include_ext:
                    continue
                if exclude_ext and ext in exclude_ext:
                    continue

                # 插件过滤
                if plugin and hasattr(plugin, 'on_file_filter'):
                    if not plugin.on_file_filter({
                        'rel_path': rel_path,
                        'size': size,
                        'mtime': mtime,
                        'is_dir': False,
                        'full_path': full_path
                    }, context):
                        continue

                files.append({
                    'rel_path': rel_path,
                    'full_path': full_path,
                    'mtime': mtime,
                    'size': size
                })
        return files

    def _collect_device_files(self, device_path, include_ext, exclude_ext, threshold, plugin, context):
        """收集设备文件，目前简化，只使用非递归列表"""
        # 此处应使用递归获取，但 adb_manager 中 list_files_recursive 尚未完善
        # 临时使用非递归，仅支持单层目录
        files = []
        entries = self.adb.list_directory(device_path)
        for entry in entries:
            if entry['is_dir']:
                # 忽略子目录（简化）
                continue
            name = entry['name']
            rel_path = name

            mtime = entry.get('mtime')
            if mtime is None:
               continue  # 无法获取时间则跳过
            size = entry['size']

            if threshold > 0 and mtime < threshold:
                continue
            
            ext = os.path.splitext(name)[1].lower()
            if include_ext and ext not in include_ext:
                continue
            if exclude_ext and ext in exclude_ext:
                continue

            if plugin and hasattr(plugin, 'on_file_filter'):
                if not plugin.on_file_filter({
                    'rel_path': rel_path,
                    'size': size,
                    'mtime': mtime,
                    'is_dir': False
                }, context):
                    continue

            files.append({
                'rel_path': rel_path,
                'mtime': mtime,
                'size': size,
                'full_device_path': f"{device_path}/{rel_path}"
            })
        
        return files

    def _is_same_file(self, local_info, device_info):
        """基于大小和分钟级修改时间判断文件是否相同"""
        if local_info['size'] != device_info['size']:
            return False
        # 将时间戳对齐到分钟
        local_min = int(local_info['mtime'] // 60)
        device_min = int(device_info['mtime'] // 60)
        return local_min == device_min
    
    def _compare_files(self, local_files, device_files, direction, plugin, context, conflict_callback):
        """比较两端文件，生成操作列表"""
        operations = []  # (op, file_info, target_path)  target_path 用于下载时指定设备源路径
        local_dict = {f['rel_path']: f for f in local_files}
        device_dict = {f['rel_path']: f for f in device_files}

        if direction == 'local_to_device':
            # 只考虑本地到设备
            for rel_path, lf in local_dict.items():
                df = device_dict.get(rel_path)
                if df is None:
                    operations.append(('upload', lf, None))
                else:
                    if self._is_same_file(lf, df):
                        continue   # 文件相同，跳过
                    if lf['mtime'] > df['mtime']:
                        operations.append(('upload', lf, None))
                    # 否则忽略（设备更新或相同）
        elif direction == 'device_to_local':
            # 只考虑设备到本地
            for rel_path, df in device_dict.items():
                lf = local_dict.get(rel_path)
                if lf is None:
                    operations.append(('download', df, df['full_device_path']))
                else:
                    if self._is_same_file(lf, df):
                        continue   # 文件相同，跳过
                    if df['mtime'] > lf['mtime']:
                        operations.append(('download', df, df['full_device_path']))
        else:  # bidirectional
            # 双向：需要冲突处理
            all_paths = set(local_dict.keys()) | set(device_dict.keys())
            for rel_path in all_paths:
                lf = local_dict.get(rel_path)
                df = device_dict.get(rel_path)
                if lf and df:
                    if self._is_same_file(lf, df):
                        continue   # 文件相同，跳过
                    # 两端都有
                    if lf['mtime'] > df['mtime']:
                        operations.append(('upload', lf, None))
                    elif lf['mtime'] < df['mtime']:
                        # 冲突，需要决策
                        decision = 'skip'
                        if plugin and hasattr(plugin, 'on_conflict'):
                            decision = plugin.on_conflict(lf, df, context)
                        elif conflict_callback:
                            decision = conflict_callback(rel_path, lf, df)
                        if decision == 'local':
                            operations.append(('upload', lf, None))
                        elif decision == 'device':
                            operations.append(('download', df, df['full_device_path']))
                        else:
                            # skip
                            pass
                    # 相等则跳过
                elif lf:
                    operations.append(('upload', lf, None))
                elif df:
                    operations.append(('download', df, df['full_device_path']))

        return operations