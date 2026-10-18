# Ring of Elysium Local — experimental winter session (2022)

[English](#english) | [Русский](#russian) · [Discord](https://discord.gg/pD2Bj5kAxk)

<a id="english"></a>

## English

### Research follow-up — 18 October 2026

Optional terrain LOS now uses an extracted Iceland heightfield. Proton verified open hits, reconnects, two kills, evacuation and a fresh Training session. This option requires your own extracted PXBIN and is disabled in the standard launcher; it does not provide complete map collision or original damage rules. The intermittent inventory image delay was not reproduced or fixed. Existing Windows W19 tests remain current. [Technical follow-up](docs/SESSION-RESULT-20261018-PM.md).

### Update — 18 October 2026

`-PracticeTargets 10` enables ten passive targets with separate health, armor and death bags. Proton verified two genuine gun kills and separate loot pickups; a second control verified ten administrative deaths, reconnects and evacuation without adding fake gun kills. NPC loot no longer inherits the player's starter ammunition or bandages. The full-magazine capacity fix has passed Proton tests; Windows validation of this revision is pending.

```powershell
git pull --ff-only
.\play.cmd -Client "G:\REsearch\Ring of Elysium-2022" -PracticeTargets 10 -LiveControl
```

Use Training and keep the default spawn cell for this fixed practice layout. The launcher already supplies the smoke loot catalog, armored target and cycle settings; do not repeat those options. Use [WINDOWS-TESTS-W19.csv](WINDOWS-TESTS-W19.csv), then `export-report.cmd`. Targets are passive; this does not restore original AI. [Technical results](docs/SESSION-RESULT-20261018.md).

### Demo use and disclaimer

- **This is an experimental demo intended only for personal home use and research.** It is not an official ROE service or a production-ready game server.
- You install, configure, run, and experiment with the project **entirely at your own risk**. You are responsible for your actions and for checking whether the project is suitable for your environment.
- The code, tools, and research materials are provided **as is, without warranties** of functionality, safety, reliability, or suitability for any particular purpose.
- **To the maximum extent permitted by applicable law, the repository owner, authors, maintainers, and contributors accept no liability** for damage, data loss, malfunctions, changes to system or network settings, or other consequences arising from use of, or inability to use, this project.

This notice does not exclude liability that cannot lawfully be excluded, and it does not change the licenses of third-party components.

Run the current restoration on Windows 11 x64. The repository includes the lobby emulator, Python scene peer, and launcher. This is an unofficial preservation project that reconstructs a game session using external services. The original server has not been recovered. The main map is **Iceland, map 16010**.

## Quick start

1. Provide a **complete 2022 client with its resources**, not just an EXE. The supported executable is the root `Europa_Client.exe`, SHA-256 `2dca9b1e122e21363e14eeeb2372598c773205a907ed8d2b2d54a7229ad6ba18`. Other builds are incompatible.
2. The fixed local handshake files are included: `private/candidate-001.key` (16 bytes) and `private/lobby-ck.bin` (32 bytes). These belong to our emulator; they are not Steam passwords or universal ROE server keys. No separate import is required.
3. From the repository root, run one command:

   ```powershell
   .\play.cmd
   ```

Enter the folder containing your `Europa_Client.exe` when prompted, for example `G:\REsearch\Ring of Elysium-2022`. The path is remembered in `.tools/client-path.txt`; next time, press Enter to reuse it. You can also provide it directly: `.\play.cmd -Client "G:\REsearch\Ring of Elysium-2022"`.

The bootstrap installs Python and the .NET 8 SDK locally under `.tools`. A system `py` command is not required. The first installation needs Internet access.

The launcher **runs directly from the selected client folder**. It does not copy the client or create a backup, and it does not patch EXE, DLL, or resource archives. The local server address is supplied as a launch argument. Space is needed only for dependencies, session files, and logs in this repository. Windows requests UAC approval for firewall rules that isolate the **selected game folder** from external networks; its original online access remains blocked by those rules. Services for the standard single-player scenario listen on localhost.

The game can write its normal settings and cache into the selected folder. With the default debug option, the launcher also creates its own `FileDriven/_GM_CONTROL_` marker and a uniquely named `ROE_Probe_state_*.lua` file. Its numeric TSV output is collected in the session report. On normal exit, launcher-owned debug files are removed; existing user files are preserved. An interrupted launcher may leave its temporary files behind.

Wait for the launcher to report readiness, then enter through **Training**. Keep the **DEFAULT** spawn cell for your first test to start near the fixed test loot. The scenario provides movement, inventory, three weapon slots, firing and reloading, a target, region closures, an airdrop, and evacuation. `play.cmd` sets an accelerated cycle of about 9.5 minutes; the 1,500-second process limit also includes login and preparation.

Direct ground-to-weapon attachment dragging and native hit markers have now been checked under Proton, including body, head, armor, and lethal hits. Windows run 20261016T134206-fafd00 with the legacy launcher also confirmed audible body/head/kill feedback and AK attachment handling. The older W17 revision played a reload animation/sound on full R. The capacity fix has now passed Proton; Windows follow-up is in WINDOWS-TESTS-W19.csv. See [W17](WINDOWS-TESTS-W17.md) and [research notes](docs/HIT-FEEDBACK-20261016.md).

## Verified behavior and remaining work

The previous Windows build was tested for pickups, three weapon slots, firing, reloading, the target, zones, and a Kill 1 / Rescued 1 result. The new profile disables the invisible training hazard near the evacuation rope and extends the schedule. It has been tested under Proton, but **this public package has not yet been tested by launching the game on Windows**. See the [Windows log review](docs/WINDOWS-RAW-REVIEW-20261015.md).

Start with the [smoke test](SMOKE-TEST.md), then use the [full W16 checklist](WINDOWS-TESTS.md) if needed. The corrected full-magazine R gate awaits Windows W19 validation. Original balance, AI, loot distribution, and a complete multiplayer match remain unfinished. The current preset has three reductions of the safe area across six timed phases.

After closing the game, run `export-report.cmd`. It creates a compact report under `reports/`, excluding keys and raw packets. Share that folder with a description of your actions; do not publish the full `runs` folder. Supporting documentation is currently mainly in Russian.

## Reset and reinstall

Close the game and its launcher, then run:

```powershell
git pull --ff-only
.\reset.cmd
.\play.cmd
```

`reset.cmd` removes only this client's local firewall rule group, receipt-tracked launcher debug files, generated lobby build files, and the extracted region cache. The next `play.cmd` rebuilds the emulator. Game EXE/DLL/resource archives, game settings, saved client path, local profiles, installed dependencies, and `runs`/`reports` are preserved. A running launcher blocks reset; UAC may be requested to remove firewall rules.

For a fresh local profile and dependency installation:

```powershell
.\reset.cmd -FreshProfile -ReinstallDependencies
.\play.cmd
```

`-FreshProfile` deletes all emulator profiles and saved cosmetic choices; it does not delete the game's UserData. `-ReinstallDependencies` removes the repository's downloaded Python, .NET, and installer cache so the next launch installs them again. Both options are off by default. Use `-Client "G:\REsearch\Ring of Elysium-2022"` to reset another client path.

Cleanup receipts are written by this version of the launcher. Unknown or modified files, and older leftovers without ownership records, are preserved. Reset does not restore earlier game settings or caches written by the game itself; no client backup is made. It does not discard source-code changes or change Git versions.

## Community and development

Join the [Discord community](https://discord.gg/pD2Bj5kAxk) to discuss tests and research.

Research, build identities, protocol notes, and the recovery plan are in [ring-of-elysium-research](https://github.com/ROE-LIVE/ring-of-elysium-research). Read [CONTRIBUTING.md](CONTRIBUTING.md) before changing code, and [RIGHTS.md](RIGHTS.md) for provenance and licensing information.

---

<a id="russian"></a>

## Русский

### Продолжение исследований — 18 октября 2026

Добавлен opt-in terrain LOS по исходному рельефу Iceland. Proton подтвердил попадания, переподключение, два убийства, эвакуацию и новый Training. Нужен собственный извлечённый PXBIN; стандартный launcher не включает эту опцию. Полная коллизия и исходный урон не восстановлены. Задержка изображений инвентаря не воспроизведена/не исправлена. Действуют прежние Windows W19 тесты. [Подробности](docs/SESSION-RESULT-20261018-PM.md).

### Обновление — 18 октября 2026

`-PracticeTargets 10` включает десять пассивных мишеней с отдельными HP/бронёй/сумками. В Proton проверены два настоящих убийства и раздельный лут; в отдельном контроле — десять административных смертей, обрывы связи и эвакуация без ложного начисления убийств. NPC не копируют начальные патроны/бинты игрока. Исправленная ёмкость полного магазина проверена в Proton; Windows новой ревизии ожидается.

```powershell
git pull --ff-only
.\play.cmd -Client "G:\REsearch\Ring of Elysium-2022" -PracticeTargets 10 -LiveControl
```

Training, клетку для фиксированного стенда не менять. Каталог лута, armored и cycle уже заданы в play.cmd — повторять эти параметры не нужно. Проверки — [WINDOWS-TESTS-W19.csv](WINDOWS-TESTS-W19.csv), затем `export-report.cmd`. Мишени пассивные, исходный AI не восстановлен. [Технический итог](docs/SESSION-RESULT-20261018.md).

### Демонстрационное использование и отказ от ответственности

- **Это экспериментальный демонстрационный проект только для личного домашнего использования и исследований.** Он не является официальным сервисом ROE или готовым сервером для эксплуатации.
- Все действия по установке, настройке, запуску и исследованию вы выполняете **добровольно, на свой страх и риск**. Вы самостоятельно отвечаете за свои действия и проверку пригодности проекта для вашей системы.
- Код, инструменты и исследовательские материалы предоставляются **«как есть», без гарантий** работоспособности, безопасности, надёжности и пригодности для конкретных целей.
- **В максимально допустимой применимым законодательством степени владелец репозитория, авторы, сопровождающие и участники проекта не несут ответственности** за ущерб, потерю данных, сбои, изменения системных или сетевых настроек и другие последствия использования либо невозможности использования проекта.

Это уведомление не исключает ответственность, которую нельзя исключить по закону, и не меняет лицензии сторонних компонентов.

Для тех, кто хочет запустить достигнутый результат на Windows11 x64. Код лобби, Python-peer и bootstrap включены. Это внешняя реконструкция игровой сессии, а не найденный оригинальный сервер. Основная карта — Iceland16010.

## Первый запуск

1. Нужна **полная копия клиента2022 с ресурсами**, а не один EXE. Исследован корневой `Europa_Client.exe`, SHA-256 `2dca9b1e122e21363e14eeeb2372598c773205a907ed8d2b2d54a7229ad6ba18`. Другие билды несовместимы.
2. Фиксированные зависимости локального handshake уже включены: `private/candidate-001.key` (16байт) и `private/lobby-ck.bin` (32байта). Это данные нашего эмулятора, не пароль Steam и не универсальный ключ серверов ROE. Отдельный импорт не нужен.

3. Из корня репозитория запустите одну команду:

   ```powershell
   .\play.cmd
   ```

Когда появится запрос, укажите папку с `Europa_Client.exe`, например `G:\REsearch\Ring of Elysium-2022`. Путь сохраняется в `.tools/client-path.txt`; при следующем запуске нажмите Enter, чтобы использовать его снова. Можно передать путь сразу: `.\play.cmd -Client "G:\REsearch\Ring of Elysium-2022"`.

Bootstrap устанавливает Python и .NET8 SDK локально в `.tools`; системная команда `py` не требуется. Для первой установки нужен Интернет. Launcher **запускает игру прямо из выбранной папки**, без копии клиента и без бэкапа. EXE, DLL и архивы ресурсов не патчатся; адрес локального сервера передаётся параметром запуска. Место требуется для зависимостей, файлов сеанса и журналов в репозитории. Windows запрашивает UAC для правил firewall, изолирующих **выбранную папку игры** от внешней сети; эти правила продолжают блокировать её прежний онлайн-доступ.

Сама игра может записывать обычные настройки и кэш в выбранную папку. При включённой по умолчанию диагностике launcher добавляет собственный marker `FileDriven/_GM_CONTROL_` и файл `ROE_Probe_state_*.lua` с уникальным именем. Числовой TSV переносится в отчёт сеанса. После штатного завершения собственные debug-файлы удаляются, существующие пользовательские файлы сохраняются. При прерывании launcher временные файлы могут остаться.

Дождитесь сообщения launcher о готовности, войдите через **Training**. Для первого теста оставьте клетку **DEFAULT**, чтобы оказаться рядом с фиксированным тестовым лутом. Доступны обычное движение, инвентарь, три оружейных слота, стрельба/перезарядка, мишень, закрытие областей, дроп и эвакуация. `play.cmd` задаёт ускоренный цикл≈9.5мин;1500с — общий лимит процесса с учётом входа.

Прямой перенос совместимого модуля с земли на оружие и штатные отметки попаданий теперь проверены в Proton: тело, голова, броня и добивание. Windows-прогон20261016T134206-fafd00 через прежний launcher подтвердил слышимый body/head/kill feedback и модулиAK. В старой W17 при полном магазине R запускала анимацию/звук. Исправление ёмкости прошло Proton; Windows-проверка в WINDOWS-TESTS-W19.csv. Отдельный [чек-лист W17](WINDOWS-TESTS-W17.md), [результаты исследования](docs/HIT-FEEDBACK-20261016.md).

## Что проверено и что проверить

На прежней Windows-сборке подтверждены подбор/три слота/огонь/перезарядка, мишень, зоны и итог Kill1/Rescued1. Новый профиль отключает невидимый учебный урон около троса и растягивает календарь; он проверен в Proton, но **новая публичная упаковка ещё не запускалась на Windows**. Источник: [первичные журналы](docs/WINDOWS-RAW-REVIEW-20261015.md).

Начните с [короткой проверки](SMOKE-TEST.md), затем при необходимости используйте [полный W16](WINDOWS-TESTS.md). Анимация перезарядки полного магазина остаётся открытой. Исходные баланс/AI/распределение лута и полный многопользовательский матч не восстановлены. Три сокращения безопасной площади при шести временных фазах — текущий пресет.

После закрытия игры выполните `export-report.cmd`: он создаёт компактный отчёт в `reports/`, исключая ключи и сырые пакеты. Передавайте эту папку и описание действий; полную папку `runs` не публикуйте.

Исследовательский комплект находится рядом: [ring-of-elysium-research](https://github.com/ROE-LIVE/ring-of-elysium-research). Для изменения кода читайте [CONTRIBUTING.md](CONTRIBUTING.md), происхождение и лицензирование — [RIGHTS.md](RIGHTS.md). Все сервисы штатного одиночного сценария слушают localhost.

## Сброс и повторная установка

Закройте игру и окно launcher, затем выполните:

```powershell
git pull --ff-only
.\reset.cmd
.\play.cmd
```

`reset.cmd` удаляет только локальную группу правил firewall для выбранного клиента, собственные debug-файлы по квитанциям, результаты сборки лобби и извлечённый кэш регионов. Следующий `play.cmd` заново собирает эмулятор. EXE/DLL/архивы игры, игровые настройки, сохранённый путь, локальные профили, зависимости и папки `runs`/`reports` сохраняются. При работающем launcher сброс блокируется; для удаления правил firewall может потребоваться UAC.

Для чистого локального профиля и переустановки зависимостей:

```powershell
.\reset.cmd -FreshProfile -ReinstallDependencies
.\play.cmd
```

`-FreshProfile` удаляет все профили эмулятора и сохранённый выбор внешности, сохраняя UserData игры. `-ReinstallDependencies` удаляет установленный в репозитории Python, .NET и кэш установщиков; следующий запуск установит их заново. Оба флага по умолчанию выключены. Для другой папки передайте `-Client "G:\REsearch\Ring of Elysium-2022"`.

Квитанции очистки создаются этой версией launcher. Неизвестные или изменённые файлы и остатки старых запусков без подтверждения владения сохраняются. Сброс не возвращает прежние настройки и кэш, записанные самой игрой: бэкап клиента не создаётся. Исходный код и версии Git команда не переключает.

## Сообщество

Присоединяйтесь к [Discord](https://discord.gg/pD2Bj5kAxk), чтобы обсудить исследования, согласовать проверки и поделиться результатами.

## Update — 16 October 2026 / Обновление

Full-magazine reload capacity and eight test loot heights were corrected; validated under Proton, Windows retest pending. See [results](docs/SESSION-RESULT-20261016-AFTERNOON.md).

Исправлены вместимость для полной R и высоты восьми тестовых предметов; проверено под Proton, новый Windows-повтор ожидается. [Результаты](docs/SESSION-RESULT-20261016-AFTERNOON.md).
