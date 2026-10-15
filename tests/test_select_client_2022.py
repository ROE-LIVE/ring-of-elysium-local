"""Интерактивный выбор папки: пробелы, сохранение, повторный запуск и отказ неверного билда."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHELL = os.environ.get('ROE_TEST_PWSH') or shutil.which('pwsh') or shutil.which('powershell.exe')


@unittest.skipUnless(SHELL, 'requires PowerShell')
class SelectClientTests(unittest.TestCase):
    def test_prompt_explicit_path_reuse_and_invalid_build(self):
        with tempfile.TemporaryDirectory(prefix='roe select ') as folder:
            base = Path(folder)
            game = base/'Игра [2022]';game.mkdir()
            repo = base/'repo';repo.mkdir()
            for name in ('Europa_Client.exe', 'ProtocalHandler_x64.dll', 'Tenproxy64.dll',
                         'SFC/World_EU_ICELAND_4096_RemainingFiles.sfc'):
                p = game/name;p.parent.mkdir(exist_ok=True);p.write_bytes(b'synthetic fixture')
            script = base/'check.ps1'
            script.write_text('''$ErrorActionPreference = 'Stop'
. $env:ROE_SELECT_HELPER
$script:answer = '"' + $env:ROE_SELECT_GAME + '"'
$script:prompts = 0
$script:wrong = $false
function Read-Host { param($Prompt); $script:prompts++; return $script:answer }
function Get-FileHash {
    param($LiteralPath,$Algorithm)
    if ($script:wrong) { return @{Hash=('0'*64)} }
    return @{Hash='2dca9b1e122e21363e14eeeb2372598c773205a907ed8d2b2d54a7229ad6ba18'}
}
$first = Select-RoeClient -Repository $env:ROE_SELECT_REPO
if ($first -ne $env:ROE_SELECT_GAME -or $script:prompts -ne 1) { throw 'First prompt failed' }
$script:answer = ''
$second = Select-RoeClient -Repository $env:ROE_SELECT_REPO
if ($second -ne $first -or $script:prompts -ne 2) { throw 'Saved path reuse failed' }
$explicit = Select-RoeClient -Client $env:ROE_SELECT_GAME -Repository $env:ROE_SELECT_REPO
if ($explicit -ne $first -or $script:prompts -ne 2) { throw 'Explicit path prompted' }
$script:wrong = $true
$rejected = $false
try { Select-RoeClient -Client $env:ROE_SELECT_GAME -Repository $env:ROE_SELECT_REPO }
catch { $rejected = $true }
if (-not $rejected) { throw 'Wrong build accepted' }
$script:wrong = $false
$rejected = $false
try { Select-RoeClient -Client (Join-Path $env:ROE_SELECT_GAME 'Europa_Client.exe') -Repository $env:ROE_SELECT_REPO }
catch { $rejected = $true }
if (-not $rejected) { throw 'EXE accepted instead of folder' }
Write-Output 'SELECT_CLIENT_OK'
''', encoding='utf-8-sig')
            before = {p.relative_to(game):p.read_bytes() for p in game.rglob('*') if p.is_file()}
            env = dict(os.environ, ROE_SELECT_HELPER=str(ROOT/'tools/select_client.ps1'),
                       ROE_SELECT_GAME=str(game), ROE_SELECT_REPO=str(repo))
            result = subprocess.run([SHELL, '-NoProfile', '-File', str(script)], env=env,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('SELECT_CLIENT_OK', result.stdout)
            self.assertEqual((repo/'.tools/client-path.txt').read_text(), str(game))
            self.assertEqual(before, {p.relative_to(game):p.read_bytes() for p in game.rglob('*') if p.is_file()})
