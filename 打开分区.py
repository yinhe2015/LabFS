import subprocess
import stat
import sys
import os
import re

IS_MAC = sys.platform.lower() == 'darwin'

class 打开分区:
    def _是设备路径(self) -> bool:
        try:
            模式 = os.stat(self.dev_path).st_mode
        except OSError:
            return self.dev_path.startswith('/dev/')
        return stat.S_ISBLK(模式) or (sys.platform == 'darwin' and stat.S_ISCHR(模式))

    def _prevent_write_to_system_disk(self) -> None:
        """禁止打开根文件系统所在的物理磁盘。"""
        if not self._是设备路径():
            return

        设备路径 = self.dev_path.lower()
        if IS_MAC:
            try:
                结果 = self._运行命令(['diskutil', 'info', '/'])
            except OSError as 异常:
                raise OSError('无法确认 macOS 系统盘，已拒绝打开原始设备') from 异常
            if 结果.returncode != 0:
                raise OSError('无法确认 macOS 系统盘，已拒绝打开原始设备')

            系统磁盘标识 = re.findall(
                r'(?:Part of Whole|APFS Physical Store):\s*(disk\d+)',
                结果.stdout
            )
            if not 系统磁盘标识:
                raise OSError('无法解析 macOS 系统盘，已拒绝打开原始设备')
            目标名称 = os.path.basename(设备路径)
            if 目标名称.startswith('r'):
                目标名称 = 目标名称[1:]
            if any(目标名称.startswith(标识) for 标识 in 系统磁盘标识):
                raise PermissionError('禁止操作 macOS 系统根磁盘')
        else:
            try:
                根设备结果 = self._运行命令(['findmnt', '-n', '-o', 'SOURCE', '/'])
                if 根设备结果.returncode != 0:
                    raise OSError('无法检测 Linux 系统根设备')
                根设备 = 根设备结果.stdout.strip()
                if not 根设备.startswith('/dev/'):
                    return

                def 设备链(路径: str) -> set[str]:
                    结果 = self._运行命令(['lsblk', '-nrpo', 'PATH', '-s', 路径])
                    if 结果.returncode != 0 or not 结果.stdout.strip():
                        raise OSError(f'无法检测设备链: {路径}')
                    链 = {
                        os.path.realpath(行.strip())
                        for 行 in 结果.stdout.splitlines()
                        if 行.strip()
                    }
                    return 链

                if 设备链(根设备) & 设备链(self.dev_path):
                    raise PermissionError('禁止操作 Linux 系统根磁盘')
            except OSError as 异常:
                if 设备路径.startswith(('/dev/sda', '/dev/vda')):
                    raise PermissionError('禁止操作 Linux 系统根磁盘') from 异常
                raise OSError('Linux 系统盘检测失败，已拒绝打开原始设备') from 异常

    def _unmount_if_mounted(self) -> None:
        """仅在设备已挂载时卸载，卸载失败则禁止继续写入。"""
        if not self._是设备路径():
            return

        if IS_MAC:
            目标名称 = os.path.basename(self.dev_path)
            if 目标名称.startswith('r'):
                目标名称 = 目标名称[1:]

            if re.fullmatch(r'disk\d+', 目标名称):
                subprocess.run(['diskutil', 'unmountDisk', self.dev_path])
        else:
            subprocess.run(['umount', self.dev_path])

    def _get_sector_size(self) -> int:
        """探测逻辑扇区大小，普通镜像文件和探测失败时使用 512。"""
        if not self._是设备路径():
            return 512

        if IS_MAC:
            结果 = subprocess.run(['diskutil', 'info', self.dev_path])
            匹配 = re.search(r'(?:Device|Logical) Block Size:\s*(\d+)', 结果.stdout)
            return int(匹配.group(1)) if 匹配 else 512
        else:
            try:
                结果 = subprocess.run(['lsblk', '-ndo', 'LOG-SEC', self.dev_path])
                if 结果.returncode == 0 and 结果.stdout.strip().isdigit():
                    return int(结果.stdout.strip())
            except OSError:
                pass
            return 512

    def __init__(
        self,
        dev_path: str,
        enable_cache: bool = True,
        cache_max_sectors: int = 256,
        sector_size: int | None = None
    ) -> None:
        self.dev_path = dev_path
        if cache_max_sectors <= 0:
            raise ValueError('cache_max_sectors 必须大于 0')
        if sector_size is not None and sector_size <= 0:
            raise ValueError('sector_size 必须大于 0')

        self._prevent_write_to_system_disk()
        self._unmount_if_mounted()

        self.sector_size = sector_size or self._get_sector_size()
        self.enable_cache = enable_cache
        self.cache_max = cache_max_sectors
        self._cache: dict[int, tuple[bytes, bool]] = {}
        self._access_list: list[int] = []
        self._pos = 0
        self._handle = None

        try:
            self._handle = open(self.dev_path, 'rb+', buffering=0)
            self.大小 = self._get_device_size()
        except Exception:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
            raise

    def _get_device_size(self) -> int:
        状态 = os.fstat(self._handle.fileno())
        if stat.S_ISREG(状态.st_mode):
            return 状态.st_size

        if IS_MAC:
            结果 = self._运行命令(['diskutil', 'info', self.dev_path])
            匹配 = re.search(r'Disk Size:.*\(([\d,]+) Bytes\)', 结果.stdout)
            if 匹配:
                return int(匹配.group(1).replace(',', ''))
        else:
            try:
                结果 = self._运行命令(['blockdev', '--getsize64', self.dev_path])
                if 结果.returncode == 0 and 结果.stdout.strip().isdigit():
                    return int(结果.stdout.strip())
            except OSError:
                pass

        try:
            原位置 = os.lseek(self._handle.fileno(), 0, os.SEEK_CUR)
            大小 = os.lseek(self._handle.fileno(), 0, os.SEEK_END)
            os.lseek(self._handle.fileno(), 原位置, os.SEEK_SET)
            return 大小
        except OSError as 异常:
            raise OSError(f'无法获取设备大小: {self.dev_path}') from 异常

    def _pos_to_sector(self, offset: int) -> tuple[int, int]:
        return offset // self.sector_size, offset % self.sector_size

    def _read_sector_from_device(self, sec_idx: int) -> bytes:
        偏移 = sec_idx * self.sector_size
        if 偏移 < 0 or 偏移 >= self.大小:
            raise OSError(f'扇区 {sec_idx} 超出设备范围')
        读取大小 = min(self.sector_size, self.大小 - 偏移)

        self._handle.seek(偏移)
        数据 = self._handle.read(读取大小)

        if len(数据) != 读取大小:
            raise OSError(f'设备扇区短读：预期 {读取大小} 字节，实际 {len(数据)} 字节')
        if 读取大小 < self.sector_size:
            数据 += bytes(self.sector_size - 读取大小)
        return 数据

    def _write_sector_to_device(self, sec_idx: int, data: bytes) -> None:
        if len(data) != self.sector_size:
            raise ValueError('扇区数据大小与逻辑扇区大小不一致')

        偏移 = sec_idx * self.sector_size
        if 偏移 < 0 or 偏移 >= self.大小:
            raise OSError(f'扇区 {sec_idx} 超出设备范围')
        写入数据 = data[:min(self.sector_size, self.大小 - 偏移)]

        self._handle.seek(偏移)
        已写入 = self._handle.write(写入数据)
        if 已写入 != len(写入数据):
            raise OSError(f'设备扇区短写: {已写入}/{len(写入数据)}')

    def _evict_oldest(self) -> None:
        while len(self._cache) >= self.cache_max and self._access_list:
            最旧扇区 = self._access_list.pop(0)
            扇区数据, 已修改 = self._cache.pop(最旧扇区)
            if 已修改:
                self._write_sector_to_device(最旧扇区, 扇区数据)

    def _load_sector_to_cache(self, sec_idx: int) -> bytes:
        if sec_idx in self._cache:
            if sec_idx in self._access_list:
                self._access_list.remove(sec_idx)
            self._access_list.append(sec_idx)
            return self._cache[sec_idx][0]

        self._evict_oldest()
        扇区数据 = self._read_sector_from_device(sec_idx)
        self._cache[sec_idx] = (扇区数据, False)
        self._access_list.append(sec_idx)
        return 扇区数据

    def seek(self, offset: int, whence: int = 0) -> None:
        if whence != 0:
            raise NotImplementedError('仅支持 whence=0')
        if not isinstance(offset, int):
            raise TypeError('offset 必须是整数')
        if offset < 0 or offset > self.大小:
            raise ValueError(f'偏移 {offset} 超出设备范围 0..{self.大小}')
        self._pos = offset

    def tell(self) -> int:
        return self._pos

    def _检查访问大小(self, 大小: int) -> None:
        if not isinstance(大小, int):
            raise TypeError('大小必须是整数')
        if 大小 < 0:
            raise ValueError('大小不能为负数')
        if self._pos + 大小 > self.大小:
            raise OSError(f'访问范围 {self._pos}..{self._pos + 大小} 超出设备大小 {self.大小}')

    def read(self, size: int) -> bytes:
        self._检查访问大小(size)
        结果 = bytearray()
        剩余大小 = size
        while 剩余大小 > 0:
            扇区号, 扇区内偏移 = self._pos_to_sector(self._pos)
            if self.enable_cache:
                扇区数据 = self._load_sector_to_cache(扇区号)
            else:
                扇区数据 = self._read_sector_from_device(扇区号)

            读取大小 = min(剩余大小, self.sector_size - 扇区内偏移)
            结果.extend(扇区数据[扇区内偏移:扇区内偏移 + 读取大小])
            self._pos += 读取大小
            剩余大小 -= 读取大小
        return bytes(结果)

    def write(self, data: bytes) -> None:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError('data 必须是字节数据')
        数据 = bytes(data)
        self._检查访问大小(len(数据))

        数据偏移 = 0
        while 数据偏移 < len(数据):
            扇区号, 扇区内偏移 = self._pos_to_sector(self._pos)
            if self.enable_cache:
                扇区数据 = bytearray(self._load_sector_to_cache(扇区号))
            else:
                扇区数据 = bytearray(self._read_sector_from_device(扇区号))

            写入大小 = min(len(数据) - 数据偏移, self.sector_size - 扇区内偏移)
            扇区数据[扇区内偏移:扇区内偏移 + 写入大小] = 数据[
                数据偏移:数据偏移 + 写入大小
            ]

            if self.enable_cache:
                self._cache[扇区号] = (bytes(扇区数据), True)
                if 扇区号 in self._access_list:
                    self._access_list.remove(扇区号)
                self._access_list.append(扇区号)
            else:
                self._write_sector_to_device(扇区号, bytes(扇区数据))

            self._pos += 写入大小
            数据偏移 += 写入大小

    def flush(self) -> None:
        if self._handle is None:
            return

        for 扇区号, (数据, 已修改) in list(self._cache.items()):
            if 已修改:
                self._write_sector_to_device(扇区号, 数据)
                self._cache[扇区号] = (数据, False)

        os.fsync(self._handle.fileno())

    def toggle_cache(self, enable: bool) -> None:
        self.flush()
        self._cache.clear()
        self._access_list.clear()
        self.enable_cache = bool(enable)

    def close(self) -> None:
        if self._handle is None:
            return
        self.flush()
        self._handle.close()
        self._handle = None
        self._cache.clear()
        self._access_list.clear()

    def __enter__(self) -> '打开分区':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
