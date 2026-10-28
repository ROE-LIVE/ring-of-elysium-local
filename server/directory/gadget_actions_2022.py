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
