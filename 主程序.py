from 索引工具 import 索引工具
from 打开分区 import 打开分区

class 文件系统:
    def __init__(self, 索引文件: str, 设备: str, 索引自动保存: bool = False, 分区启用缓存: bool = True) -> None:
        self.索引文件 = 索引文件
        self.设备路径 = 设备

        self.索引自动保存 = 索引自动保存
        self.分区启用缓存 = 分区启用缓存

        self.索引 = 索引工具(self.索引文件, 自动保存=索引自动保存)
        self.设备 = 打开分区(self.设备路径, enable_cache=分区启用缓存)

    def _寻找空闲位置(self, 大小: int) -> list[tuple[int, int]]:
        pass

    def 创建文件(self, 路径: str) -> None:
        self.索引.文件_添加(路径)

    def 删除文件(self, 路径: str) -> None:
        self.索引.文件_删除(路径)

    def 重命名文件(self, 路径: str, 新路径: str) -> None:
        self.索引.文件_修改_重命名(路径, 新路径)

    def 文件_读取(self, 路径: str, 起始: int, 大小: int) -> bytes:
        索引 = self.索引.文件_读取(路径)
        if 起始 + 大小 > 索引['大小']:
            raise ValueError(f'起始位置 {起始} + 大小 {大小} 超过文件大小 {索引['大小']}')
        数据 = bytearray(大小)
        当前位置 = 起始
        结束位置 = 起始 + 大小
        for 数据位置, 数据大小 in 索引['数据位置']:
            if 当前位置 <= 数据位置:
                读取大小 = max(大小 - 当前位置, 数据大小)
                self.设备.seek(数据位置)
                数据[当前位置:当前位置 + 读取大小] = self.设备.read(读取大小)
                当前位置 += 读取大小
                if 当前位置 >= 结束位置:
                    break
        return bytes(数据)

    def 文件_写入(self, 路径: str, 起始: int, 数据: bytes) -> None:
        索引 = self.索引.文件_读取(路径)
        数据大小 = len(数据)
        结束位置 = 起始 + 数据大小
        需要追加 = 结束位置 > 索引['大小']
        覆盖大小 = 索引['大小'] - 起始 if 需要追加 else 数据大小
        if 覆盖大小 > 0:
            self.设备.seek(起始)
            self.设备.write(数据[:覆盖大小])
        if 需要追加:
            新位置 = self._寻找空闲位置(数据大小 - 覆盖大小)
            当前位置 = 覆盖大小
            for 数据位置, 数据大小 in 新位置:
                self.设备.seek(数据位置)
                self.设备.write(数据[当前位置:当前位置 + 数据大小])
                当前位置 += 数据大小

    def 关闭(self) -> None:
        if not self.索引自动保存:
            self.索引.保存索引()
        self.设备.close()

    def 刷新(self) -> None:
        if not self.索引自动保存:
            self.索引.保存索引()

        if self.分区启用缓存:
            self.设备.flush()

    def __enter__(self) -> '文件系统':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.关闭()
