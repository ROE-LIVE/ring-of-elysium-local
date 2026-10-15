# Ring of Elysium Local — experimental winter session (2022)

**English** | [Русский](README.ru.md) · [Discord](https://discord.gg/pD2Bj5kAxk)

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
