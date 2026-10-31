"""标题相似度：把「番号+标题」去掉空白和括号后比较编辑距离，用来确认 AVBASE 的结果是同一部片子。"""

from __future__ import annotations

import re

_STRIP = re.compile(r"[\s\[\]()【】（）]")


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return len(a) or len(b)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def title_similarity(source: tuple[str, str], target: tuple[str, str]) -> float:
    """source、target 都是（番号，标题）。"""
    source_key = _normalize("".join(source))
    target_key = _normalize("".join(target))
    if not source_key or not target_key:
        return 0.0
    average = (len(source_key) + len(target_key)) / 2
    return min(max(1.0 - levenshtein(source_key, target_key) / average, 0.0), 1.0)


def _normalize(value: str) -> str:
    return _STRIP.sub("", value.lower()).strip()
