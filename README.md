# Ring of Elysium Local — experimental winter session (2022)

[English](#english) | [Русский](#russian) · [Discord](https://discord.gg/pD2Bj5kAxk)

<a id="english"></a>

## English

Run the current restoration on Windows 11 x64. The repository includes the lobby emulator, Python scene peer, and launcher. This is an unofficial preservation project that reconstructs a game session using external services. The original server has not been recovered. The main map is **Iceland, map 16010**.

## Quick start

1. Provide a **complete 2022 client with its resources**, not just an EXE. The supported executable is the root `Europa_Client.exe`, SHA-256 `2dca9b1e122e21363e14eeeb2372598c773205a907ed8d2b2d54a7229ad6ba18`. Other builds are incompatible.
2. The fixed local handshake files are included: `private/candidate-001.key` (16 bytes) and `private/lobby-ck.bin` (32 bytes). These belong to our emulator; they are not Steam passwords or universal ROE server keys. No separate import is required.
3. From the repository root, run:

   ```powershell
   .\play.cmd -Client "G:\REsearch\Ring of Elysium-2022"
   ```

The bootstrap installs Python and the .NET 8 SDK locally under `.tools`. A system `py` command is not required. The first installation needs Internet access.

On first launch, the launcher **copies the complete client and resources** into `runtime/client`, excluding UserData and part of the cache. Allow space for the selected client files plus 2 GiB, dependencies, and logs. Later launches reuse the copy. No hard links or junctions are used, and the source client is not modified. Windows will request UAC approval to create firewall rules that isolate the runtime from external networks. Services for the standard single-player scenario listen on localhost.

Wait for the launcher to report readiness, then enter through **Training**. Keep the **DEFAULT** spawn cell for your first test to start near the fixed test loot. The scenario provides movement, inventory, three weapon slots, firing and reloading, a target, region closures, an airdrop, and evacuation. `play.cmd` sets an accelerated cycle of about 9.5 minutes; the 1,500-second process limit also includes login and preparation.

## Verified behavior and remaining work

The previous Windows build was tested for pickups, three weapon slots, firing, reloading, the target, zones, and a Kill 1 / Rescued 1 result. The new profile disables the invisible training hazard near the evacuation rope and extends the schedule. It has been tested under Proton, but **this public package has not yet been tested by launching the game on Windows**. See the [Windows log review](docs/WINDOWS-RAW-REVIEW-20261015.md).

Start with the [smoke test](SMOKE-TEST.md), then use the [full W16 checklist](WINDOWS-TESTS.md) if needed. Reloading a full magazine may still play an animation. Original balance, AI, loot distribution, and a complete multiplayer match remain unfinished. The current preset has three reductions of the safe area across six timed phases.

After closing the game, run `export-report.cmd`. It creates a compact report under `reports/`, excluding keys and raw packets. Share that folder with a description of your actions; do not publish the full `runs` folder. Supporting documentation is currently mainly in Russian.

## Community and development

Join the [Discord community](https://discord.gg/pD2Bj5kAxk) to discuss tests and research.

Research, build identities, protocol notes, and the recovery plan are in [ring-of-elysium-research](https://github.com/ROE-LIVE/ring-of-elysium-research). Read [CONTRIBUTING.md](CONTRIBUTING.md) before changing code, and [RIGHTS.md](RIGHTS.md) for provenance and licensing information.

---

<a id="russian"></a>

## Русский

Для тех, кто хочет запустить достигнутый результат на Windows11 x64. Код лобби, Python-peer и bootstrap включены. Это внешняя реконструкция игровой сессии, а не найденный оригинальный сервер. Основная карта — Iceland16010.

## Первый запуск

1. Нужна **полная копия клиента2022 с ресурсами**, а не один EXE. Исследован корневой `Europa_Client.exe`, SHA-256 `2dca9b1e122e21363e14eeeb2372598c773205a907ed8d2b2d54a7229ad6ba18`. Другие билды несовместимы.
2. Фиксированные зависимости локального handshake уже включены: `private/candidate-001.key` (16байт) и `private/lobby-ck.bin` (32байта). Это данные нашего эмулятора, не пароль Steam и не универсальный ключ серверов ROE. Отдельный импорт не нужен.

3. Из корня нового репозитория запустите:

   ```powershell
   .\play.cmd -Client "G:\REsearch\Ring of Elysium-2022"
   ```

Bootstrap устанавливает Python и .NET8 SDK локально в `.tools`; системная команда `py` не требуется. Для первой установки нужен Интернет. При первом запуске launcher **копирует полный клиент с ресурсами** в `runtime/client`, исключая UserData и часть кэша. Нужен объём выбранных файлов плюс2ГиБ, а также место для `.tools` и журналов. Последующие запуски используют готовую копию. Hardlink/junction не используются; исходный клиент не изменяется. При первом запуске потребуется UAC для настройки отдельных правил firewall, изолирующих runtime от внешней сети.

Дождитесь сообщения launcher о готовности, войдите через **Training**. Для первого теста оставьте клетку **DEFAULT**, чтобы оказаться рядом с фиксированным тестовым лутом. Доступны обычное движение, инвентарь, три оружейных слота, стрельба/перезарядка, мишень, закрытие областей, дроп и эвакуация. `play.cmd` задаёт ускоренный цикл≈9.5мин;1500с — общий лимит процесса с учётом входа.

## Что проверено и что проверить

На прежней Windows-сборке подтверждены подбор/три слота/огонь/перезарядка, мишень, зоны и итог Kill1/Rescued1. Новый профиль отключает невидимый учебный урон около троса и растягивает календарь; он проверен в Proton, но **новая публичная упаковка ещё не запускалась на Windows**. Источник: [первичные журналы](docs/WINDOWS-RAW-REVIEW-20261015.md).

Начните с [короткой проверки](SMOKE-TEST.md), затем при необходимости используйте [полный W16](WINDOWS-TESTS.md). Анимация перезарядки полного магазина остаётся открытой. Исходные баланс/AI/распределение лута и полный многопользовательский матч не восстановлены. Три сокращения безопасной площади при шести временных фазах — текущий пресет.

После закрытия игры выполните `export-report.cmd`: он создаёт компактный отчёт в `reports/`, исключая ключи и сырые пакеты. Передавайте эту папку и описание действий; полную папку `runs` не публикуйте.

Исследовательский комплект находится рядом: [ring-of-elysium-research](https://github.com/ROE-LIVE/ring-of-elysium-research). Для изменения кода читайте [CONTRIBUTING.md](CONTRIBUTING.md), происхождение и лицензирование — [RIGHTS.md](RIGHTS.md). Все сервисы штатного одиночного сценария слушают localhost.

## Сообщество

Присоединяйтесь к [Discord](https://discord.gg/pD2Bj5kAxk), чтобы обсудить исследования, согласовать проверки и поделиться результатами.
