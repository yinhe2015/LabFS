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
        self._已关闭 = False

    def _寻找空闲位置(self, 大小: int) -> list[tuple[int, int]]:
        if 大小 < 0:
            raise ValueError('大小不能小于 0')
        if 大小 == 0:
            return []

        设备大小 = self.设备.大小
        if 大小 > 设备大小:
            raise OSError(f'设备剩余空间不足，需要 {大小} 字节')

        # 查询整个设备的已占用区间，不直接访问索引内部结构。
        已占用位置 = sorted(
            self.索引.总位置_读取(0, 设备大小),
            key=lambda 位置: 位置[0]
        )

        空闲位置: list[tuple[int, int]] = []
        当前位置 = 0
        剩余大小 = 大小

        for 起始位置, 已占用大小 in 已占用位置:
            if 起始位置 < 0 or 已占用大小 < 0:
                raise ValueError('总位置中的起始位置和大小不能小于 0')
            if 已占用大小 == 0:
                continue
            if 起始位置 + 已占用大小 > 设备大小:
                raise ValueError(f'总位置超出设备范围: {(起始位置, 已占用大小)!r}')

            if 起始位置 > 当前位置:
                可用大小 = min(起始位置 - 当前位置, 剩余大小)
                空闲位置.append((当前位置, 可用大小))
                剩余大小 -= 可用大小
                if 剩余大小 == 0:
                    return 空闲位置

            # max 可以合并重叠或完全包含的已占用区间。
            当前位置 = max(当前位置, 起始位置 + 已占用大小)

        末尾可用大小 = 设备大小 - 当前位置
        if 剩余大小 <= 末尾可用大小:
            空闲位置.append((当前位置, 剩余大小))
            return 空闲位置

        raise OSError(f'设备剩余空间不足，需要 {大小} 字节')

    @staticmethod
    def _映射文件区间(
        数据位置: list[tuple[int, int]],
        起始: int,
        大小: int
    ) -> list[tuple[int, int, int]]:
        """返回（物理位置、缓冲区偏移、大小）。"""
        if 大小 == 0:
            return []

        请求结束 = 起始 + 大小
        逻辑位置 = 0
        已映射大小 = 0
        映射结果: list[tuple[int, int, int]] = []

        for 物理位置, 分段大小 in 数据位置:
            if 物理位置 < 0 or 分段大小 <= 0:
                raise ValueError(f'文件索引中存在无效数据位置: {(物理位置, 分段大小)!r}')

            分段逻辑结束 = 逻辑位置 + 分段大小
            重叠起始 = max(起始, 逻辑位置)
            重叠结束 = min(请求结束, 分段逻辑结束)
            if 重叠起始 < 重叠结束:
                重叠大小 = 重叠结束 - 重叠起始
                映射结果.append((
                    物理位置 + 重叠起始 - 逻辑位置,
                    重叠起始 - 起始,
                    重叠大小
                ))
                已映射大小 += 重叠大小

            逻辑位置 = 分段逻辑结束
            if 逻辑位置 >= 请求结束:
                break

        if 已映射大小 != 大小:
            raise ValueError('文件大小与数据位置不一致')
        return 映射结果

    def 创建文件(self, 路径: str) -> None:
        self.索引.文件_添加(路径)

    def 删除文件(self, 路径: str) -> None:
        self.索引.文件_删除(路径)

    def 重命名文件(self, 路径: str, 新路径: str) -> None:
        self.索引.文件_修改_重命名(路径, 新路径)

    def 文件_读取(self, 路径: str, 起始: int, 大小: int) -> bytes:
        索引 = self.索引.文件_读取(路径)
        文件大小 = 索引['大小']
        if 起始 < 0 or 大小 < 0:
            raise ValueError('起始位置和大小不能为负数')
        if 起始 + 大小 > 文件大小:
            raise ValueError(f'起始位置 {起始} + 大小 {大小} 超过文件大小 {文件大小}')

        数据 = bytearray(大小)
        for 物理位置, 数据偏移, 读取大小 in self._映射文件区间(索引['数据位置'], 起始, 大小):
            self.设备.seek(物理位置)
            读取数据 = self.设备.read(读取大小)
            if len(读取数据) != 读取大小:
                raise OSError(f'设备只读取了 {len(读取数据)} 字节，预期 {读取大小} 字节')
            数据[数据偏移:数据偏移 + 读取大小] = 读取数据
        return bytes(数据)

    def 文件_写入(self, 路径: str, 起始: int, 数据: bytes) -> None:
        索引 = self.索引.文件_读取(路径)
        if 起始 < 0:
            raise ValueError('起始位置不能为负数')
        if not isinstance(数据, (bytes, bytearray, memoryview)):
            raise TypeError('数据必须是字节数据')
        数据 = bytes(数据)

        文件大小 = 索引['大小']
        if 起始 > 文件大小:
            raise ValueError(f'起始位置 {起始} 超过文件大小 {文件大小}，不支持稀疏写入')

        数据大小 = len(数据)
        if 数据大小 == 0:
            return

        结束位置 = 起始 + 数据大小
        追加大小 = max(0, 结束位置 - 文件大小)
        覆盖大小 = 数据大小 - 追加大小
        新位置 = self._寻找空闲位置(追加大小) if 追加大小 else []

        if 覆盖大小 > 0:
            for 物理位置, 数据偏移, 写入大小 in self._映射文件区间(
                索引['数据位置'],
                起始,
                覆盖大小
            ):
                self.设备.seek(物理位置)
                self.设备.write(数据[数据偏移:数据偏移 + 写入大小])

        if 新位置:
            当前位置 = 覆盖大小
            for 物理位置, 分段大小 in 新位置:
                self.设备.seek(物理位置)
                self.设备.write(数据[当前位置:当前位置 + 分段大小])
                当前位置 += 分段大小

            # 自动保存索引时，也要保证先落盘数据，再持久化元数据。
            self.设备.flush()
            self.索引.文件_修改_添加数据位置(路径, 新位置)

    def 关闭(self) -> None:
        if self._已关闭:
            return

        # 先落盘数据，再保存引用这些数据的索引。
        self.设备.flush()
        if not self.索引自动保存:
            self.索引.保存索引()
        self.设备.close()
        self._已关闭 = True

    def 刷新(self) -> None:
        self.设备.flush()
        if not self.索引自动保存:
            self.索引.保存索引()

    def __enter__(self) -> '文件系统':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.关闭()
