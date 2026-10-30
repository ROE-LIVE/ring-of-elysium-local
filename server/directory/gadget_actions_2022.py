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
#
# O aviso no detectado não vem do 0x1168 (testado: nada aparece), e sim do 0x1166
# ACTOR_MARKED_STATUS_NTF (U8 bStatus): tratador 1412e7c50 → EuPlayerDetectedSystem liga/desliga o
# bit 2 e, na transição, chama OnPlayerBeDetected(bStatus) no Lua + DetectedFx. O bit só desliga
# com bStatus 0, então o servidor manda 1 na marca e 0 ao fim de mMarkCloseTime (11 s).
SCANNER_ABILITY, SCANNER_COUNT = 37, 38        # ATR_INIT_ABILITY_SCANNER / ATR_SCANNER_LEFT_COUNT
AT_USE_SCANNER = 72
CLIENT_DATA_SCANNER = 15
SCANNER_MARK_SECONDS = 11


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
                         config=BARRIER_CONFIG, seconds=BARRIER_SECONDS, bait=b''):
    """No tipo 2 (isca) o bloco `bait` (encode_bait_block) vai logo depois do tipo (140ca8150)."""
    x, y, z = (int(v) for v in position)
    return (struct.pack('>QQI', uid, owner, config) + struct.pack('>iiiB', x, y, z, 0) + bytes(12)
            + struct.pack('>III', hp, hp, kind) + bait + struct.pack('>I', seconds)
            + struct.pack('>3f', *rotation) + struct.pack('>I', int(own)))


# Bloco da isca no 0x74D0 tipo 2 (140ca7f80, versão 0x5C): ficha do ator (140c29710), percurso
# (140ca7df0, o mesmo do USE_BAIT) e U32 n<=50 de pares U32 (140c27f60). A ficha, campo a campo:
#   U32 tamanho + nome com NUL (<=0x80); 140bd0450: 3×U32, U64, 3×U32, F32, 3×U32 (48 B);
#   140bd0180: 30× {U32, U64, U32, U32, U32 n<=8 (140bceab0), U32, U32} + U32;
#   140c25cf0: 11×U32, listas U32 n + n×U32 (<=10, <=5, <=10, <=80, <=10), U32, U32;
#   140be86f0: aparência 5×I32 (a mesma do BE7 +1240); U8; 140be91a0: U32 n<=400 itens de 0x3E.
# Esses três últimos são o mesmo trecho do fim do ENTER_ROOM (aparência + flag + acessórios,
# room_cosmetics_2022). Só com a aparência o holograma saiu sem roupa (sessão 20261030T191045);
# agora vai o trecho inteiro do dono. O resto da ficha segue zerado, com listas vazias.
OBSTACLE_BAIT = 2
BAIT_CONFIG, BAIT_HP, BAIT_SECONDS = 201, 1000, 30


def encode_bait_block(name, appearance_tail, path):
    raw = name.encode('utf-8')[:0x7f] + b'\0'
    card = (struct.pack('>I', len(raw)) + raw + bytes(48)
            + bytes(32) * 30 + bytes(4)
            + bytes(44) + bytes(4) * 5 + bytes(8)
            + (appearance_tail or bytes(21) + struct.pack('>I', 0)))
    route = struct.pack('>I', len(path)) + b''.join(struct.pack('>iii4f', *p) for p in path)
    return card + route + struct.pack('>I', 0)


def encode_obstacle_leave(uid, reason=0):
    return struct.pack('>QI', uid, reason)


class GadgetRooms:
    """Obstáculos vivos por sala; somem ao fim do tempo da tabela (BC_LEAVE_SCENE)."""

    def __init__(self):
        self.next_uid, self.obstacles = OBSTACLE_UID_BASE + 1, {}

    def place_barrier(self, room, owner, request, now, seconds=BARRIER_SECONDS):
        uid = self.next_uid
        self.next_uid += 1
        self.obstacles[uid] = dict(room=room, owner=owner, expires=now + seconds, request=request)
        return uid

    def expired(self, now):
        gone = [(uid, o) for uid, o in self.obstacles.items() if now >= o['expires']]
        for uid, _ in gone:
            del self.obstacles[uid]
        return gone

    def in_room(self, room):
        return [(uid, o) for uid, o in self.obstacles.items() if o['room'] == room]


# Holograma (isca, tática 3, item 70021): nomes/IDs pela tabela de registro do cliente (140bbe736…):
#   0x74D3 OBSTACLE_MSGID_USE_BAIT, 0x74D4 USE_BAIT_RSP (I32, decodificador 140bcf170 como 0x74E1),
#   0x74D5 BC_BAIT_ATTACK, 0x74D6 SHOW_BAIT_ATTACKER, 0x74D7/0x74D8 ENTER/LEAVE_BAIT,
#   0x74D9/0x74DA BC_ENTER/BC_LEAVE_BAIT (todos U64; 0x74D6 U64 + POS13).
# USE_BAIT (decodificador 140ca8430): POS13, 4×U32 (140bcd9d0), percurso (140ca7df0: U32 n<=128,
#   n×{3×U32, 4×U32}), U32, 3×U32 (140bcd900). EuVehicleTable_bait: nId 201 HOLOBAIT, nHp 1000, nTime 30 s.
# No 0x74D0 o tipo 2 traz um bloco da isca (140ca7f80: ficha do ator 140c29710 + percurso + 140c27f60);
# ainda não montamos esse bloco.
BAIT_ABILITY, BAIT_COUNT = 29, 30              # ATR_INIT_ABILITY_BAIT / ATR_BAIT_LEFT_COUNT
BAIT_CONFIG, BAIT_HP, BAIT_SECONDS = 201, 1000, 30


def decode_bait_request(payload):
    if len(payload) < 49 or (len(payload) - 49) % 28:
        raise ValueError('USE_BAIT espera 49 + 28n bytes')
    x, y, z, _ = struct.unpack_from('>iiiB', payload, 0)
    rotation = struct.unpack_from('>4f', payload, 13)
    count = struct.unpack_from('>i', payload, 29)[0]
    if not 0 <= count <= 128 or len(payload) != 49 + 28 * count:
        raise ValueError('USE_BAIT com percurso inválido')
    path = [struct.unpack_from('>iii4f', payload, 33 + 28 * i) for i in range(count)]
    extra = struct.unpack_from('>I', payload, 33 + 28 * count)[0]
    vector = struct.unpack_from('>3f', payload, 37 + 28 * count)
    return dict(position=(x, y, z), rotation=rotation, path=path, extra=extra, vector=vector)


# Capa (tática 8, item 70026): 0x536 com E_EU_AT_USE_STEALTH 71 / QUIT_STEALTH 73 (enum do cliente);
# estado E_EU_ST_IN_STEALTH 83 (EuStatusTable m_nDescBuff 18). EuStealthCloakTable: energia mínima 6,
# abrir 1,5 s, fechar 1,2 s — a energia (gasto/recarga) ainda não é simulada pelo servidor.
AT_USE_STEALTH, AT_QUIT_STEALTH, ST_IN_STEALTH = 71, 73, 83

# Gancho (mochila 200903, ATR_MOVE_GRAPPLE_LEFT_COUNT 16): o cliente pede 0x3B SCENE_MSGID_GRAPPLE e
# fica parado na pose de lançamento até o 0x3C BC_GRAPPLE com o próprio UID (sessão 20261030T184624).
# Campos pelos decodificadores do despachante de cena (tabela de saltos em 140c5b23b, IDs 10..0x4F):
#   0x3B (140c58000): U32, U8, U32, 3×F32 direção, 3×I16, POS13 jogador, U8 + U64, 3×F32 início,
#        3×F32 ponto de fixação, 3×I16, U8, 5×U16; com versão >= 99 mais 38 bytes (140c57d80).
#   0x3C (140c585d0): U64 ator, U32, U8, U32, 3×I16, POS13, POS13, 3×I16, U8, 5×U16; com versão >= 99
#        mais POS13 + U64. O servidor manda versão = código (0x3C < 99), então o bloco final não vai.
# A correspondência campo a campo do 0x3B para o 0x3C (mesma ordem, POS13 do ponto de fixação a partir
# dos F32) é hipótese nossa.
# O que solta o personagem é o 0x3A RESOLVE_MOVE (decodificador 140c59e10: U32, U16, POS13, U32, U8,
# U8 + U64, U8, U64) com o número do gancho (1º U32 do 0x3B) e o ponto de fixação: só com o 0x3C ele
# ficava parado na pose de lançamento até um tempo limite de ~3 min. Confirmado ao vivo (sessão
# 20261030T193140, seis ganchos seguidos); a sequência do MOVE_SPEC (U16) pode ir zerada.
GRAPPLE_REQUEST_SIZE = 90


def encode_grapple_resolve(request):
    ax, ay, az = (int(round(v)) for v in request['anchor'])
    return (struct.pack('>IH', request['a'], 0) + struct.pack('>iiiB', ax, ay, az, 0)
            + struct.pack('>IB', 0, 0) + struct.pack('>BQ', 0, 0) + struct.pack('>BQ', 0, 0))


def decode_grapple_request(payload):
    if len(payload) < GRAPPLE_REQUEST_SIZE:
        raise ValueError('GRAPPLE espera pelo menos 90 bytes')
    o = 0
    fields = {}
    for name, fmt in (('a', 'I'), ('b', 'B'), ('c', 'I'), ('direction', '3f'), ('rotation', '3h'),
                      ('position', '3iB'), ('target_flag', 'B'), ('target', 'Q'), ('start', '3f'),
                      ('anchor', '3f'), ('normal', '3h'), ('d', 'B'), ('tail', '5H')):
        value = struct.unpack_from('>' + fmt, payload, o)
        fields[name] = value if len(value) > 1 else value[0]
        o += struct.calcsize('>' + fmt)
    return fields


def encode_grapple_bc(actor, request):
    x, y, z, flag = request['position']
    ax, ay, az = (int(round(v)) for v in request['anchor'])
    return (struct.pack('>QIBI', actor, request['a'], request['b'], request['c'])
            + struct.pack('>3h', *request['rotation'])
            + struct.pack('>iiiB', x, y, z, flag)
            + struct.pack('>iiiB', ax, ay, az, 0)
            + struct.pack('>3hB5H', *request['normal'], request['d'], *request['tail']))


# Medgun em si mesmo: 0x117B HEAL_GUN_ONESELF_REQ (iBullet_id) → 0x117C HEAL_GUN_ONESELF_RSP (iError).
# Buff 4000 "奶枪回血": a cada 500 ms PowerSet Life +20. A duração do buff não foi achada: 10 pulsos (5 s,
# +200) é hipótese nossa.
HEAL_GUN_TICK, HEAL_GUN_AMOUNT, HEAL_GUN_PULSES = 0.5, 20, 10
# Carga da Medgun: munição BULLET_EXTRA2 = ATR_HEAL_GUN_LEFT_COUNT 22 (item 70024 nUseNum 1); cada disparo
# ou autocura gasta 1; o buff 3002 "奶枪冷却" devolve 1 a cada 300 s. Com a Medgun na mão o encaixe é o 9.
HEAL_GUN_ABILITY, HEAL_GUN_COUNT, HEAL_GUN_RECHARGE, MEDGUN_HAND_SLOT = 21, 22, 300.0, 9
