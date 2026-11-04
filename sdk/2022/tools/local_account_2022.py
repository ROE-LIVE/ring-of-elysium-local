"""Именованные локальные профили; идентичность не является оригинальной авторизацией."""
import hashlib
from pathlib import Path
import re

DEFAULT_ACTOR_UID = 0x515BB1E1DD242C
_RESERVED = {'con', 'prn', 'aux', 'nul'} | {
    prefix + str(number) for prefix in ('com', 'lpt') for number in range(1, 10)
}


def local_account(runtime, name='default'):
    """Возвращает устойчивый public UID и путь; не создаёт файлы/сокеты."""
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,31}', name):
        raise ValueError('Profile:1..32 ASCII букв/цифр, _ и -, начало буква/цифра')
    canonical = name.lower()
    if canonical in _RESERVED:
        raise ValueError('Profile: имя устройства Windows запрещено')
    runtime = Path(runtime)
    if canonical == 'default':
        state = runtime / 'local-account/cosmetics.json'
        uid = DEFAULT_ACTOR_UID
    else:
        state = runtime / 'local-accounts' / canonical / 'cosmetics.json'
        # Low2bits0 подтверждены native223–226; это synthetic ID, не token.
        digest = hashlib.sha256(('roe-local-2022:' + canonical).encode('ascii')).digest()
        uid = 0x515BB100000000 | (int.from_bytes(digest[:4], 'big') & 0xFFFFFFFC)
        if uid == DEFAULT_ACTOR_UID:
            uid ^= 4
    return dict(name=canonical, actor_uid=uid, state_file=str(state))
