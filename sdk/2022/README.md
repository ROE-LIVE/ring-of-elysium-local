# Protocol SDK 2022 — 4 November 2026 / 4 ноября 2026

Reusable source modules from the current restoration: lobby ownership and appearance, base male/female characters, TCP framing, relays, movement, equipment, action packets and spectator synchronization. This is an isolated developer SDK, **not a replacement launcher or a complete multiplayer server**. The existing `play.cmd` remains the historical local demo. No new bot implementation is included.

## Проверка

Python3.11+; команды из корня ring-of-elysium-local:

```sh
python -m pip install -r sdk/2022/requirements.txt
python -B sdk/2022/run_tests.py
```

Тесты не запускают игру и не читают реальные ключи. Протокольные тесты используют синтетический ключ `bytes(range(16))`. Остальные модули используют только стандартную библиотеку. Новые модули специально отделены от прежнего tools/: запуск всего старого демо с частично заменёнными файлами не проверен и здесь не предлагается.

## Что использовать

- tools/base_character_2022.py: ActorHeadCfg, LOGIN_WORLD, редактор030D/030F,703F.
- tools/local_cosmetics_2022.py, local_clothing_2022.py, lobby_rewards_2022.py: демо-владение, сохранение выбора/лиц,54C5/54C9. Каталог содержит ID и метаданные; модели и текстуры нужно получить из своего клиента.
- tools/lobby_actor_uid_2022.py: согласованный UID и сохранённое лицо в LOGIN_WORLD. Подключать к уже существующему lobby stream, не использовать как отдельный сервер.
- server/directory/peer_*.py: формы профиля, движения, экипировки, ADS/reload и наблюдателя. Это codecs/обработчики с определёнными входными структурами, не полный tick-loop.
- tools/tcp_relay_2022.py, lan_tunnel_2022.py, network_fault_2022.py: транспорт и ограниченные опыты с задержкой/разрывом. По умолчанию использовать localhost; перед LAN/public запуском проверить аргументы и маршруты.
- UPSTREAM.json: исходный коммит и SHA256 каждого перенесённого файла. Не содержит игровые EXE или сохранённые лица пользователей.

## Интеграция

Сначала воспроизвести тесты, затем подключать один codec в собственный scene peer. Сохранять разделение: профиль/lease → lobby → общая комната → игровые события. Согласовать один actor UID между LOGIN_WORLD, комнатой и удалённой моделью. Оформление игрока нужно передать при появлении и обновлять при изменениях; один broadcast координат не синхронизирует экипировку/параплан/перезарядку.

Публикуемый SDK не содержит игровой авторизации, handshake captures, игрового лута/ресурсов, HTTP profile directory, полного общего combat-loop, Kubernetes-окружения или новых FSM ботов. Схема интеграции и ограничения: ../../docs/PUBLIC-UPDATE-20261104.md. Правила проекта, лицензии и отказ от гарантий основного репозитория действуют и здесь.
