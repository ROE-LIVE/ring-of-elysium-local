"""Локальный конечный опыт над TCP-мостом; системную сеть/брандмауэр не меняет."""
import argparse
import asyncio
import json
from pathlib import Path
import time
import uuid


class NetworkFault:
    def __init__(self, control_file, routes, *, clock=time.time, emit=None):
        self.path = Path(control_file)
        self.status_path = self.path.with_suffix('.status.json')
        self.routes = routes
        self.clock = clock
        self.emit = emit or (lambda event: print(json.dumps(event), flush=True))
        self.session = uuid.uuid4().hex
        self.seen = set()
        self.action = 'reset'
        self.channel = 'game'
        self.until = 0
        self.delay = 0
        self.connections = {}

    def status(self):
        return dict(session=self.session, updated=self.clock(), action=self.action,
                    channel=self.channel, until=self.until, delay_ms=round(self.delay*1000))

    def publish(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.status_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.status()), encoding='utf-8')
        temporary.replace(self.status_path)

    def applies(self, target):
        selected = {self.routes[-1][1]} if self.channel == 'game' else {t for _, t in self.routes}
        return self.clock() < self.until and target in selected

    def blocked(self, target):
        return self.action == 'cut' and self.applies(target)

    async def before_write(self, target):
        # Задержка на порцию TCP в каждом направлении, а не эмуляция IP-пакетов.
        if self.action == 'delay' and self.applies(target):
            delay = min(self.delay, max(0, self.until-self.clock()))
            await asyncio.sleep(delay)
        if self.blocked(target):
            raise ConnectionResetError('Локальный тест разрыва канала')

    def apply(self, request):
        if not isinstance(request, dict) or set(request) != {'session','id','created','action','channel','seconds','delay_ms'}:
            raise ValueError('Неверная схема опыта')
        now = self.clock()
        if request['session'] != self.session:
            raise ValueError('Запрос относится к другому запуску')
        identifier = request['id']
        if not isinstance(identifier,str) or len(identifier) != 32:
            raise ValueError('Неверный ID опыта')
        if identifier in self.seen:
            return False
        if type(request['created']) not in (int,float) or not 0 <= now-request['created'] <= 10:
            raise ValueError('Просроченный запрос')
        action, channel = request['action'], request['channel']
        if action not in ('cut','delay','reset') or channel not in ('game','all'):
            raise ValueError('Неизвестное действие/канал')
        seconds, delay = request['seconds'], request['delay_ms']
        if type(seconds) not in (int,float) or not 0 < seconds <= 30:
            raise ValueError('Длительность: больше0 и не более30секунд')
        if type(delay) is not int or not 0 <= delay <= 1000:
            raise ValueError('Задержка:0..1000мс')
        if len(self.seen) >= 256:
            raise ValueError('Лимит256 опытов в одном запуске')
        self.seen.add(identifier)
        self.action, self.channel = action, channel
        self.until = now+seconds if action != 'reset' else 0
        self.delay = delay/1000
        if action == 'cut':
            for writer, target in list(self.connections.items()):
                if self.applies(target):
                    writer.transport.abort()
        self.emit(dict(kind='network_test_applied', id=identifier, action=action,
                       channel=channel, seconds=seconds, delay_ms=delay, timestamp=now))
        self.publish()
        return True

    async def monitor(self):
        self.publish()
        previous = None
        last_publish = self.clock()
        try:
            while True:
                try:
                    if self.path.is_file() and self.path.stat().st_size <= 4096:
                        raw = self.path.read_bytes()
                        if raw != previous:
                            previous = raw
                            try:
                                self.apply(json.loads(raw))
                            except (ValueError,TypeError):
                                self.emit(dict(kind='network_test_rejected',timestamp=self.clock()))
                    if self.clock()-last_publish >= 1:
                        self.publish()
                        last_publish = self.clock()
                except OSError:
                    # Отказ диагностического файла не рвёт игровой канал.
                    pass
                await asyncio.sleep(.05)
        finally:
            self.status_path.unlink(missing_ok=True)


def submit(path, action, seconds, delay_ms, channel):
    path = Path(path)
    status = json.loads(path.with_suffix('.status.json').read_text(encoding='utf-8'))
    now = time.time()
    if not 0 <= now-status['updated'] <= 5:
        raise ValueError('Нет активного моста: запустите игру через connect-game.cmd')
    request = dict(session=status['session'],id=uuid.uuid4().hex,created=now,
                   action=action,channel=channel,seconds=seconds,delay_ms=delay_ms)
    # Та же валидация до записи; локальная проверка без соединений.
    check = NetworkFault(path, [], emit=lambda event: None)
    check.session = status['session']
    check.publish = lambda: None
    check.apply(request)
    temporary = path.with_suffix('.request.tmp')
    temporary.write_text(json.dumps(request), encoding='utf-8')
    temporary.replace(path)
    return request['id']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('cut','delay','reset','status'))
    parser.add_argument('--seconds',type=float,default=3)
    parser.add_argument('--delay-ms',type=int,default=100)
    parser.add_argument('--channel',choices=('game','all'),default='game')
    parser.add_argument('--control-file',type=Path,default=Path(__file__).resolve().parents[1]/'runtime/network-test.json')
    args = parser.parse_args()
    try:
        if args.action == 'status':
            print(args.control_file.with_suffix('.status.json').read_text(encoding='utf-8'))
        else:
            identifier = submit(args.control_file,args.action,args.seconds,args.delay_ms,args.channel)
            print('Опыт отправлен: '+identifier+'. Применение проверьте в lan-relay.log: network_test_applied.')
    except (OSError,ValueError,KeyError) as error:
        parser.exit(1,str(error)+'\n')


if __name__ == '__main__':
    main()
