"""Явное одиночное поражение; исходные причины и награды не восстановлены."""
from dataclasses import dataclass
import math
import struct


@dataclass
class MatchEndPolicy:
    on_death: bool = False
    timeout_seconds: float | None = None
    ended: bool = False

    def __post_init__(self):
        if type(self.on_death) is not bool:
            raise ValueError('on_death должен быть bool')
        if self.timeout_seconds is not None and (
                type(self.timeout_seconds) not in (int, float)
                or not math.isfinite(self.timeout_seconds)
                or not 1 <= self.timeout_seconds <= 7200):
            raise ValueError('Локальный deadline: 1..7200 секунд')

    @property
    def enabled(self):
        return self.on_death or self.timeout_seconds is not None

    def poll(self, now, world, statistics, fixture, actor_uid, room_uid, display_name,
             already_rescued=False):
        if (self.ended or already_rescued or statistics.rescued or world is None
                or statistics.started_at is None):
            return [], None
        reason = ('death' if self.on_death and world.dead else
                  'timeout' if self.timeout_seconds is not None and
                  now >= statistics.started_at+self.timeout_seconds else None)
        if reason is None:
            return [], None
        # Запоздалый callback не продлевает лимит. Уже учтённая смерть
        # сохраняет свой прежний timestamp. Невалидный fixture не замораживает учёт.
        ended = statistics.started_at+self.timeout_seconds if reason == 'timeout' else now
        snapshot = statistics.snapshot(ended)
        snapshot['rescued'] = 0
        packets = fixture.messages(actor_uid, room_uid, snapshot, display_name)
        # Native140E70E7E: flag!=1 обходит helicopter lookup. Cold174
        # подтвердил No survivors/Stats/lobby без выданного объекта helicopter.
        packets.append((0x6589, struct.pack('>BQ', 0, 0)))
        statistics.finish(ended, rescued=False)
        self.ended = True
        return packets, {'action': 'singleplayer_failure_result', 'cause': reason,
                         'match_statistics': snapshot,
                         'original_result_reason_verified': False}
