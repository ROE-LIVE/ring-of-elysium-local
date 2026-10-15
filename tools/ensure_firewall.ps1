param([Parameter(Mandatory=$true)][string]$Client, [switch]$Apply, [switch]$Remove)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$runtime = [IO.Path]::GetFullPath($Client).TrimEnd([IO.Path]::DirectorySeparatorChar)
if (-not $Remove) {
    $runtime = (Resolve-Path -LiteralPath $runtime).Path
    $exe = Join-Path $runtime 'Europa_Client.exe'
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'В выбранной папке нет Europa_Client.exe.' }
    if ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant() -ne '2dca9b1e122e21363e14eeeb2372598c773205a907ed8d2b2d54a7229ad6ba18') { throw 'Нужен проверенный клиент2022.' }
}
$hash = [Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($runtime.ToLowerInvariant()))
$id = ([BitConverter]::ToString($hash) -replace '-','').Substring(0,12)
$group = 'ROE2022-local-' + $id
$rules = @(Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue)
function Invoke-RoeFirewallElevation {
    $scriptLiteral = "'" + $PSCommandPath.Replace("'", "''") + "'"
    $clientLiteral = "'" + $runtime.Replace("'", "''") + "'"
    $command = "& $scriptLiteral -Client $clientLiteral -Apply"
    if ($Remove) { $command += ' -Remove' }
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    $process = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand',$encoded)
    return $process.ExitCode
}
if ($Remove) {
    if ($rules.Count -eq 0) { Write-Host 'No local firewall rules / Локальных правил нет.'; exit 0 }
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { exit (Invoke-RoeFirewallElevation) }
    $rules | Remove-NetFirewallRule
    Write-Host ('Removed local firewall rules / Удалены локальные правила: ' + $rules.Count)
    exit 0
}
$programs = @(Get-ChildItem -LiteralPath $runtime -Recurse -File -Filter '*.exe')
$profiles = @(Get-NetFirewallProfile)
if ($profiles | Where-Object { -not $_.Enabled }) { throw 'Для локального режима включите профили брандмауэра Windows.' }
if ($rules.Count -eq $programs.Count -and $rules.Count -gt 0 -and -not ($rules | Where-Object { $_.Enabled -ne 'True' -or $_.Action -ne 'Block' })) {
    $existing = @($rules | Get-NetFirewallApplicationFilter | Select-Object -ExpandProperty Program)
    if (@($programs | Where-Object { $_.FullName -notin $existing }).Count -eq 0) { exit 0 }
}
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $code = Invoke-RoeFirewallElevation
    if ($code -ne 0) { throw 'Не удалось настроить изоляцию клиента.' }
    exit 0
}
$remote = @('0.0.0.0-126.255.255.255','128.0.0.0-255.255.255.255','::2-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff')
$rules | Remove-NetFirewallRule
$created = @()
try {
    for ($index=0; $index -lt $programs.Count; $index++) {
        $name = $group + '-' + $index
        New-NetFirewallRule -Name $name -DisplayName $name -Group $group -Direction Outbound -Action Block -Program $programs[$index].FullName -RemoteAddress $remote -Profile Any -Enabled True | Out-Null
        $created += $name
    }
} catch {
    foreach ($name in $created) { Remove-NetFirewallRule -Name $name -ErrorAction SilentlyContinue }
    throw
}
Write-Host ('Изоляция выбранного клиента готова; правил: ' + $created.Count)
