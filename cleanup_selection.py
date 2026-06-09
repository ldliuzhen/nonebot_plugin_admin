import re


def parse_cleanup_selection(confirm: str, total: int):
    if confirm == '确认':
        return list(range(total)), None
    if not confirm.startswith('确认清理'):
        return None, None

    selector = confirm[len('确认清理'):].strip()
    if not selector:
        return [], '请填写要清理的序号，例如：确认清理 2 或 确认清理 2-10'

    selector = re.sub(r'\s*([-~～－])\s*', r'\1', selector)
    parts = [part for part in re.split(r'[\s,，、]+', selector) if part]
    selected = []
    seen = set()

    for part in parts:
        match = re.fullmatch(r'(\d+)(?:[-~～－](\d+))?', part)
        if not match:
            return [], '序号格式不正确，请回复「确认清理 2」或「确认清理 2-10」'

        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start > end:
            return [], '序号范围起点不能大于终点，请重新回复'
        if start < 1 or end > total:
            return [], f'序号范围需在 1-{total} 之间，请重新回复'

        for index in range(start - 1, end):
            if index not in seen:
                selected.append(index)
                seen.add(index)

    if not selected:
        return [], '请填写要清理的序号，例如：确认清理 2 或 确认清理 2-10'
    return selected, None
