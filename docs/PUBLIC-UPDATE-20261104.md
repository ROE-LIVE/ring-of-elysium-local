# Public restoration update — 4 November 2026

## English

The active development environment has progressed beyond the October local demo: two Windows clients have joined the same scene, and the restoration now separates profile/lobby, scene simulation, client bootstrap and optional bot control. These are reconstructed services; the original authoritative game server has not been recovered.

This publication contains **reusable source modules and tests**, an integration map, a current evidence summary and contributor tasks. The historical `play.cmd` stays unchanged. It does not become the current multiplayer launcher simply by pulling this update. New bot work remains unpublished at the owner's request; private infrastructure, user sessions, credentials and game assets are excluded.

Source SDK: [ring-of-elysium-local/sdk/2022](https://github.com/ROE-LIVE/ring-of-elysium-local/tree/main/sdk/2022). Research and tasks: [ring-of-elysium-research](https://github.com/ROE-LIVE/ring-of-elysium-research).

## Русский: что можно взять

Основной билд: **2022-0.2.989.0 x64, корневой Europa_Client.exe**, SHA256 `2dca9b1e122e21363e14eeeb2372598c773205a907ed8d2b2d54a7229ad6ba18`. Адреса ниже — VA при базе0x140000000; они не относятся к XVersion, V99 или x86 Steam2018.

SDK изолирован в sdk/2022 и содержит текущие codecs лобби/внешности, сохранение профиля, room appearance, профиль соседа, движение/экипировку/ADS/reload, наблюдателя, TCP framing/relay и UDP-over-TCP туннель стенда. UPSTREAM.json указывает исходный коммит ROE_SERVER571dca4 и SHA каждого исходного файла. Сырых AUTH/CK-пакетов в SDK нет; тестовые ключи синтетические. config/cosmetics.json — ID/метаданные, не игровые модели.

```sh
# Из ring-of-elysium-local; без запуска игры и без реальных ключей
python -m pip install -r sdk/2022/requirements.txt
python -B sdk/2022/run_tests.py
```

## Архитектура рабочего стенда и точки интеграции

```text
Windows bootstrap/helper → профиль и lease → lobby stream → scene transport
                                                   ↓
                          сервер общей комнаты → события каждому участнику
                          профиль / лут / HP / зоны / транспорт / эвакуация
```

Клиент загружает ресурсы, рисует мир, исполняет локальное движение/физику и отправляет события. Наш helper адаптирует запуск и сетевой путь; одного изменения IP в штатном EXE для этого стенда недостаточно. Сервер сопоставляет actor UID и комнату, хранит общее состояние и формирует ответы/уведомления. Второму игроку нужны профиль, оружие, экипировка, транспортная привязка и действия, а не только координаты.

Первым подключать один изолированный codec, затем проверять: совпадение UID → появление модели → движение/остановка → ADS/reload → спецснаряжение → посадка/выход → смерть/наблюдатель → новый матч. Общая FSM/мультиплеерный orchestrator текущего стенда в этот SDK не входят. Это реальный исходный материал для собственной реализации, а не обещание полного публичного кластера.

## Что подтверждено и чем

| Область | Наблюдение | Уровень доказательства / граница |
|---|---|---|
| Общая сцена | Два Windows-клиента подключаются и взаимодействуют; пользователь повторял матчи | Пользовательские проверки 02–03.11, не новый публичный native-прогон |
| Движение | Разделены формы профиля/движения/экипировки/действий/спецдвижения | Публикуемые codecs и unit-тесты; плавность всех анимаций не гарантируется |
| Лобби | Cold-выбор костюмов без обхода через Accessories; базовые мужчина/женщина, восемь категорий одежды и редактор лица | Свой Proton-контроль04.11; новый парный Windows-повтор внешности ожидается |
| Каталог | 450 gun skins,361 character variants,197 charms,189 clothing IDs; дополнительные reward-группы | Код/границы контейнеров и часть native-выборов; каждый ресурс не просмотрен |
| Транспорт | TCP relay, framing и восстановление туннеля исследованы отдельно от логики матча | Передача байтов и повторное соединение не доказывают корректность повторного входа в произвольной фазе |
| Интернет | Внешний маршрут через TCP-прокси требует согласованного соответствия портов | Прогон04.11 дал Connection Timeout до игрового обмена; причина маршрута ещё не доказана |
| Лут | Публичный пакет7155prefab-точек и8313legacy-записей остаётся доступен | Наборы не объединять; исторические RNG/binding не объявлены восстановленными |

Имеющиеся приватные native-контроли лобби: native-baseline, native-candidate, native-male-media, native-female-restore, native-home-male, native-home-female из исследования20261103-lobby-wardrobe. Сами скриншоты/пакеты/сохранённые лица здесь не публикуются. UPSTREAM и тесты воспроизводят код и граничные проверки, но не заменяют отсутствующие raw-доказательства.

## Первичные адреса и схемы

| Цепочка | Адреса / форма | Публичный код |
|---|---|---|
| ActorHeadCfg | 140BD0450,140BD09A0;140+40*n,n≤30;gender0/1 | tools/base_character_2022.py |
| UserCfg / appearance | 140BDBC30;703F/type3,kind1=created head,kind2=costume | base_character_2022.py,local_cosmetics_2022.py |
| Инициализация cache | 1412E0770;call1412E082B→140D9F130;unknown descriptor140DA0BA4..140DA0C45 | LocalCosmetics.cache_primer;73B3/descriptor0 |
| Reward selection | 141051AA0,jump table141051B30;54C5/54C9 | tools/lobby_rewards_2022.py |
| Удалённое лицо BE7 | 140C2A730→140C2A130→140C29C80+140BD09A0 | server/directory/peer_profile_2022.py |
| Инвентарь | 140BCF790,140BCF510,140BCEC10,140BCF2F0,140C28460,140BD4D60,140C4AE00 | server/directory/inventory_codec_2022.py |

Первичные схемы дополнительно сверялись с read-only ROE.Nexus: ActorHeadCfg/ActorModule/UserCfg, CosmeticsSync/reward/media. Это источник сопоставления, не доказательство полного восстановления сервера. Initial face строится из DefaultMakeupConfigTable и нейтральных морфов; после Save сохраняется реальный ActorHeadCfg клиента.

DefaultMakeupConfigTable проверена по своему TableBin.sfc: ordinal2955,key17224730823421754044,block offset29048734,SHA256 `82f8e86f4af7fe0131cc5c222e6b8fe9f11b30a4bf5415910ace0b8c104a1bfd`. Таблица/архив не включены; для дополнительной проверки нужен собственный клиент этого билда.

Дополнение к историческому реестру сигналов: [SIGNALS-SUPPLEMENT-20261104.csv](SIGNALS-SUPPLEMENT-20261104.csv). Названия исследовательские; неизвестные поля не получают придуманной семантики.

## Отрицательные результаты и ограничения

Комбинация согласованного UID, kind1 и cache-primer устранила cold Appearance в native-контроле; вклад каждого изменения отдельно не изолирован. Подмена LOGIN_WORLD пустым списком персонажей вызывала падение1412AE8A3 и исключена. Переключение пола пока реализовано до запуска, не родными кнопками внутри редактора. Snowboard UI показывает только default; выдача дополнительных ID этого не исправила. Лобби-выбор оформления не доказывает применение ко всем сущностям матча. Кодек перезарядки не гарантирует слышимость/анимацию у каждого пассажира во всех состояниях.

WireGuard/Egress Gateway обсуждались как следующий сетевой опыт, **не развёрнуты и не проверены этим обновлением**. Namespace сам не задаёт маршрут; вход и обратный путь требуют отдельной согласованной настройки.

## Вклад сообщества

Новые задачи — PUBLIC-TASKS-20261104.csv: короткие действия, ожидаемый результат, первичный источник и поле результата. Старый mechanics-2022.csv остаётся историческим планом; старые проценты не являются актуальной оценкой всего проекта. Для сравнения билдов использовать docs/BUILDS.md исследовательского репозитория. V99 имеет собственные адреса/структуры; наличие host/debug-строк не доказывает работающий автономный сервер.

Для полезного отчёта нужны: билд/SHA, коммит SDK, один сценарий, что ожидалось/произошло, последовательность событий с временем и минимальный обезличенный пример. Не прикладывать реальные ключи, полный дамп/клиент или исходные голосовые/видеозаписи. Discord: https://discord.gg/pD2Bj5kAxk.
