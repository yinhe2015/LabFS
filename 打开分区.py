import subprocess
import sys
import re
import os

# 区分平台
IS_WIN = sys.platform.startswith("win")
if IS_WIN:
    import win32file  # pyright: ignore[reportMissingModuleSource]
    import win32con  # pyright: ignore[reportMissingModuleSource]

class 打开分区:
    def _prevent_write_to_system_disk(self):
        """在 __init__ 内部调用，禁止打开系统盘（Windows C盘，*nix / 根盘）"""
        dev = self.dev_path.lower()
        # Windows 判断 C 盘
        if IS_WIN:
            if re.match(r'\\\\\.\\\\physicaldrive0', dev) or re.match(r'\\\\\.\\\\c:', dev):
                raise PermissionError("禁止操作 Windows 系统盘(C盘 / PhysicalDrive0)")
        else:
            # Linux / macOS：拦截根目录所在的整块磁盘（简单判断，拦截 disk0 / sda）
            system_dev_patterns = ["/dev/disk0", "/dev/sda", "/dev/vda"]
            for pat in system_dev_patterns:
                if dev.startswith(pat):
                    raise PermissionError("禁止操作系统根磁盘，只能操作外接U盘等移动设备")

    def _unmount_if_mounted(self):
        """在 __init__ 内部调用：尝试卸载当前设备对应的挂载点，只卸载分区，不弹出磁盘"""
        dev = self.dev_path
        if IS_WIN:
            # Windows: 解析盘符 \\\\.\\X:，执行 mountvol /d 解除挂载
            match = re.search(r'([A-Za-z]):$', dev)
            if match:
                drive_letter = match.group(1) + ":"
                try:
                    subprocess.run(["mountvol", drive_letter, "/d"],
                                capture_output=True, shell=True, check=False)
                except Exception:
                    pass
        elif sys.platform == "darwin":
            # macOS：用 diskutil unmount 分区设备
            try:
                subprocess.run(["diskutil", "unmount", dev],
                            capture_output=True, check=False)
            except Exception:
                pass
        else:
            # Linux：umount
            try:
                subprocess.run(["umount", dev],
                            capture_output=True, check=False)
            except Exception:
                pass

    def _get_sector_size(self) -> int:
        """自动探测当前块设备逻辑扇区大小，失败返回默认512"""
        dev = self.dev_path

        if IS_WIN:
            # Windows 方式：wmic 查询逻辑扇区
            if dev.startswith(r"\\.\PhysicalDrive"):
                num = re.search(r"PhysicalDrive(\d+)", dev).group(1)
                cmd = [
                    "wmic",
                    "diskdrive",
                    f"index={num}",
                    "get",
                    "LogicalSectorSize",
                    "/value"
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                match = re.search(r"LogicalSectorSize=(\d+)", result.stdout)
                if match:
                    return int(match.group(1))
            # 分区盘符模式 \\.\X: 无法直接wmic获取， fallback 512
            return 512

        elif sys.platform == "darwin":
            # macOS 使用 diskutil 获取
            cmd = ["diskutil", "info", dev]
            result = subprocess.run(cmd, capture_output=True, text=True)
            match = re.search(r"Logical Block Size:\s*(\d+)", result.stdout)
            if match:
                return int(match.group(1))
            return 512

        else:
            # Linux：读取sysfs，最优方案
            match_dev = re.search(r"/dev/([a-zA-Z0-9]+)", dev)
            if match_dev:
                dev_name = match_dev.group(1)
                path = f"/sys/block/{dev_name}/queue/logical_block_size"
                try:
                    with open(path, "r") as f:
                        return int(f.read().strip())
                except (FileNotFoundError, ValueError):
                    pass
            # 备选：lsblk
            cmd = ["lsblk", "-o", "log-sec", "-n", dev]
            result = subprocess.run(cmd, capture_output=True, text=True)
            try:
                return int(result.stdout.strip())
            except ValueError:
                return 512

    def __init__(self, dev_path, enable_cache=True, cache_max_sectors=256):
        """
        :param dev_path: 块设备路径(\\\\.\\PhysicalDriveX 或者 /dev/diskXs1)
        :param sector_size: 扇区大小，默认512
        :param enable_cache: 开启内存缓存
        :param cache_max_sectors: 缓存最多持有多少个扇区，超出淘汰旧脏扇区
        """
        self.dev_path = dev_path

        # 先校验系统盘
        self._prevent_write_to_system_disk()
        # 尝试卸载挂载点
        self._unmount_if_mounted()

        self.sector_size = self._get_sector_size()
        self.enable_cache = enable_cache
        self.cache_max = cache_max_sectors

        # 缓存：key=sector_idx(int), value = (data:bytes, dirty:bool)
        self._cache = dict()
        # 记录扇区访问顺序，用于LRU淘汰
        self._access_list = []
        # 当前全局文件指针(字节偏移)
        self._pos = 0
        # 底层句柄
        self._handle = None
        self._open_device()

    def _open_device(self):
        if IS_WIN:
            # Windows 打开块设备 rb+ 读写
            handle = win32file.CreateFile(
                self.dev_path,
                win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                None,
                win32con.OPEN_EXISTING,
                win32con.FILE_FLAG_NO_BUFFERING,
                None
            )
            self._handle = handle
        else:
            # macOS / Linux 原生打开块设备 rb+
            self._handle = open(self.dev_path, "rb+", buffering=0)

    def _pos_to_sector(self, offset):
        """全局字节偏移 → 扇区号 + 扇区内偏移"""
        sec_idx = offset // self.sector_size
        in_sec_off = offset % self.sector_size
        return sec_idx, in_sec_off

    def _read_sector_from_device(self, sec_idx):
        """从物理设备读取一整个扇区"""
        off = sec_idx * self.sector_size
        if IS_WIN:
            win32file.SetFilePointer(self._handle, off, 0, win32con.FILE_BEGIN)
            buf, _ = win32file.ReadFile(self._handle, self.sector_size)
            return buf
        else:
            self._handle.seek(off)
            data = self._handle.read(self.sector_size)
            # 补齐不足扇区长度的部分（末尾）
            if len(data) < self.sector_size:
                data += bytes(self.sector_size - len(data))
            return data

    def _write_sector_to_device(self, sec_idx, data):
        """把完整扇区写回物理设备"""
        assert len(data) == self.sector_size
        off = sec_idx * self.sector_size
        if IS_WIN:
            win32file.SetFilePointer(self._handle, off, 0, win32con.FILE_BEGIN)
            win32file.WriteFile(self._handle, data)
        else:
            self._handle.seek(off)
            self._handle.write(data)

    def _evict_oldest(self):
        """LRU淘汰最久未访问的扇区，如果是脏扇区先刷盘"""
        while len(self._cache) >= self.cache_max and self._access_list:
            oldest_sec = self._access_list.pop(0)
            sec_data, is_dirty = self._cache.pop(oldest_sec)
            if is_dirty:
                self._write_sector_to_device(oldest_sec, sec_data)

    def _load_sector_to_cache(self, sec_idx):
        """加载扇区进缓存，维护LRU"""
        if sec_idx in self._cache:
            # 更新访问顺序
            if sec_idx in self._access_list:
                self._access_list.remove(sec_idx)
            self._access_list.append(sec_idx)
            return self._cache[sec_idx][0]

        # 缓存已满，淘汰旧的
        self._evict_oldest()
        # 从磁盘读取
        sec_data = self._read_sector_from_device(sec_idx)
        self._cache[sec_idx] = (sec_data, False)
        self._access_list.append(sec_idx)
        return sec_data

    def seek(self, offset, whence=0):
        """模仿文件seek，只支持 SEEK_SET(0)"""
        if whence != 0:
            raise NotImplementedError("仅支持 whence=0")
        self._pos = offset

    def tell(self):
        return self._pos

    def read(self, size):
        """读取任意长度字节，自动跨扇区，优先读缓存"""
        result = bytearray()
        remaining = size
        while remaining > 0:
            sec_idx, in_off = self._pos_to_sector(self._pos)
            if self.enable_cache:
                sec_data = self._load_sector_to_cache(sec_idx)
            else:
                sec_data = self._read_sector_from_device(sec_idx)

            read_len = min(remaining, self.sector_size - in_off)
            chunk = sec_data[in_off:in_off + read_len]
            result.extend(chunk)
            self._pos += read_len
            remaining -= read_len
        return bytes(result)

    def write(self, data: bytes):
        """写入任意字节，修改内存缓存扇区，标记脏，不立刻刷盘"""
        data = bytearray(data)
        ptr = 0
        while ptr < len(data):
            sec_idx, in_off = self._pos_to_sector(self._pos)
            if self.enable_cache:
                # 载入扇区到缓存
                sec_data = bytearray(self._load_sector_to_cache(sec_idx))
                write_len = min(len(data) - ptr, self.sector_size - in_off)
                sec_data[in_off:in_off + write_len] = data[ptr:ptr + write_len]
                # 更新缓存，标记为脏
                self._cache[sec_idx] = (bytes(sec_data), True)
                # 更新访问顺序
                if sec_idx in self._access_list:
                    self._access_list.remove(sec_idx)
                self._access_list.append(sec_idx)
            else:
                # 关闭缓存模式：先读整个扇区，内存修改，直接写回设备
                sec_data = bytearray(self._read_sector_from_device(sec_idx))
                write_len = min(len(data) - ptr, self.sector_size - in_off)
                sec_data[in_off:in_off + write_len] = data[ptr:ptr + write_len]
                self._write_sector_to_device(sec_idx, bytes(sec_data))

            written = min(len(data) - ptr, self.sector_size - in_off)
            self._pos += written
            ptr += written

    def flush(self):
        """把所有缓存内的脏扇区全部写入物理设备，清空脏标记"""
        if not self.enable_cache:
            return
        to_flush = []
        for sec_idx, (data, dirty) in self._cache.items():
            if dirty:
                to_flush.append((sec_idx, data))
        for sec_idx, data in to_flush:
            self._write_sector_to_device(sec_idx, data)
            # 把脏标记改成False
            self._cache[sec_idx] = (data, False)

    def toggle_cache(self, enable: bool):
        """开关缓存，切换前自动flush"""
        self.flush()
        self.enable_cache = enable

    def close(self):
        self.flush()
        if IS_WIN:
            win32file.CloseHandle(self._handle)
        else:
            self._handle.close()
        self._cache.clear()
        self._access_list.clear()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()