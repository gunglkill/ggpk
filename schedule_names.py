# -*- coding: utf-8 -*-
"""Разбор даты из имён файлов расписания и изменений."""
import os
import re
from datetime import date

# Поддерживаем YYYY-MM-DD и DD.MM.YYYY в любом месте имени файла.
_PATTERNS = (
    re.compile(r'(?<!\d)(\d{4})[-_.](\d{1,2})[-_.](\d{1,2})(?!\d)'),
    re.compile(r'(?<!\d)(\d{1,2})[._-](\d{1,2})[._-](\d{2,4})(?!\d)'),
)


def parse_schedule_date(filename):
    """Вернуть дату из имени; суффиксы-дубликаты вроде (1) пропускаются."""
    name = os.path.basename(str(filename or ''))
    # VK нередко добавляет (1), (2) и т. п. к повторным именам файлов.
    name = re.sub(r'\(\s*\d+\s*\)', ' ', name)
    for index, pattern in enumerate(_PATTERNS):
        match = pattern.search(name)
        if not match:
            continue
        parts = [int(part) for part in match.groups()]
        if index == 0:
            year, month, day = parts
        else:
            day, month, year = parts
            if year < 100:
                year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None
