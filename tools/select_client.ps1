function Select-RoeClient {
    param([string]$Client, [Parameter(Mandatory=$true)][string]$Repository)
    # Сохраняем только путь внутри репозитория; файлы игры здесь не меняются.
    $savedPath = Join-Path $Repository '.tools\client-path.txt'
    if ([string]::IsNullOrWhiteSpace($Client)) {
        $previous = ''
        if (Test-Path -LiteralPath $savedPath -PathType Leaf) {
            $previous = ([IO.File]::ReadAllText($savedPath)).Trim()
        }
        $prompt = 'Game folder / Папка игры (с Europa_Client.exe)'
        if ($previous) { $prompt += " [$previous; Enter = use / использовать]" }
        $Client = Read-Host $prompt
        if ([string]::IsNullOrWhiteSpace($Client)) { $Client = $previous }
    }
    if ([string]::IsNullOrWhiteSpace($Client)) { throw 'Не указана папка игры / Game folder is required.' }
    $Client = $Client.Trim().Trim('"').Trim("'")
    $directory = Get-Item -LiteralPath $Client -ErrorAction Stop
    if (-not $directory.PSIsContainer) { throw 'Укажите папку игры, а не EXE / Select the game folder, not the EXE.' }
    foreach ($file in @('Europa_Client.exe','ProtocalHandler_x64.dll','Tenproxy64.dll','SFC\World_EU_ICELAND_4096_RemainingFiles.sfc')) {
        if (-not (Test-Path -LiteralPath (Join-Path $directory.FullName $file) -PathType Leaf)) {
            throw "Неполный клиент / Incomplete client: $file"
        }
    }
    $sha = (Get-FileHash -LiteralPath (Join-Path $directory.FullName 'Europa_Client.exe') -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($sha -ne '2dca9b1e122e21363e14eeeb2372598c773205a907ed8d2b2d54a7229ad6ba18') {
        throw 'Неподдерживаемый билд / Unsupported build: expected ROE 2022 0.2.989.0.'
    }
    [IO.Directory]::CreateDirectory((Split-Path -Parent $savedPath)) | Out-Null
    [IO.File]::WriteAllText($savedPath,$directory.FullName,[Text.UTF8Encoding]::new($false))
    Write-Host ('In-place / Без копирования: ' + $directory.FullName)
    return $directory.FullName
}
