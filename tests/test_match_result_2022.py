"""Семантика локального окончания: deadline, freeze, death, rescue, opt-in."""
import unittest
from pathlib import Path
import sys,math,json,struct,tempfile
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server/directory'))
from match_result_2022 import MatchEndPolicy
from match_statistics_2022 import MatchStatistics
class Fixture:
    def messages(self,actor_uid,room_uid,report,name):return [(0xd62,b'')]
class Tests(unittest.TestCase):
    def test_no_timer_before_world_and_freeze_once_after_deadline(self):
        p=MatchEndPolicy(timeout_seconds=10);s=MatchStatistics();w=SimpleNamespace(dead=False)
        self.assertEqual(p.poll(100,w,s,Fixture(),1,1,'X'),([],None));s.begin(100)
        self.assertEqual(p.poll(109,w,s,Fixture(),1,1,'X'),([],None));packets,e=p.poll(117,w,s,Fixture(),1,1,'X')
        self.assertEqual(e['cause'],'timeout');self.assertEqual(e['match_statistics']['survival_seconds'],10);self.assertEqual(e['match_statistics']['rescued'],0);self.assertEqual(packets[-1],(0x6589,bytes(9)))
        self.assertEqual(p.poll(120,w,s,Fixture(),1,1,'X'),([],None));self.assertEqual(s.snapshot(120)['survival_seconds'],10)
    def test_death_precedes_timeout_and_does_not_override_rescue(self):
        s=MatchStatistics();s.begin(100);p=MatchEndPolicy(on_death=True,timeout_seconds=10)
        self.assertEqual(p.poll(120,SimpleNamespace(dead=True),s,Fixture(),1,1,'X',already_rescued=True),([],None));_,e=p.poll(120,SimpleNamespace(dead=True),s,Fixture(),1,1,'X');self.assertEqual(e['cause'],'death')
    def test_invalid_bridge_leaves_match_unfinished_and_rescue_is_final(self):
        class Invalid:
            def messages(self,*args):raise ValueError('invalid fixture')
        s=MatchStatistics();s.begin(100);p=MatchEndPolicy(timeout_seconds=10)
        with self.assertRaises(ValueError):p.poll(120,SimpleNamespace(dead=False),s,Invalid(),1,1,'X')
        self.assertIsNone(s.ended_at);self.assertFalse(p.ended)
        s.finish(105,rescued=True)
        self.assertEqual(p.poll(120,SimpleNamespace(dead=True),s,Fixture(),1,1,'X'),([],None))

    def test_fixture_controls_are_opt_in_and_archive_cannot_end_live_match(self):
        from vehicle_probe_2022 import EvacuationUIFixture
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            terminal=bytearray(41);struct.pack_into('>I',terminal,8,4)
            terminal[12:16]=b'XXX\0';struct.pack_into('>I',terminal,24,1)
            struct.pack_into('>III',terminal,29,0,0,15)
            outcome=bytearray(174);struct.pack_into('>Q',outcome,0,1)
            struct.pack_into('>I',outcome,16,4);outcome[20:24]=b'XXX\0';outcome[-1]=1
            (root/'terminal.bin').write_bytes(terminal);(root/'outcome.bin').write_bytes(outcome)
            config=dict(reconstructed_session_statistics=True,terminal_file='terminal.bin',outcome_file='outcome.bin')
            path=root/'config.json'
            def load():
                path.write_text(json.dumps(config));return EvacuationUIFixture.load(path)
            f=load();self.assertFalse(f.result_on_death);self.assertIsNone(f.timeout_seconds)
            config.update(singleplayer_result_on_death=True,singleplayer_timeout_seconds=120)
            f=load();self.assertTrue(f.result_on_death);self.assertEqual(f.timeout_seconds,120)
            config['singleplayer_result_on_death']=1
            with self.assertRaises(ValueError):load()
            config.update(singleplayer_result_on_death=True,reconstructed_session_statistics=False,diagnostic_archive_statistics=True)
            with self.assertRaises(ValueError):load()

    def test_controls_require_explicit_valid_values(self):
        for x in (True,False,0,-1,float('nan'),float('inf'),7201,'10'):
            with self.subTest(value=x),self.assertRaises(ValueError):MatchEndPolicy(timeout_seconds=x)
        with self.assertRaises(ValueError):MatchEndPolicy(on_death=1)
        self.assertEqual(MatchEndPolicy().poll(999,SimpleNamespace(dead=True),MatchStatistics(),Fixture(),1,1,'X'),([],None))
if __name__=='__main__':unittest.main()
