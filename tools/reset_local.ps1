param([string]$Client = '', [switch]$FreshProfile, [switch]$ReinstallDependencies)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$sessionLock = $null
try {
    . (Join-Path $PSScriptRoot 'local_session.ps1')
    $sessionLock = Enter-RoeSessionLock -Repository $repo
    if (Get-Process -Name 'Europa_Client' -ErrorAction SilentlyContinue) { throw 'Сначала закройте игру / Close the game first.' }
    if (-not $Client) {
        $saved = Join-Path $repo '.tools\client-path.txt'
        if (Test-Path -LiteralPath $saved -PathType Leaf) { $Client = ([IO.File]::ReadAllText($saved)).Trim() }
    }
    if (-not $Client) { $Client = Read-Host 'Game folder / Папка игры для отката' }
    if ([string]::IsNullOrWhiteSpace($Client)) { throw 'Game folder is required / Не указана папка игры.' }
    $Client = [IO.Path]::GetFullPath($Client.Trim().Trim('"').Trim("'"))
    # Удаление правил не зависит от наличия прежнего EXE или смены его версии.
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'ensure_firewall.ps1') -Client $Client -Remove
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось убрать правила firewall / Firewall cleanup failed.' }
    Remove-RoeClientDebugFiles -Repository $repo -Client $Client
    $targets = @('server\lobby\LobbyEmulator.Sdk\bin','server\lobby\LobbyEmulator.Sdk\obj','runtime\regions-iceland-fast.dat')
    if ($FreshProfile) { $targets += @('runtime\local-account','runtime\local-accounts') }
    if ($ReinstallDependencies) { $targets += @('.tools\python','.tools\dotnet','.tools\downloads') }
    foreach ($target in $targets) { Remove-RoeGeneratedPath -Repository $repo -Relative $target }
    Write-Host 'Reset complete / Сброс завершён. Game files, settings and reports are preserved.'
    Write-Host 'Update and reinstall / Обновить и установить заново: git pull --ff-only; .\play.cmd'
} catch {
    Write-Host ('Reset failed / Ошибка сброса: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($sessionLock) { $sessionLock.Dispose() }
}
