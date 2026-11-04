"""Экспериментальная команда одного участника по decoder EXE2022, не сервер матча."""
import struct
from roe_protocol_2022 import dt_plain, encrypt, MAGIC


def client_message(frame, key):
    plain = dt_plain(frame, key)
    if plain is None:
        return None
    if frame[3] != 4 or len(plain) < 34:
        raise ValueError('Неизвестный формат клиентского DT')
    length, code = struct.unpack_from('>IH', plain, 4)
    if length != len(plain) - 4 or code != struct.unpack_from('>I', plain, 30)[0]:
        raise ValueError('Не совпала длина или body-tag')
    return code, struct.unpack_from('>Q', plain, 22)[0], plain[34:]


def server_message(code, body, stamp, key):
    plain = struct.pack('>IHI', stamp, code, code) + body
    cipher = encrypt(plain, key)
    return MAGIC + b'\0\0' + struct.pack('>II', 12, len(cipher)) + cipher


def team_body(uid, request, nickname='Player', team_id=1):
    """Полная минимальная схема; семантика неизвестных слов требует Windows-теста."""
    if not 0 < uid < 2**64 or not 0 < team_id < 2**64:
        raise ValueError('Нужны ненулевые идентификаторы')
    if len(request) != 16:
        raise ValueError('CREATE_REQ должен содержать четыре U32')
    mode, map_id, perspective, unknown = struct.unpack('>IIII', request)
    name = nickname.encode('utf-8') + b'\0'
    if not nickname or '\0' in nickname or len(name) > 128:
        raise ValueError('Имя должно занимать 1…128 байт с NUL')
    # Result; team-id/type/leader/unknown/count. Два UID согласованы с ENTER_GAME.
    prefix = struct.pack('>IQIQII', 0, team_id, mode, uid, 0, 1)
    # Двенадцать слов участника: исходный пример [0,2,211433,0,0,0,0,49,1,85,1,0].
    # Идентификаторы внешности/профиля не копируются из чужого захвата.
    words = (0, 2, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0)
    member = struct.pack('>QI', uid, len(name)) + name + struct.pack('>12I', *words)
    tail = struct.pack('>4I', unknown, map_id, perspective, 5)
    return prefix + member + tail + struct.pack('>I', 0)


def decode_minimal_team(body):
    """Строгий независимый reader минимальной ветки для офлайн проверки."""
    if len(body) < 52:
        raise ValueError('Недостаточно данных')
    result, team_id, mode, leader, unknown, count = struct.unpack_from('>IQIQII', body)
    if count != 1:
        raise ValueError('Ожидается один участник')
    uid, length = struct.unpack_from('>QI', body, 32)
    if not 1 <= length <= 128 or len(body) != 112 + length:
        raise ValueError('Неверная длина записи')
    name = body[44:44 + length]
    if name[-1] != 0 or b'\0' in name[:-1]:
        raise ValueError('Неверная NUL-строка')
    words = struct.unpack_from('>12I', body, 44 + length)
    tail = struct.unpack_from('>4I', body, 92 + length)
    if struct.unpack_from('>I', body, 108 + length)[0] != 0:
        raise ValueError('Дополнительный список должен быть пуст')
    return {'result': result, 'team_id': team_id, 'mode': mode, 'leader': leader,
            'unknown': unknown, 'uid': uid, 'nickname': name[:-1].decode('utf-8'),
            'member_words': words, 'tail': tail}
