# ROE local — everything the server and launcher do

[Português](RECURSOS.md) | **English**

A homemade, **unofficial** server for playing **Ring of Elysium (2022 build, 0.2.989.0)** after the official servers shut down. It runs on your PC, alone or as a room for the local network (LAN), and uses the Steam game **without changing any game file**.

> **Download:** [installer for Windows](https://github.com/streamnestapp/ring-of-elysium-local/releases/latest) (~37 MB).
>
> **Before downloading**
> - The game is **not** included in the package. Each PC needs the full 2022 client, with the `Europa_Client.exe` whose SHA-256 is `2dca9b1e…6ba18`. Other versions will not connect, and the launcher checks the file.
> - Requires Windows 10/11 x64.
> - This is an experimental project for personal use at home, provided "as is" (see [RIGHTS.md](RIGHTS.md)).

Legend:
- ✅ tested in the game
- 🧪 implemented, not yet fully tested in the game
- ⏳ does not work yet
- 📦 comes with the **installer** ([download in Releases](https://github.com/streamnestapp/ring-of-elysium-local/releases/latest)): the control panel, the map scripts (`jogar-mapa.ps1`) and the catalogs for each map. The installer includes no game files: it reads them from your Ring of Elysium during installation.

---

## 1. Launcher

### How to start

| Method | What it does |
|---|---|
| `play.cmd` | Training match on Mt. Dione, with the accelerated cycle (~9.5 min). Asks for the game folder only the first time. |
| `run-roe-2022.cmd [options]` | The same launcher, with all the options in the table below. |
| `jogar-mapa.ps1 <map>` 📦 | Sets up the right options for each map (Mt. Dione and variants, KillZone, Vera/Desert): loot, spawn, zone, weather, vehicles and airdrop. |
| Control panel 📦 | A browser page (this PC only) to configure, start and follow the match (section 11). |
| Installer 📦 | Lets you choose whether the PC is **server and client** or **client only** (section 12). |

### How it treats your PC

- **Does not touch the game:** it runs straight from the chosen folder, with no copying, no backup and no changes to EXE, DLL or resource files ✅.
  - The local server address is passed as a launch argument.
- **Installs dependencies by itself**, in the repository's `.tools` folder: Python and .NET 8. It does not need `py` on the system.
- **Isolates the game from the internet** with firewall rules only for the chosen folder (asks for UAC). The standalone-mode services listen only on localhost.
- **One session at a time**, with a lock. On close, it ends only its own processes.
- **Temporary files:** the debug files the launcher creates are deleted on exit, and yours are preserved.
- **Logs:** each match writes its own in `runs/`.
  - `export-report.cmd` generates a compact report, with no keys or raw packets.
- **`reset.cmd`:** undoes the firewall rules, the cache and the lobby build.
  - `-FreshProfile` deletes the local profiles; `-ReinstallDependencies` downloads Python and .NET again.
- **`-VerifyOnly`:** checks the client, keys, catalogs and map without opening the game.

### `run-roe-2022.cmd` options

| Option | What it is for |
|---|---|
| `-Client <folder>` | Game folder; remembered in `.tools/client-path.txt`. |
| `-Profile <name>` | Separate local profile: appearance and cosmetics. |
| `-PlayerName`, `-GuestName` | Your name and the default name for guests (shown in the game). |
| `-Mode walk\|cycle`, `-CycleScale 1..10` | Match with the zone, airdrop and evacuation schedule. 10 is the original timing (~32 min); lower is faster. |
| `-Duration <s>` | Maximum session time. |
| `-StartHour 7\|8\|15\|16`, `-TemperatureRaw` | Time of day and starting temperature. |
| `-Kit snowboard\|glider\|climb` | Jump equipment: snowboard, glider or grappling hook. |
| `-WeaponProfile citori\|m4\|ak47\|r700\|mosin\|usp45` | Starting weapon. |
| `-MapId`, `-MapAnchor`, `-MapSpawnCells` | Map, origin and spawn cells. |
| `-MapZoneProfile`, `-MapZoneIndex`, `-MapZoneSeed` | Map zone: phases, region index and the draw of the final region. |
| `-LootCatalog <json>` | Loot for the map's points. |
| `-NativeAirDrop`, `-AirdropTable`, `-AirdropPoints` | Balloon airdrop, crate contents and drop points. |
| `-NativeEvacuation` | Evacuation by the game's helicopter. |
| `-OriginalJeeps`, `-VehicleProfile jeep\|snowmotor` | Original vehicles and the model of the training vehicle. |
| `-WinterDoors`, `-WinterWindows` | Doors that open and windows that break. |
| `-ZoneDamage <0..1000>` | Damage per second outside the safe zone. |
| `-DeathOnZero` | Die when health reaches zero (without it, training does not kill). |
| `-SharedRoom`, `-SharedPvP 1..100` | Room for several PCs and damage between players (%). |
| `-Target none\|plain\|armored`, `-PracticeTargets 1..10`, `-TargetLOS` | Training targets, with or without a vest, and line of sight through the terrain. |
| `-Bots`, `-BotGroundRoute`, `-BotBehavior` | Experimental bot with a fixed route (not the original AI). |
| `-ClimbPractice`, `-BoatPractice`, `-VehicleDamagePractice` | Training scenarios for climbing, boat and vehicle damage. |
| `-FragDamage`, `-OwnArmorAbsorbPercent` | Grenade damage and your own vest's protection in training. |
| `-LiveControl` | Live commands during the match (section 11). |
| `-ReliableUDP`, `-IdleHandoff` | More robust networking (UDP resend, idle connection handoff). |
| `-DebugConsole`, `-DiagnosticHazard`, `-DiagnosticDeparture` | Diagnostics. |
| `-RemotePeer <user@ip>` | Windows client with the server on a Linux machine on the network, via SSH. |
| `-VerifyOnly` | Only checks everything, without opening the game. |

## 2. Lobby

- Local login with the emulator's fixed handshake (the `private/` files). It uses no Steam account and not the official servers ✅.
- Character and appearance:
  - the character profile is created and the appearance is saved per local profile ✅;
  - in the room, each account has its own appearance ✅.
- Player name in the lobby and in the match ✅.
- **Training** queue and **Start Matchmaking** leading to the local match ✅.
- Jump-point selection screen, with a timer and a cell map. In the room, each player gets one cell ✅.

## 3. Maps

| Map | Status |
|---|---|
| **Mt. Dione (Iceland, 16010)** | ✅ |
| Variants on the same terrain: 16008, 16015 Sniper Assassin, 16016, 16030 | ✅ |
| **KillZone (16007)**, with its own region index, zone and terrain | ✅ |
| **Vera / Desert (16021)** | ✅ experimental |

- **Loot** at each map's original points 📦.
- **Spawn** at the real terrain height, so you do not fall through the map. The draw avoids water ✅.

## 4. Match

- **Safe zone that closes** in phases, with damage outside the zone and the danger-area visual ✅.
  - The visual disappears when you return, on foot, by glider or by car ✅.
- **Weather drawn as in the original**, from the EnvrMapWeatherTable and EnvrClimateTable tables: map weather → group → sequence of conditions (sun, rain, fog, snow, ash…).
  - Initial weather ✅; changes during the match 🧪.
  - The volcano ash on KillZone comes from the weather ✅.
- **Airdrop:** a balloon that descends at a randomly chosen open point and drops the crate on the ground ✅.
  - The crate holds the original's airdrop loot: weapon, ammo, level 4 vest and helmet, medical box.
- **Evacuation:** rescue helicopter with 4 seats ✅.
  - It leaves 60 s after the first boarding.
  - At the end comes the newspaper: rescued or not rescued, with kills and distance.
- **HUD:** alive count, kill count and the kill notice for the room ✅.
- **Fall damage** by vertical speed (curve calibrated from video of the original) ✅.
- **Water:** swimming, underwater oxygen and drowning ✅.
- **Doors and windows:** opening and breaking ✅.

## 5. Jump equipment

| Kit | Status |
|---|---|
| Glider, with jet and 60 s recharge | ✅ |
| Snowboard / ski | ✅ |
| Grappling hook (climbing), with 10 s recharge | ✅ |
| Vera/Europe backpacks: island wing, BMX, grappling hook, motorcycle | ✅ |

## 6. Tactical items

| Tactical item | Status |
|---|---|
| Deployable Shield (barricade), which disappears after 30 s | ✅ |
| Biosignal Detector (scanner), with a warning for the detected player | ✅ |
| Vehicle modification (vehicle modification kit) | ✅ |
| Holographic Decoy (hologram) | 🧪 other players do not see it yet |
| Stealth Cloak (invisibility cloak) | 🧪 the cloak's energy is not simulated |
| Medgun (self-heal) | 🧪 |
| Recon Drone, DPV | ⏳ |

The usage counter and recharge appear on the HUD ✅.

## 7. Vehicles

- **Original models** for each map (Jeep, Fiat, SnowMotor, boat…), at the original points ✅.
- **Multiple occupants**, with seat switching, including in multiplayer ✅.
- **Modification kit:** the vehicle levels up and gains more health ✅.
  - Special function on **Shift**: radar on the Jeep and invisibility on the Fiat, with duration and recharge from the table 🧪.
- **Vehicle damage** (training scenario).

## 8. Combat and items

- **Weapons:** damage comes from the game's table, with falloff by distance, headshots, reduced damage on arms and legs, and each weapon's range ✅.
- **Protection:** helmet and vest protect according to the table, by body part ✅.
- **Aiming and shooting:** three weapon slots, attachments, reload and hit feedback (body, head and kill sounds) ✅.
- **Ammo and healing:** all calibers, bandages and medical kits ✅.
- **Death:** the dead player's backpack with the loot is left behind; the body disappears for others after 30 s ✅.
- **Training targets** (up to 10), with health, vest and their own backpack ✅.
- **Grenade** with configurable damage.

## 9. Local network (LAN) multiplayer (experimental)

- **Room for up to 60 players** (the host and 59 guests), like the original matches. Tested with 2 PCs ✅.
- **The other PCs find the server by themselves** on the network (automatic discovery), with no need to type an IP ✅.
- **Names:** each player has their own. It appears above the character, on the dead player's backpack, in the survivors list and in the kill notice ✅.
- **Other players move smoothly** ✅:
  - running, jumping, aiming and shooting;
  - reloading and healing;
  - swimming and gliding;
  - BMX and snowboard.
- **Shared world:** the room shares the same state ✅.
  - Ground loot is common: whoever picks it up removes it for everyone.
  - Doors and windows.
  - Airdrop, vehicles and zone.
- **Optional PvP**, with damage between players from 1 to 100% ✅.
- **Joint evacuation:** the helicopter leaves with those who boarded and the match ends for everyone ✅.
- **Separate matches:** whoever joins while a match is in progress opens another match.
- **Host does not take down the room:** if the host's game closes, the services keep running and the guests continue to the end.

## 10. Network

- **Relay for the local network:** TCP 28001, UDP 28002, and UDP 28003 for automatic discovery 📦. It accepts only local-network IPs, or a list of IPs.
- **UDP resend and idle connection handoff**, optional, for unstable networks.
- **Linux server:** the server can run on a Linux machine on the network, with the client on Windows (`-RemotePeer`).

## 11. Control panel and live commands

- **Live commands** (`-LiveControl`), in all modes ✅:
  - teleport;
  - give ammo and heal;
  - send an airdrop (a complete flight to a chosen point);
  - spectate another player;
  - kick and ban (the ban list is kept in `runtime/banidos.json`).
- **Browser control panel** 📦:
  - choose map, variant, mode, PvP, zone damage and duration;
  - start and stop the match;
  - see players with health and position on the game map, and the match events;
  - teleport by clicking on the map and send the commands above with one click.

## 12. Installer 📦

[Download the latest version](https://github.com/streamnestapp/ring-of-elysium-local/releases/latest).


- Two options:
  - **server and client:** the PC hosts the matches and also plays;
  - **client only:** the PC just joins another PC's room.
- Finds the game folder on Steam, including other libraries and drives, and checks the executable's version.
- Already includes Python and the .NET 8 runtime (~37 MB in total) and needs no internet.
- **Includes no game files.** In the server option it reads 13 files from your Ring of Elysium, without changing anything, and checks each one by SHA-256:
  - tables and respawn points;
  - Mt. Dione, KillZone and Vera terrain;
  - region indexes;
  - map images.
  If any are missing later, the next match extracts them again.
- Asks for the player name and can open the room's ports in the firewall, for the local network only. Uninstalling removes those rules.

## 13. What does not exist yet

- **Enemy AI:** the optional bot follows a fixed route, and the training targets are stationary.
- **Server over the internet:** the room is for the local network only.
- **Tactical items and vehicles:** Recon Drone, DPV and the other modified-vehicle functions besides radar and invisibility are missing.
- **Balance:** the loot distribution is not identical to the original on every map.
- **Progression:** there is no store, pass or online progression.

## Notices

- **Unofficial**, with no connection to Tencent/Aurora Studio. The game's names belong to their owners.
- Does not change the game or disable antivirus or Windows protections.
- Personal, home use, at your own risk, with no warranties ([RIGHTS.md](RIGHTS.md), [README.md](README.md)).
