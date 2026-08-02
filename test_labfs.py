import json
import os
import struct
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import 打开分区 as 分区模块
from 主程序 import 文件系统
from 打开分区 import 打开分区
from 索引工具 import 索引工具


class 索引工具测试(unittest.TestCase):
    def setUp(self) -> None:
        self.临时目录 = tempfile.TemporaryDirectory()
        self.索引路径 = os.path.join(self.临时目录.name, '索引.json')

    def tearDown(self) -> None:
        self.临时目录.cleanup()

    def test_空索引可以创建第一个文件(self) -> None:
        工具 = 索引工具(self.索引路径, 自动保存=False)
        工具.文件_添加('/first')
        self.assertEqual(工具.文件_读取('/first'), {'大小': 0, '数据位置': []})

    def test_空文件也能初始化为索引(self) -> None:
        with open(self.索引路径, 'wb'):
            pass
        工具 = 索引工具(self.索引路径, 自动保存=False)
        self.assertEqual(工具.索引, {'文件': {}, '总位置': []})

    def test_索引往返_json_后可以释放数据位置(self) -> None:
        工具 = 索引工具(self.索引路径, 自动保存=False)
        工具.文件_添加('/a')
        工具.文件_修改_添加数据位置('/a', [(10, 5)])
        工具.保存索引()

        重载工具 = 索引工具(self.索引路径, 自动保存=False)
        重载工具.文件_删除('/a')
        self.assertEqual(重载工具.总位置_读取(0, 100), [])

    def test_不允许单独释放仍被文件引用的位置(self) -> None:
        工具 = 索引工具(self.索引路径, 自动保存=False)
        工具.文件_添加('/a')
        工具.文件_修改_添加数据位置('/a', [(10, 5)])
        with self.assertRaises(ValueError):
            工具.总位置_删除(10, 5)

    def test_总位置读取按物理区间过滤(self) -> None:
        工具 = 索引工具(self.索引路径, 自动保存=False)
        工具.总位置_添加(10, 5)
        工具.总位置_添加(30, 5)
        self.assertEqual(工具.总位置_读取(12, 1), [(10, 5)])
        self.assertEqual(工具.总位置_读取(15, 15), [])
        self.assertEqual(工具.总位置_读取(14, 17), [(10, 5), (30, 5)])

    def test_同名创建和重命名不会覆盖旧索引(self) -> None:
        工具 = 索引工具(self.索引路径, 自动保存=False)
        工具.文件_添加('/a')
        工具.文件_添加('/b')
        with self.assertRaises(ValueError):
            工具.文件_添加('/a')
        with self.assertRaises(ValueError):
            工具.文件_修改_重命名('/a', '/b')

    def test_保存后索引仍是完整_json(self) -> None:
        工具 = 索引工具(self.索引路径, 自动保存=False)
        工具.文件_添加('/a')
        工具.保存索引()
        with open(self.索引路径, 'r', encoding='utf-8') as f:
            self.assertEqual(json.load(f)['文件']['/a']['大小'], 0)


class 分区访问测试(unittest.TestCase):
    def setUp(self) -> None:
        self.临时目录 = tempfile.TemporaryDirectory()
        self.镜像路径 = os.path.join(self.临时目录.name, '分区.img')
        with open(self.镜像路径, 'wb') as f:
            f.truncate(128)

    def tearDown(self) -> None:
        self.临时目录.cleanup()

    def test_跨扇区读写和容量限制(self) -> None:
        with 打开分区(self.镜像路径, sector_size=16) as 分区:
            self.assertEqual(分区.大小, 128)
            分区.seek(14)
            分区.write(b'abcdef')
            分区.seek(14)
            self.assertEqual(分区.read(6), b'abcdef')
            分区.seek(127)
            with self.assertRaises(OSError):
                分区.write(b'xx')

    def test_重新启用缓存后不读取旧数据(self) -> None:
        with 打开分区(self.镜像路径, sector_size=16) as 分区:
            分区.read(1)
            分区.toggle_cache(False)
            分区.seek(0)
            分区.write(b'X')
            分区.toggle_cache(True)
            分区.seek(0)
            self.assertEqual(分区.read(1), b'X')

    def test_windows_api_返回值顺序和容量解析(self) -> None:
        class 假Win32File:
            写入数据 = b''

            @staticmethod
            def SetFilePointer(句柄, 偏移, 高位, 基准):
                return None

            @staticmethod
            def ReadFile(句柄, 大小):
                return 0, b'ABCD'[:大小]

            @classmethod
            def WriteFile(cls, 句柄, 数据):
                cls.写入数据 = 数据
                return 0, len(数据)

            @staticmethod
            def DeviceIoControl(句柄, 控制码, 输入, 输出大小):
                return struct.pack('<Q', 4096)

        分区 = 打开分区.__new__(打开分区)
        分区._handle = object()
        分区.sector_size = 4
        分区.大小 = 4

        with (
            mock.patch.object(分区模块, 'IS_WIN', True),
            mock.patch.object(分区模块, 'win32file', 假Win32File, create=True),
            mock.patch.object(分区模块, 'win32con', SimpleNamespace(FILE_BEGIN=0), create=True),
            mock.patch.object(
                分区模块,
                'winioctlcon',
                SimpleNamespace(IOCTL_DISK_GET_LENGTH_INFO=0x0007405C),
                create=True
            )
        ):
            self.assertEqual(分区._read_sector_from_device(0), b'ABCD')
            分区._write_sector_to_device(0, b'WXYZ')
            self.assertEqual(假Win32File.写入数据, b'WXYZ')
            self.assertEqual(分区._get_device_size(), 4096)


class 文件系统集成测试(unittest.TestCase):
    def setUp(self) -> None:
        self.临时目录 = tempfile.TemporaryDirectory()
        self.镜像路径 = os.path.join(self.临时目录.name, '分区.img')
        self.索引路径 = os.path.join(self.临时目录.name, '索引.json')
        with open(self.镜像路径, 'wb') as f:
            f.truncate(128)

    def tearDown(self) -> None:
        self.临时目录.cleanup()

    def test_分片文件可以读取覆盖追加并重载(self) -> None:
        with 文件系统(self.索引路径, self.镜像路径) as 系统:
            系统.创建文件('/a')
            系统.文件_写入('/a', 0, b'ABCD')
            系统.创建文件('/b')
            系统.文件_写入('/b', 0, b'1234')
            系统.文件_写入('/a', 4, b'EFGH')

            self.assertEqual(系统.文件_读取('/a', 2, 4), b'CDEF')
            系统.文件_写入('/a', 2, b'xyz12')
            self.assertEqual(系统.文件_读取('/a', 0, 8), b'ABxyz12H')

            系统.文件_写入('/a', 8, b'++')
            系统.删除文件('/b')
            系统.文件_写入('/a', 10, b'QQQQQQ')
            self.assertEqual(系统.文件_读取('/a', 0, 16), b'ABxyz12H++QQQQQQ')

        with 文件系统(self.索引路径, self.镜像路径) as 重载系统:
            self.assertEqual(重载系统.文件_读取('/a', 0, 16), b'ABxyz12H++QQQQQQ')

    def test_自动保存索引前数据已经落盘(self) -> None:
        with 文件系统(
            self.索引路径,
            self.镜像路径,
            索引自动保存=True
        ) as 系统:
            系统.创建文件('/a')
            系统.文件_写入('/a', 0, b'durable')
            with open(self.镜像路径, 'rb') as f:
                self.assertEqual(f.read(7), b'durable')
            with open(self.索引路径, 'r', encoding='utf-8') as f:
                self.assertEqual(json.load(f)['文件']['/a']['大小'], 7)

    def test_稀疏写入和容量超限不会修改索引(self) -> None:
        with 文件系统(self.索引路径, self.镜像路径) as 系统:
            系统.创建文件('/a')
            with self.assertRaises(ValueError):
                系统.文件_写入('/a', 1, b'x')
            with self.assertRaises(OSError):
                系统.文件_写入('/a', 0, bytes(129))
            self.assertEqual(系统.索引.文件_读取('/a')['大小'], 0)


if __name__ == '__main__':
    unittest.main()
