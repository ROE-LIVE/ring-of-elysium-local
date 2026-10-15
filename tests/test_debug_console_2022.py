"""Очистка собственных debug-файлов и ограниченная числовая телеметрия."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from debug_console_2022 import DebugConsoleSession, lua_snapshot


class DebugConsoleTests(unittest.TestCase):
    def test_install_and_cleanup_capture_numeric_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder);runtime = base / 'runtime';run = base / 'run'
            runtime.mkdir();run.mkdir()
            session = DebugConsoleSession(runtime, run)
            command = session.install()
            self.assertTrue(session.marker.is_file())
            self.assertIn('loadstring', command)
            session.output.write_text('snapshot\t1\nmagazine_slot1\t2\n')
            session.close()
            self.assertEqual((run / 'client-state.tsv').read_text(), 'snapshot\t1\nmagazine_slot1\t2\n')
            self.assertFalse(session.marker.exists());self.assertFalse(session.script.exists());self.assertFalse(session.output.exists())
            session.close()

    def test_existing_user_marker_and_modified_script_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder);runtime = base / 'runtime';run = base / 'run'
            runtime.mkdir();run.mkdir();(runtime / 'FileDriven').mkdir()
            marker = runtime / 'FileDriven/_GM_CONTROL_';marker.write_text('user-owned')
            session = DebugConsoleSession(runtime, run);session.install()
            session.script.write_text('-- user changed this file')
            session.close()
            self.assertEqual(marker.read_text(), 'user-owned')
            self.assertTrue(session.script.exists())

    def test_output_and_script_collisions_are_rejected_without_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder);session = DebugConsoleSession(runtime, runtime)
            session.output.write_text('existing')
            with self.assertRaises(ValueError):session.install()
            self.assertEqual(session.output.read_text(), 'existing')
            session.output.unlink();session.script.write_text('existing')
            with self.assertRaises(FileExistsError):session.install()
            self.assertEqual(session.script.read_text(), 'existing')
            self.assertFalse(session.marker.exists())

    def test_failed_command_record_rolls_back_owned_files(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder);runtime = base / 'runtime';run = base / 'run'
            runtime.mkdir();run.mkdir();session = DebugConsoleSession(runtime, run)
            with patch.object(Path, 'write_text', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):session.install()
            self.assertFalse(session.script.exists());self.assertFalse(session.marker.exists())

    def test_snapshot_requires_own_basename_and_only_fixed_getters(self):
        for name in ('../key.tsv', 'x";os.execute("bad")', '', None):
            with self.assertRaises(ValueError):lua_snapshot(name)
        body = lua_snapshot('ROE_Probe_state_0123456789ab.tsv')
        self.assertNotIn('pairs(', body);self.assertNotIn('debug.', body)
        self.assertIn('pcall(fn)', body)
        self.assertIn('GetInventoryWeaponAmmoLoaded(1)', body)
        self.assertIn('GetInventoryWeaponAmmoLoaded(3)', body)
        self.assertIn('GetInventoryWeaponAmmoInBag(20002)', body)
        self.assertIn('GetInventoryNumber(70001)', body)
        self.assertIn('value==value', body)

    @unittest.skipUnless(hasattr(Path, 'symlink_to'), 'requires symlink')
    def test_symlink_output_does_not_read_or_delete_other_file(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder);session = DebugConsoleSession(runtime, runtime);session.install()
            other = runtime / 'other.txt';other.write_text('unrelated')
            try:session.output.symlink_to(other)
            except OSError:self.skipTest('symlink permission not available')
            session.close()
            self.assertEqual(other.read_text(), 'unrelated')
            self.assertTrue(session.output.is_symlink());self.assertFalse((runtime / 'client-state.tsv').exists())
