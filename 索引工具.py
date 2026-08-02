import json

class 索引工具:
    def __init__(self, 索引文件: str, 自动保存: bool = True) -> None:
        self.索引文件 = 索引文件
        self.自动保存 = 自动保存
        self.编码 = 'utf-8'
        self.索引 = {}
        self.加载索引()

    def 加载索引(self) -> None:
        with open(self.索引文件, 'r', encoding=self.编码) as f:
            self.索引 = json.load(f)

    def 保存索引(self) -> None:
        with open(self.索引文件, 'w', encoding=self.编码) as f:
            json.dump(self.索引, f, indent=4)

    def _文件_检查(self, 路径: str) -> None:
        if '文件' not in self.索引:
            self.索引['文件'] = {}
            raise ValueError(f'路径 {路径} 不存在索引')

        if 路径 not in self.索引['文件']:
            raise ValueError(f'路径 {路径} 不存在索引')

    def _检查总位置(self) -> None:
        if '总位置' not in self.索引:
            self.索引['总位置'] = []

    def 总位置_读取(self, 起始位置: int, 大小: int) -> list[tuple[int, int]]:
        self._检查总位置()
        return self.索引['总位置']

    def 总位置_添加(self, 起始位置: int, 大小: int) -> None:
        self._检查总位置()
        self.索引['总位置'].append((起始位置, 大小))
        if self.自动保存:
            self.保存索引()

    def 总位置_删除(self, 起始位置: int, 大小: int) -> None:
        self._检查总位置()
        if (起始位置, 大小) in self.索引['总位置']:
            self.索引['总位置'].remove((起始位置, 大小))
            if self.自动保存:
                self.保存索引()

    def 文件_读取(self, 路径: str) -> dict[str, int]:
        self._文件_检查(路径)
        return self.索引['文件'][路径]

    def 文件_添加(self, 路径: str) -> None:
        self.索引['文件'][路径] = {
            '大小': 0,
            '数据位置': []
        }
        if self.自动保存:
            self.保存索引()

    def 文件_删除(self, 路径: str) -> None:
        self._文件_检查(路径)
        for 数据位置, 数据大小 in self.索引['文件'][路径]['数据位置']:
            self.总位置_删除(数据位置, 数据大小)
        del self.索引['文件'][路径]
        if self.自动保存:
            self.保存索引()

    def 文件_修改_重命名(self, 路径: str, 新路径: str) -> None:
        self._文件_检查(路径)
        self.索引['文件'][新路径] = self.索引['文件'][路径]
        del self.索引['文件'][路径]
        if self.自动保存:
            self.保存索引()

    def 文件_修改_添加数据位置(self, 路径: str, 数据位置: list[tuple[int, int]]) -> None:
        self.索引['文件'][路径]['数据位置'].extend(数据位置)
        for 数据位置, 数据大小 in 数据位置:
            self.总位置_添加(数据位置, 数据大小)
            self.索引['文件'][路径]['大小'] += 数据大小
        if self.自动保存:
            self.保存索引()