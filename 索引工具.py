import copy
import json
import os
import tempfile


class 索引工具:
    def __init__(self, 索引文件: str, 自动保存: bool = True) -> None:
        self.索引文件 = 索引文件
        self.自动保存 = 自动保存
        self.编码 = 'utf-8'
        self.索引: dict[str, object] = {}
        self.加载索引()

    @staticmethod
    def _规范化位置(位置: object) -> tuple[int, int]:
        if not isinstance(位置, (list, tuple)) or len(位置) != 2:
            raise ValueError(f'无效的数据位置: {位置!r}')

        起始位置, 大小 = 位置
        if not isinstance(起始位置, int) or not isinstance(大小, int):
            raise ValueError(f'数据位置必须由整数组成: {位置!r}')
        if 起始位置 < 0 or 大小 <= 0:
            raise ValueError(f'数据位置起点不能为负数，大小必须大于 0: {位置!r}')
        return 起始位置, 大小

    @staticmethod
    def _位置重叠(位置1: tuple[int, int], 位置2: tuple[int, int]) -> bool:
        起点1, 大小1 = 位置1
        起点2, 大小2 = 位置2
        return 起点1 < 起点2 + 大小2 and 起点2 < 起点1 + 大小1

    def _初始化并校验结构(self) -> None:
        if not isinstance(self.索引, dict):
            raise ValueError('索引文件的根节点必须是 JSON 对象')

        文件集合 = self.索引.setdefault('文件', {})
        总位置 = self.索引.setdefault('总位置', [])
        if not isinstance(文件集合, dict):
            raise ValueError('索引中的“文件”必须是 JSON 对象')
        if not isinstance(总位置, list):
            raise ValueError('索引中的“总位置”必须是列表')

        规范总位置: list[tuple[int, int]] = []
        for 位置 in 总位置:
            规范位置 = self._规范化位置(位置)
            if 规范位置 not in 规范总位置:
                规范总位置.append(规范位置)

        文件占用位置: list[tuple[int, int]] = []
        for 路径, 文件索引 in 文件集合.items():
            if not isinstance(文件索引, dict):
                raise ValueError(f'文件 {路径} 的索引必须是 JSON 对象')
            if '大小' not in 文件索引 or '数据位置' not in 文件索引:
                raise ValueError(f'文件 {路径} 的索引缺少“大小”或“数据位置”')

            文件大小 = 文件索引['大小']
            数据位置 = 文件索引['数据位置']
            if not isinstance(文件大小, int) or 文件大小 < 0:
                raise ValueError(f'文件 {路径} 的大小无效')
            if not isinstance(数据位置, list):
                raise ValueError(f'文件 {路径} 的数据位置必须是列表')

            规范数据位置 = [self._规范化位置(位置) for 位置 in 数据位置]
            if sum(大小 for _, 大小 in 规范数据位置) != 文件大小:
                raise ValueError(f'文件 {路径} 的大小与数据位置不一致')

            for 位置 in 规范数据位置:
                if any(self._位置重叠(位置, 已占用) for 已占用 in 文件占用位置):
                    raise ValueError(f'文件 {路径} 的数据位置与其他文件重叠: {位置!r}')
                文件占用位置.append(位置)
                if 位置 not in 规范总位置:
                    规范总位置.append(位置)

            文件索引['数据位置'] = 规范数据位置

        for 序号, 位置 in enumerate(规范总位置):
            for 其他位置 in 规范总位置[序号 + 1:]:
                if self._位置重叠(位置, 其他位置):
                    raise ValueError(f'总位置中存在重叠区间: {位置!r} 和 {其他位置!r}')

        self.索引['总位置'] = sorted(规范总位置, key=lambda 位置: 位置[0])

    def 加载索引(self) -> None:
        try:
            with open(self.索引文件, 'r', encoding=self.编码) as f:
                self.索引 = json.load(f)
        except FileNotFoundError:
            self.索引 = {'文件': {}, '总位置': []}
        except json.JSONDecodeError as 异常:
            if os.path.getsize(self.索引文件) != 0:
                raise ValueError(f'索引文件不是有效 JSON: {self.索引文件}') from 异常
            self.索引 = {'文件': {}, '总位置': []}

        self._初始化并校验结构()

    def 保存索引(self) -> None:
        索引路径 = os.path.abspath(self.索引文件)
        目录 = os.path.dirname(索引路径)
        os.makedirs(目录, exist_ok=True)
        文件描述符, 临时路径 = tempfile.mkstemp(
            prefix=f'.{os.path.basename(索引路径)}.',
            suffix='.tmp',
            dir=目录
        )
        try:
            with os.fdopen(文件描述符, 'w', encoding=self.编码) as f:
                json.dump(self.索引, f, ensure_ascii=False, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(临时路径, 索引路径)
        finally:
            if os.path.exists(临时路径):
                os.unlink(临时路径)

    def _检查文件集合(self) -> dict[str, dict[str, object]]:
        文件集合 = self.索引.setdefault('文件', {})
        if not isinstance(文件集合, dict):
            raise ValueError('索引中的“文件”必须是对象')
        return 文件集合

    def _文件_检查(self, 路径: str) -> None:
        if 路径 not in self._检查文件集合():
            raise ValueError(f'路径 {路径} 不存在索引')

    def _检查总位置(self) -> list[tuple[int, int]]:
        总位置 = self.索引.setdefault('总位置', [])
        if not isinstance(总位置, list):
            raise ValueError('索引中的“总位置”必须是列表')
        return 总位置

    def 总位置_读取(self, 起始位置: int, 大小: int) -> list[tuple[int, int]]:
        if 起始位置 < 0 or 大小 < 0:
            raise ValueError('起始位置和大小不能为负数')
        if 大小 == 0:
            return []

        结束位置 = 起始位置 + 大小
        return [
            (位置, 占用大小)
            for 位置, 占用大小 in self._检查总位置()
            if 位置 < 结束位置 and 位置 + 占用大小 > 起始位置
        ]

    def 总位置_添加(self, 起始位置: int, 大小: int) -> None:
        新位置 = self._规范化位置((起始位置, 大小))
        if self.总位置_读取(起始位置, 大小):
            raise ValueError(f'数据位置已被占用: {新位置!r}')
        self._检查总位置().append(新位置)
        self._检查总位置().sort(key=lambda 位置: 位置[0])
        if self.自动保存:
            self.保存索引()

    def 总位置_删除(self, 起始位置: int, 大小: int) -> None:
        位置 = self._规范化位置((起始位置, 大小))
        for 文件索引 in self._检查文件集合().values():
            if 位置 in 文件索引['数据位置']:
                raise ValueError(f'数据位置仍被文件引用: {位置!r}')

        总位置 = self._检查总位置()
        if 位置 in 总位置:
            总位置.remove(位置)
            if self.自动保存:
                self.保存索引()

    def 文件_读取(self, 路径: str) -> dict[str, object]:
        self._文件_检查(路径)
        return copy.deepcopy(self._检查文件集合()[路径])

    def 文件_添加(self, 路径: str) -> None:
        文件集合 = self._检查文件集合()
        if 路径 in 文件集合:
            raise ValueError(f'路径 {路径} 已存在')
        文件集合[路径] = {
            '大小': 0,
            '数据位置': []
        }
        if self.自动保存:
            self.保存索引()

    def 文件_删除(self, 路径: str) -> None:
        self._文件_检查(路径)
        文件集合 = self._检查文件集合()
        总位置 = self._检查总位置()
        for 数据位置 in 文件集合[路径]['数据位置']:
            位置 = self._规范化位置(数据位置)
            if 位置 in 总位置:
                总位置.remove(位置)
        del 文件集合[路径]
        if self.自动保存:
            self.保存索引()

    def 文件_修改_重命名(self, 路径: str, 新路径: str) -> None:
        self._文件_检查(路径)
        if 路径 == 新路径:
            return

        文件集合 = self._检查文件集合()
        if 新路径 in 文件集合:
            raise ValueError(f'路径 {新路径} 已存在')
        文件集合[新路径] = 文件集合.pop(路径)
        if self.自动保存:
            self.保存索引()

    def 文件_修改_添加数据位置(self, 路径: str, 数据位置: list[tuple[int, int]]) -> None:
        self._文件_检查(路径)
        新位置 = [self._规范化位置(位置) for 位置 in 数据位置]

        for 序号, 位置 in enumerate(新位置):
            if self.总位置_读取(*位置):
                raise ValueError(f'数据位置已被占用: {位置!r}')
            if any(self._位置重叠(位置, 其他位置) for 其他位置 in 新位置[序号 + 1:]):
                raise ValueError(f'新数据位置存在重叠: {位置!r}')

        文件索引 = self._检查文件集合()[路径]
        文件索引['数据位置'].extend(新位置)
        文件索引['大小'] += sum(大小 for _, 大小 in 新位置)
        self._检查总位置().extend(新位置)
        self._检查总位置().sort(key=lambda 位置: 位置[0])
        if self.自动保存:
            self.保存索引()
