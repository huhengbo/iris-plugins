"""替换表：每行一条 ``原文=目标``，目标留空表示删除。

规则照搬 jellyfin-plugin-metatube 的 SubstitutionTable：键不区分大小写，同一个键以后面的行为准；
替换文本时按原文逐条做区分大小写的字符串替换，替换列表项时整项匹配，目标为空白则删除该项。
"""

from __future__ import annotations

from collections.abc import Iterable


class SubstitutionTable:
    def __init__(self, entries: dict[str, str]) -> None:
        # 键保留首次出现时的写法，查找用 casefold
        self._entries = entries
        self._lookup = {key.casefold(): value for key, value in entries.items()}

    @classmethod
    def parse(cls, text: str) -> SubstitutionTable:
        entries: dict[str, str] = {}
        folded: dict[str, str] = {}
        for line in text.splitlines():
            source, _, target = (part.strip() for part in line.partition("="))
            if not source:
                continue
            key = folded.setdefault(source.casefold(), source)
            entries[key] = target
        return cls(entries)

    def __bool__(self) -> bool:
        return bool(self._entries)

    def substitute_text(self, source: str) -> str:
        for key, value in self._entries.items():
            source = source.replace(key, value)
        return source

    def substitute_items(self, items: Iterable[str]) -> list[str]:
        result: list[str] = []
        for item in items:
            value = self._lookup.get(item.casefold())
            if value is None:
                result.append(item)
            elif value.strip():
                result.append(value)
        return result
