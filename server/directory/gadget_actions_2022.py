"""Gadgets táticos de Vera/Europa: barricada (obstáculo) — experimento local, sem regra original verificada.

Formatos pelo codificador do cliente (switch 0x74CD, tabela 140ca86d8) e pelo tratador de
0x74D0 (140dee00, registrado em 1412ded40):

  0x74E0 USE_BARRIER_REQ (46 B, montado em 1411e5a80): POS13 do objeto, POS13 de um 2º ponto,
         U32, F32 giro (atan2 × const), 3×F32.
  0x74E1 USE_BARRIER_RSP: U32 resultado.
  0x74D0 OBSTACLE_BC_SYNC_INFO: U64 uid, U64 dono, U32 config, POS13, 3×U32, U32 vida,
         U32 vida máxima, U32 tipo (1 barreira, 2 isca: + bloco da isca), U32, 3×F32 rotação,
         U32 sinal (1 → objeto do próprio jogador).
  0x74CF OBSTACLE_BC_LEAVE_SCENE: U64 uid, U32.

EuVehicleTable_barrier (TableBin 917): nId 101, E_OBSTACLE_TYPE_BARRIER, nHp 7500, nTime 30 s.
"""
import struct

BARRIER_CONFIG, BARRIER_HP, BARRIER_SECONDS = 101, 7500, 30
OBSTACLE_BARRIER = 1
BARRIER_ABILITY, BARRIER_COUNT = 27, 28        # ATR_INIT_ABILITY_BARRIER / ATR_BARRIER_LEFT_COUNT
OBSTACLE_UID_BASE = 0x7600000000000             # faixa própria, fora dos UIDs de atores e veículos

# Scanner (EuTacticalScanSystem, tabela EuTacticalScanConfigTable): a varredura é do cliente
# (cone de 150°, mScanAbortDistance 2500, marca some em ~10,5–11 s). Para cada unidade viva
# não aliada no cone (1412d2994 → 1412d2b40) ele manda 0x11C9 BC_CLIENT_DATA_REQ tipo 15
# (U32 tipo, U8, U32 n, n bytes: U64 id + 3×U32 posição) e 0x1167 SCANNER_MARK_REQ (U64 unit).
# 0x1168 SCANNER_MARKED_STATUS_NTF (tratador 1412d2d90) ignora o corpo: toca
# QSConfig.RadarCfg.DetectedFx e o aviso de "detectado" — vai para o jogador marcado.
# O gasto do uso vem em 0x536 ACTOR_EU_ACTION_REQ com E_EU_AT_USE_SCANNER = 72 (confirmado no
# teste de dois PCs de 28/10; barricada 68 usa 0x74E0 direto).
#
# Campos pelos acessores Lua do cliente (BC_CLIENT_DATA_*_get, 14142f650… e 141430bb0…):
#   0x11C9 BC_CLIENT_DATA_REQ: U32 iType, U8 bBc_type, U32 iCount, szData[iCount], U8 bBc_to_ob.
#   0x11CA BC_CLIENT_DATA_NTF: U64 ullActor_rid, U32 iType, U32 iCount, szData[iCount].
# O NTF não tem tratador C++ (só os acessores Lua): a marca do scanner no HUD sai do script.
# Tipo 15 (scanner): szData = U64 unit + 3×F32 posição, em little-endian (cópia crua da memória).
SCANNER_ABILITY, SCANNER_COUNT = 37, 38        # ATR_INIT_ABILITY_SCANNER / ATR_SCANNER_LEFT_COUNT
AT_USE_SCANNER = 72
CLIENT_DATA_SCANNER = 15


def decode_client_data(payload):
    if len(payload) < 10:
        raise ValueError('BC_CLIENT_DATA_REQ curto')
    kind, bc_type, count = struct.unpack_from('>IBI', payload)
    if count > 700 or len(payload) != 10 + count:
        raise ValueError('BC_CLIENT_DATA_REQ com iCount inválido')
    return dict(kind=kind, bc_type=bc_type, data=payload[9:9 + count], to_ob=payload[9 + count])


def encode_client_data_ntf(actor, kind, data):
    return struct.pack('>QII', actor, kind, len(data)) + data


def decode_scanner_mark(payload):
    if len(payload) != 8:
        raise ValueError('SCANNER_MARK_REQ espera 8 bytes')
    return struct.unpack('>Q', payload)[0]


def eu_action(payload):
    """0x536 ACTOR_EU_ACTION_REQ: U32 E_EU_AT_* no início (resto ignorado)."""
    return struct.unpack_from('>I', payload)[0] if len(payload) >= 4 else None


def decode_barrier_request(payload):
    if len(payload) != 46:
        raise ValueError('USE_BARRIER_REQ espera 46 bytes')
    x, y, z, _ = struct.unpack_from('>iiiB', payload, 0)
    x2, y2, z2, _ = struct.unpack_from('>iiiB', payload, 13)
    extra, yaw = struct.unpack_from('>If', payload, 26)
    rotation = struct.unpack_from('>3f', payload, 34)
    return dict(position=(x, y, z), point=(x2, y2, z2), extra=extra, yaw=yaw, rotation=rotation)


def encode_obstacle_sync(uid, owner, position, rotation, own, hp=BARRIER_HP, kind=OBSTACLE_BARRIER,
                         config=BARRIER_CONFIG, seconds=BARRIER_SECONDS):
    x, y, z = (int(v) for v in position)
    return (struct.pack('>QQI', uid, owner, config) + struct.pack('>iiiB', x, y, z, 0) + bytes(12)
            + struct.pack('>III', hp, hp, kind) + struct.pack('>I', seconds)
            + struct.pack('>3f', *rotation) + struct.pack('>I', int(own)))


def encode_obstacle_leave(uid, reason=0):
    return struct.pack('>QI', uid, reason)


class GadgetRooms:
    """Obstáculos vivos por sala; somem ao fim do tempo da tabela (BC_LEAVE_SCENE)."""

    def __init__(self):
        self.next_uid, self.obstacles = OBSTACLE_UID_BASE + 1, {}

    def place_barrier(self, room, owner, request, now):
        uid = self.next_uid
        self.next_uid += 1
        self.obstacles[uid] = dict(room=room, owner=owner, expires=now + BARRIER_SECONDS, request=request)
        return uid

    def expired(self, now):
        gone = [(uid, o) for uid, o in self.obstacles.items() if now >= o['expires']]
        for uid, _ in gone:
            del self.obstacles[uid]
        return gone

    def in_room(self, room):
        return [(uid, o) for uid, o in self.obstacles.items() if o['room'] == room]
