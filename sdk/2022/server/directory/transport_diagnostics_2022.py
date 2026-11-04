"""Ограниченная числовая диагностика RUDP; без тел пакетов и ключей."""
from collections import deque


class TransportDiagnostics:
    def __init__(self):
        self.recent = deque(maxlen=32)
        self.last_received = None
        self.last_sample = float('-inf')
        self.last_progress = None
        self.last_ack = None

    def receive(self, packet, now):
        self.last_received = now
        self.recent.append(dict(seq=packet.sequence, ack=packet.acknowledgement,
                                flags=packet.flags, window=packet.window,
                                data_length=len(packet.data)))

    def sample(self, sender, receiver, now, *, force=False):
        if sender.ack != self.last_ack:
            self.last_ack = sender.ack
            self.last_progress = now
        if not force and now-self.last_sample < 1:
            return None
        self.last_sample = now
        latest = self.recent[-1] if self.recent else {}
        result = dict(peer_window=latest.get('window'), peer_seq=latest.get('seq'),
                      peer_ack=latest.get('ack'), sender_ack=sender.ack,
                      sender_high=sender.high, pending_packets=len(sender.pending),
                      pending_bytes=sender.bytes, receiver_next=receiver.next,
                      received_idle_seconds=(None if self.last_received is None else
                                             max(0,now-self.last_received)),
                      ack_idle_seconds=max(0,now-self.last_progress))
        if force:
            result['recent_headers'] = list(self.recent)
        return result
