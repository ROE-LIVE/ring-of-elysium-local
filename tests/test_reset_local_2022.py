"""Сброс после прерывания: только собственные артефакты, с сохранением игры и отчётов."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from debug_console_2022 import DebugConsoleSession

SHELL = os.environ.get('ROE_TEST_PWSH') or shutil.which('pwsh') or shutil.which('powershell.exe')


@unittest.skipUnless(SHELL, 'requires PowerShell')
class ResetTests(unittest.TestCase):
    def invoke(self, root, game, body, success=True):
        script = root/'check.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n. $env:ROE_RESET_HELPER\n"+body, encoding='utf-8-sig')
        env = dict(os.environ, ROE_RESET_HELPER=str(ROOT/'tools/local_session.ps1'),
                   ROE_RESET_REPO=str(root), ROE_RESET_GAME=str(game))
        result = subprocess.run([SHELL, '-NoProfile', '-File', str(script)], env=env,
                                capture_output=True, text=True, timeout=30)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def fixture(self, root, marker=None):
        game = root/'Game [2022]';game.mkdir()
        (game/'Europa_Client.exe').write_bytes(b'game executable')
        (game/'UserData').mkdir();(game/'UserData/settings.ini').write_bytes(b'user settings')
        if marker is not None:
            (game/'FileDriven').mkdir();(game/'FileDriven/_GM_CONTROL_').write_bytes(marker)
        run = root/'runs/session';run.mkdir(parents=True)
        session = DebugConsoleSession(game, run);session.install()
        return game, run, session

    def test_crash_cleanup_is_repeatable_and_preserves_game_logs_and_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);game,run,session=self.fixture(root)
            session.output.write_text('snapshot\t1\nmagazine_slot1\t17\n')
            (run/'events.jsonl').write_text('evidence')
            profile=root/'runtime/local-account';profile.mkdir(parents=True);(profile/'cosmetics.json').write_text('profile')
            build=root/'server/lobby/LobbyEmulator.Sdk/bin';build.mkdir(parents=True);(build/'test.dll').write_bytes(b'generated')
            body="Remove-RoeClientDebugFiles -Repository $env:ROE_RESET_REPO -Client $env:ROE_RESET_GAME\nRemove-RoeGeneratedPath -Repository $env:ROE_RESET_REPO -Relative 'server/lobby/LobbyEmulator.Sdk/bin'\n"
            self.invoke(root,game,body)
            self.invoke(root,game,body)
            self.assertFalse(session.script.exists());self.assertFalse(session.output.exists())
            self.assertFalse(session.marker.exists());self.assertFalse(session.marker.parent.exists())
            self.assertEqual((game/'Europa_Client.exe').read_bytes(),b'game executable')
            self.assertEqual((game/'UserData/settings.ini').read_bytes(),b'user settings')
            self.assertEqual((profile/'cosmetics.json').read_text(),'profile')
            self.assertEqual((run/'events.jsonl').read_text(),'evidence')
            self.assertIn('magazine_slot1', (run/'client-state-recovered.tsv').read_text())
            self.assertFalse(build.exists())

    def test_existing_empty_marker_and_modified_script_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);game,run,session=self.fixture(root,marker=b'')
            session.script.write_text('-- user changed this script')
            session.output.write_text('unrecognized user text')
            self.invoke(root,game,'Remove-RoeClientDebugFiles -Repository $env:ROE_RESET_REPO -Client $env:ROE_RESET_GAME')
            self.assertEqual(session.marker.read_bytes(),b'')
            self.assertEqual(session.script.read_text(),'-- user changed this script')
            self.assertEqual(session.output.read_text(),'unrecognized user text')

    def test_completed_receipt_does_not_remove_a_new_user_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);game,run,session=self.fixture(root)
            session.close()
            session.marker.parent.mkdir()
            session.marker.write_bytes(b'')
            self.invoke(root,game,'Remove-RoeClientDebugFiles -Repository $env:ROE_RESET_REPO -Client $env:ROE_RESET_GAME')
            self.assertTrue(session.marker.exists())

    def test_changed_marker_timestamp_is_preserved_after_crash(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);game,run,session=self.fixture(root)
            stamp=session.marker.stat().st_mtime_ns+2_000_000_000
            os.utime(session.marker,ns=(stamp,stamp))
            self.invoke(root,game,'Remove-RoeClientDebugFiles -Repository $env:ROE_RESET_REPO -Client $env:ROE_RESET_GAME')
            self.assertTrue(session.marker.exists())

    def test_receipt_cannot_target_game_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);game,run,session=self.fixture(root)
            receipt=json.loads(session.receipt.read_text());receipt['script']='Europa_Client.exe'
            session.receipt.write_text(json.dumps(receipt))
            self.invoke(root,game,'Remove-RoeClientDebugFiles -Repository $env:ROE_RESET_REPO -Client $env:ROE_RESET_GAME',success=False)
            self.assertEqual((game/'Europa_Client.exe').read_bytes(),b'game executable')

    def test_generated_cleanup_rejects_links_and_outside_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);game=root/'game';game.mkdir();outside=root/'outside';outside.mkdir()
            (outside/'keep.txt').write_text('keep')
            link=root/'runtime/linked';link.parent.mkdir()
            try:link.symlink_to(outside,target_is_directory=True)
            except OSError:self.skipTest('requires symlink permission')
            self.invoke(root,game,"Remove-RoeGeneratedPath -Repository $env:ROE_RESET_REPO -Relative 'runtime/linked'",success=False)
            self.invoke(root,game,"Remove-RoeGeneratedPath -Repository $env:ROE_RESET_REPO -Relative '../outside'",success=False)
            self.assertEqual((outside/'keep.txt').read_text(),'keep')

    def test_busy_launcher_lock_rejects_reset_then_releases(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.invoke(root,root,'''$first = Enter-RoeSessionLock -Repository $env:ROE_RESET_REPO
$blocked = $false
try { $second = Enter-RoeSessionLock -Repository $env:ROE_RESET_REPO; $second.Dispose() }
catch { $blocked = $true }
finally { $first.Dispose() }
if (-not $blocked) { throw 'Concurrent reset was not blocked' }
$third = Enter-RoeSessionLock -Repository $env:ROE_RESET_REPO
$third.Dispose()
''')

    def test_reset_entrypoint_reinstalls_dependencies_only_when_requested(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);game,run,session=self.fixture(root)
            tools=root/'tools';tools.mkdir()
            for name in ('reset_local.ps1','local_session.ps1'):
                shutil.copyfile(ROOT/'tools'/name,tools/name)
            generated=['server/lobby/LobbyEmulator.Sdk/bin','server/lobby/LobbyEmulator.Sdk/obj',
                       '.tools/python','.tools/dotnet','.tools/downloads',
                       'runtime/local-account','runtime/local-accounts']
            for name in generated:
                p=root/name;p.mkdir(parents=True,exist_ok=True);(p/'generated.txt').write_text('generated')
            (root/'.tools/client-path.txt').write_text(str(game))
            body='''function powershell.exe {
    param([switch]$NoProfile,[string]$ExecutionPolicy,[string]$File,[string]$Client,[switch]$Remove)
    if (-not $Remove -or $Client -ne $env:ROE_RESET_GAME -or -not $File.EndsWith('ensure_firewall.ps1')) { throw 'Wrong firewall scope' }
    $global:LASTEXITCODE = 0
}
& (Join-Path $env:ROE_RESET_REPO 'tools/reset_local.ps1')
'''
            self.invoke(root,game,body)
            self.assertFalse((root/generated[0]).exists())
            self.assertFalse((root/generated[1]).exists())
            for name in generated[2:]:self.assertTrue((root/name).exists())
            self.invoke(root,game,body.replace("'tools/reset_local.ps1')","'tools/reset_local.ps1') -FreshProfile -ReinstallDependencies"))
            for name in generated:self.assertFalse((root/name).exists())
            self.assertTrue(run.exists())
            self.assertTrue((root/'.tools/client-path.txt').exists())
            self.assertEqual((game/'Europa_Client.exe').read_bytes(),b'game executable')
