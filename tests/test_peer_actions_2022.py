"""Пересылка поворота/прицела/выстрела/анимации: размеры SYNC по декодерам клиента."""
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server/directory'))
from peer_actions_2022 import HIP_FIRE_HOLD, event_status, hip_fire_release, relay_body, relay_packets
from game_endpoint_probe_2022 import Endpoint


class PeerActionTests(unittest.TestCase):
    def test_sync_sizes_follow_client_decoders(self):
        uid = 0x2040000100002
        # Взгляд вдоль -X (замер0x2F): yaw = 0 или 65535 (±180°), pitch по середине.
        code, body = relay_body(0x2f, struct.pack('>3f', -1, 0, 0), uid)
        self.assertEqual((code, len(body), body[:8]), (0x30, 20, struct.pack('>Q', uid)))
        self.assertEqual(struct.unpack_from('>HH', body, 8), (65535, 32768))
        code, body = relay_body(0x2f, struct.pack('>3f', 0, 1, 0), uid)
        self.assertEqual(struct.unpack_from('>H', body, 8)[0], 49151)
        memo = {}
        fire = struct.pack('>6fIBIIfII', 1, 2, 3, 4, 5, 6, 7, 0, 9, 10, 11.0, 12, 13)
        code, body = relay_body(0x11da, fire, uid, memo)
        self.assertEqual((code, len(body)), (0x11d4, 41))
        self.assertEqual(struct.unpack('>Q6fBII', body), (uid, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 0, 9, 7))
        code, body = relay_body(0x11d5, struct.pack('>3f', 0.5, 0, 0), uid, memo)
        self.assertEqual(struct.unpack('>Q3fII', body), (uid, 0.5, 0.0, 0.0, 9, 7))
        # 0x11D8: o decodificador 140c3f310 lê U8, U64 e dois U32 (17 bytes); com 9 o cliente descarta.
        code, body = relay_body(0x11d7, b'\x05', uid, memo)
        self.assertEqual((code, body), (0x11d8, struct.pack('>BQII', 5, uid, 9, 7)))
        (code, body), = relay_packets(0x11d7, b'\x00', uid, memo, tick=1234)
        self.assertEqual((code, len(body)), (0x11d8, 17))
        self.assertEqual(struct.unpack('>BQII', body), (0, uid, 1234, 7))
        self.assertIsNone(relay_body(0x11d5, bytes(11), uid))
        self.assertIsNone(relay_body(0x2f, struct.pack('>3f', float('nan'), 0, 0), uid))

    def test_hip_fire_raises_and_lowers_remote_weapon(self):
        # Sem mira (sessão 20261029T012734) só a pose do tiro mirando aparecia: sem 0x536,
        # o servidor manda AIMING antes do 0x11D8 e STOP_AIM depois de HIP_FIRE_HOLD sem tiros.
        uid, memo = 0xA, {}
        motion = bytes(1)
        sent = relay_packets(0x11d7, motion, uid, memo, tick=1, now=10.0)
        self.assertEqual([c for c, _ in sent], [0x2b, 0x11d8])
        self.assertEqual(struct.unpack('>QI', sent[0][1]), (uid, 24))
        self.assertEqual([c for c, _ in relay_packets(0x11d7, motion, uid, memo, now=10.5)], [0x11d8])
        self.assertEqual(hip_fire_release(uid, memo, 10.5+HIP_FIRE_HOLD-0.01), [])
        (code, body), = hip_fire_release(uid, memo, 10.5+HIP_FIRE_HOLD)
        self.assertEqual((code, struct.unpack('>QI', body)), (0x2b, (uid, 40)))
        self.assertEqual(hip_fire_release(uid, memo, 20.0), [])
        # Mirando, a arma já está erguida pelo 0x536: só o 0x11D8, sem STOP_AIM adiantado.
        relay_packets(0x536, struct.pack('>I', 16), uid, memo)
        self.assertEqual([c for c, _ in relay_packets(0x11d7, motion, uid, memo, now=30.0)], [0x11d8])
        self.assertEqual(hip_fire_release(uid, memo, 40.0), [])
        relay_packets(0x536, struct.pack('>I', 17), uid, memo)
        self.assertEqual([c for c, _ in relay_packets(0x11d7, motion, uid, memo, now=50.0)], [0x2b, 0x11d8])
        # Mirar durante a espera cancela o STOP_AIM pendente.
        relay_packets(0x536, struct.pack('>I', 35), uid, memo)
        self.assertEqual(hip_fire_release(uid, memo, 60.0), [])

    def test_ik_request_is_not_used_as_turn_pitch(self):
        # 0x11D5 é desvio de animação (parâmetro 0x37), não ângulo vertical: só vira 0x11D6.
        uid, memo = 0xA, {}
        relay_packets(0x2f, struct.pack('>3f', 1, 0, 0), uid, memo)
        self.assertEqual([c for c, _ in relay_packets(0x11d5, struct.pack('>3f', 30, 0, 0), uid, memo)], [0x11d6])
        (code, body), = relay_packets(0x2f, struct.pack('>3f', 0.8, 0, 0.6), uid, memo)
        self.assertEqual(struct.unpack_from('>HH', body, 8), (32768, round(1.6*32767.5)))
        self.assertEqual(relay_packets(0x2f, bytes(12), uid, memo), [])
        ik = relay_packets(0x11d5, struct.pack('>3f', 5, 0, 0), uid, memo, tick=1234)[0][1]
        self.assertEqual(struct.unpack_from('>I', ik, 20)[0], 1234)

    def test_scene_broadcast_is_relayed_with_remote_uid(self):
        actor, avatar = 0x515bb1e1dd242c, 0x2040000100001
        blob = struct.pack('>IQ', 7, actor) + bytes(8)
        code, body = relay_body(0x11ec, struct.pack('>i', len(blob)) + blob, avatar, {'actor': actor})
        self.assertEqual(code, 0x11ec)
        self.assertEqual(body, struct.pack('>iIQ', len(blob), 7, avatar) + bytes(8))
        self.assertIsNone(relay_body(0x11ec, struct.pack('>i', 5) + bytes(4), avatar, {}))
        # Amostra real (SET_HAND): UID little-endian dentro do bloco.
        real = bytes.fromhex('000000140300000004000000') + struct.pack('<QI', actor, 1)
        code, body = relay_body(0x11ec, real, avatar, {'actor': actor})
        self.assertEqual(body[12:20], struct.pack('<Q', avatar))
        # SCENE_AROUND_BROADCAST 0x1159 (snowboard): mesmo envelope e troca de UID, mesmo código.
        code, body = relay_body(0x1159, real, avatar, {'actor': actor})
        self.assertEqual((code, body[12:20]), (0x1159, struct.pack('<Q', avatar)))
        # BMX (amostras reais do PC2): subtipos 3 e 2 (este vem com o pulo 50) passam com o UID trocado.
        bike = '000000210c000000110000007cc7598eb15b5100020000007f21000015000000'
        charlie = 0x515bb18e59c77c
        for tail in ('0300930100', '0201000000'):
            code, body = relay_body(0x1159, bytes.fromhex(bike+tail), avatar, {'actor': charlie})
            self.assertEqual((code, body[12:20]), (0x1159, struct.pack('<Q', avatar)))
        # STOP_USE_ITEM (20) não vira estado para os outros; AIM/DIS_AIM/SCOPE_AIM viram.
        self.assertEqual(relay_packets(0x536, struct.pack('>I', 20), avatar, {}), [])
        for action, status in ((16, 24), (17, 40), (35, 39)):
            self.assertEqual(relay_packets(0x536, struct.pack('>I', action), avatar, {}),
                             [(0x2b, struct.pack('>QI', avatar, status))])

    def test_reload_and_medical_events_map_to_status(self):
        memo = {}
        self.assertIsNone(event_status({'action': 'reload'}, memo))
        self.assertEqual(event_status({'action': 'reload_started'}, memo), 41)
        self.assertEqual(event_status({'action': 'reload'}, memo), 27)
        self.assertIsNone(event_status({'action': 'reload'}, memo))
        self.assertEqual([event_status({'action': a}, memo) for a in
                          ('medical_started', 'medical_finished', 'medical_cancelled', 'hand')], [22, 27, 27, None])

    def test_endpoint_status_goes_only_to_other_room_members(self):
        sent = []
        a, b = dict(room_uid=1, actor_uid=10), dict(room_uid=1, actor_uid=11)
        fake = SimpleNamespace(
            peer_avatars=SimpleNamespace(members={(1, 10): dict(avatar=0xA, state=a), (1, 11): dict(avatar=0xB, state=b)}),
            emit_peer_avatars=lambda outputs, events: sent.extend(outputs),
            capture=SimpleNamespace(record=lambda *x, **y: None))
        Endpoint.relay_peer_status(fake, a, [{'action': 'reload_started', 'seconds': 2}, {'action': 'hand'}])
        self.assertEqual(sent, [(b, [(0x2b, struct.pack('>QI', 0xA, 41))])])

    def test_medical_start_notifies_item_use(self):
        from weapon_probe_2022 import MEDICAL_SLOTS
        definition, slot = next(iter(MEDICAL_SLOTS.items()))
        code, body = relay_body(0x3e80, struct.pack('>BBHBIB', 3, 2, slot, 0, 0, 1), 0xA)
        self.assertEqual((code, body), (0xbee, struct.pack('>QI', 0xA, definition)))
        self.assertIsNone(relay_body(0x3e80, struct.pack('>BBHBIB', 1, 2, slot, 0, 0, 1), 0xA))

    def test_endpoint_relays_only_to_other_room_members(self):
        sent = []
        a, b, c = dict(room_uid=1, actor_uid=10), dict(room_uid=1, actor_uid=11), dict(room_uid=2, actor_uid=12)
        fake = SimpleNamespace(
            peer_avatars=SimpleNamespace(members={(1, 10): dict(avatar=0xA, state=a), (1, 11): dict(avatar=0xB, state=b),
                                                  (2, 12): dict(avatar=0xC, state=c)}),
            emit_peer_avatars=lambda outputs, events: sent.extend(outputs), started=0,
            capture=SimpleNamespace(record=lambda *x, **y: None))
        Endpoint.relay_peer_action(fake, a, 0x2f, struct.pack('>3f', 1, 0, 0))
        self.assertEqual(len(sent), 1)
        self.assertIs(sent[0][0], b)
        self.assertEqual(sent[0][1][0][0], 0x30)
        self.assertEqual(struct.unpack_from('>Q', sent[0][1][0][1])[0], 0xA)
        a['world'] = SimpleNamespace(dead=True)
        Endpoint.relay_peer_action(fake, a, 0x2f, struct.pack('>3f', 0, 1, 0))
        self.assertEqual(len(sent), 1)


if __name__ == '__main__':
    unittest.main()
