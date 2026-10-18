param(
    [string]$Client = '',
    [string]$Profile = 'default',
    [string]$RemotePeer = '',
    [ValidateSet('snowboard','glider','climb')][string]$Kit = 'snowboard',
    [ValidateSet(7,8,15,16)][int]$StartHour = 8,
    [ValidateRange(-5000,500)][int]$TemperatureRaw = 500,
    [ValidateSet('walk','cycle')][string]$Mode = 'walk',
    [ValidateRange(1,10)][int]$CycleScale = 1,
    [switch]$DiagnosticHazard,
    [ValidateSet('citori','m4','ak47','r700','mosin','usp45')][string]$WeaponProfile = 'citori',
    [switch]$Bots,
    [switch]$LiveControl,
    [switch]$WinterDoors,
    [switch]$WinterWindows,
    [switch]$DebugConsole,
    [switch]$BotGroundRoute,
    [switch]$BotBehavior,
    [switch]$ReliableUDP,
    [switch]$IdleHandoff,
    [switch]$DeathOnZero,
    [switch]$NativeAirDrop,
    [switch]$NativeEvacuation,
    [switch]$OriginalJeeps,
    [switch]$ClimbPractice,
    [switch]$BoatPractice,
    [switch]$VehicleDamagePractice,
    [ValidateSet('jeep','snowmotor')][string]$VehicleProfile = 'jeep',
    [switch]$DiagnosticDeparture,
    [ValidateRange(0,100)][int]$OwnArmorAbsorbPercent = 0,
    [ValidateRange(0,1000)][int]$FragDamage = 100,
    [switch]$ValidateMovement,
    [ValidateSet('none','plain','armored')][string]$Target = 'none',
    [ValidateRange(1,10)][int]$PracticeTargets = 1,
    [ValidateSet('off','open','blocked')][string]$TargetLOS = 'off',
    [string]$LootCatalog = '',
    [int]$Duration = 3600,
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$repo = Split-Path -Parent $PSScriptRoot
$pythonHome = Join-Path $repo '.tools\python'
$python = Join-Path $pythonHome 'python.exe'
$dotnetHome = Join-Path $repo '.tools\dotnet'
$dotnet = Join-Path $dotnetHome 'dotnet.exe'
$download = Join-Path $repo '.tools\downloads'
New-Item -ItemType Directory -Force -Path $download | Out-Null
$sessionLock = $null
try {
    . (Join-Path $PSScriptRoot 'local_session.ps1')
    $sessionLock = Enter-RoeSessionLock -Repository $repo
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Нужен Windows x64.' }
    . (Join-Path $PSScriptRoot 'select_client.ps1')
    $Client = Select-RoeClient -Client $Client -Repository $repo
    $key = Join-Path $repo 'private\candidate-001.key'
    if (-not (Test-Path -LiteralPath $key -PathType Leaf) -or (Get-Item -LiteralPath $key).Length -ne 16) {
        throw 'Добавьте локальный private\candidate-001.key. Восстановите файлы комплекта через git pull; см. private\README.md.'
    }
    $ck = Join-Path $repo 'private\lobby-ck.bin'
    if (-not (Test-Path -LiteralPath $ck -PathType Leaf) -or (Get-Item -LiteralPath $ck).Length -ne 32) { throw 'Добавьте локальный private\lobby-ck.bin (32байта). См. private\README.md.' }
    if (-not (Test-Path -LiteralPath $python)) {
        Write-Host 'Устанавливаю отдельный Python в .tools (py/python в системе не требуются)...'
        $zip = Join-Path $download 'python-3.12.10-embed-amd64.zip'
        Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip' -OutFile $zip
        $actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3') { throw 'Не совпала SHA-256 portable Python.' }
        New-Item -ItemType Directory -Force -Path $pythonHome | Out-Null
        Expand-Archive -LiteralPath $zip -DestinationPath $pythonHome -Force
    }
    # Embeddable Python изолирует sys.path; явно разрешаем наши модули/site-packages.
    @('python312.zip','.','Lib\site-packages','..\..\tools','..\..\server\directory','import site') |
        Set-Content -LiteralPath (Join-Path $pythonHome 'python312._pth') -Encoding ASCII
    $requirements = Join-Path $repo 'requirements.txt'
    $dependencies = Join-Path $pythonHome 'roe-dependencies.sha256'
    $hash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
    if (-not (Test-Path -LiteralPath $dependencies) -or (Get-Content -LiteralPath $dependencies -Raw).Trim() -ne $hash) {
        & $python -B -c 'import importlib.util,sys;sys.exit(0 if importlib.util.find_spec("pip") else 1)'
        if ($LASTEXITCODE -ne 0) {
            $getPip = Join-Path $download 'get-pip.py'
            Invoke-WebRequest -UseBasicParsing -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile $getPip
            & $python $getPip --no-warn-script-location --disable-pip-version-check
            if ($LASTEXITCODE -ne 0) { throw 'Не удалось подготовить pip.' }
        }
        Write-Host 'Устанавливаю зависимости локального протокола...'
        & $python -m pip install --disable-pip-version-check --no-warn-script-location --only-binary=:all: -r $requirements
        if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить cryptography/lz4.' }
        Set-Content -LiteralPath $dependencies -Value $hash -Encoding ASCII
    }
    if (-not $VerifyOnly -and -not $RemotePeer) {
        $dll = Join-Path $repo 'server\lobby\LobbyEmulator.Sdk\bin\Release\net8.0\LobbyEmulator.dll'
        $needSdk = -not (Test-Path -LiteralPath $dll)
        $install = -not (Test-Path -LiteralPath $dotnet)
        if (-not $install -and $needSdk) {
            $sdks = & $dotnet --list-sdks
            $install = -not ($sdks | Where-Object { $_ -match '^8\.' })
        }
        if ($install) {
            Write-Host 'Устанавливаю отдельный .NET8 в .tools...'
            $installer = Join-Path $download 'dotnet-install.ps1'
            Invoke-WebRequest -UseBasicParsing -Uri 'https://dot.net/v1/dotnet-install.ps1' -OutFile $installer
            if ($needSdk) { & $installer -Channel 8.0 -Architecture x64 -InstallDir $dotnetHome -NoPath }
            else { & $installer -Channel 8.0 -Runtime dotnet -Architecture x64 -InstallDir $dotnetHome -NoPath }
            if (-not (Test-Path -LiteralPath $dotnet)) { throw 'Не удалось установить .NET8.' }
        }
    }
    $env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
    $env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
    $env:DOTNET_ROOT = $dotnetHome
    $arguments = @('-X','utf8','-B','-u',(Join-Path $PSScriptRoot 'windows_launch.py'),'--client',$Client,'--profile',$Profile,'--kit',$Kit,'--weapon-profile',$WeaponProfile,'--target',$Target,'--practice-targets',"$PracticeTargets",'--target-los',$TargetLOS,'--mode',$Mode,'--duration',"$Duration",'--cycle-scale',"$CycleScale",'--dotnet',$dotnet)
    if ($RemotePeer) { $arguments += @('--remote-peer',$RemotePeer) }
    if ($Bots) { $arguments += '--bots' }
    if ($WinterDoors) { $arguments += '--winter-doors' }
    if ($WinterWindows) { $arguments += '--winter-windows' }
    if ($LiveControl) { $arguments += '--live-control' }
    if ($DiagnosticHazard) { $arguments += '--diagnostic-hazard' }
    if ($DebugConsole) { $arguments += '--debug-console' }
    if ($BotGroundRoute) { $arguments += '--bot-ground-route' }
    if ($BotBehavior) { $arguments += '--bot-behavior' }
    $arguments += @('--start-hour', "$StartHour")
    $arguments += @('--temperature-raw', "$TemperatureRaw")
    if ($NativeAirDrop) { $arguments += '--native-airdrop' }
    $arguments += @('--vehicle-profile', $VehicleProfile)
    if ($BoatPractice) { $arguments += '--boat-practice' }
    if ($VehicleDamagePractice) { $arguments += '--vehicle-damage-practice' }
    if ($ClimbPractice) { $arguments += '--climb-practice' }
    if ($OriginalJeeps) { $arguments += '--original-jeeps' }
    if ($NativeEvacuation) { $arguments += '--native-evacuation' }
    if ($DiagnosticDeparture) { $arguments += '--diagnostic-departure' }
    if ($ReliableUDP) { $arguments += '--reliable-udp' }
    if ($IdleHandoff) { $arguments += '--idle-handoff' }
    if ($DeathOnZero) { $arguments += '--death-on-zero' }
    $arguments += @('--own-armor-absorb-percent', "$OwnArmorAbsorbPercent")
    $arguments += @('--frag-damage', "$FragDamage")
    if ($ValidateMovement) { $arguments += '--validate-movement' }
    if ($LootCatalog) { $arguments += @('--loot-catalog',$LootCatalog) }
    if ($VerifyOnly) { $arguments += '--verify-only' }
    & $python @arguments
    exit $LASTEXITCODE
} catch {
    Write-Host ('Ошибка: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($sessionLock) { $sessionLock.Dispose() }
}
