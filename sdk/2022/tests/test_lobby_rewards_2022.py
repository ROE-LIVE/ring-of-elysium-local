"""Группы владения/выбора и границы54C5/54C9 по Nexus и декодеру2022."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from lobby_rewards_2022 import LobbyRewards
from local_cosmetics_2022 import LocalCosmetics


class LobbyRewardsTests(unittest.TestCase):
    def catalog(self):
        groups=[[]for _ in range(19)]
        for g,item in ((0,111001),(1,112001),(2,113001),(4,221001),(6,901001),(11,231001),(15,601002)):
            groups[g]=[item]
        return dict(owned_reward_groups=groups,default_reward_ids={'4':[221000],'15':[601001]},
                    reward_vehicle_types={'601001':300107,'601002':300107})

    def test_wire_groups_and_single_choice_replacement(self):
        r=LobbyRewards(self.catalog(),{});at=0
        for g,expected in enumerate(r.groups):
            n=struct.unpack_from('>I',r.owned,at)[0];at+=4
            self.assertEqual(list(struct.unpack_from('>'+str(n)+'I',r.owned,at)),expected);at+=4*n
        self.assertEqual(r.owned[at:],bytes(4))
        for g in (0,1,2,4,6,11,15):
            item=r.groups[g][0];replies,action=r.handle(0x54c6,struct.pack('>II',item,g))
            self.assertEqual(action,'reward_changed');self.assertEqual(replies[0],(0x54c7,bytes(4)))
        equipped=r.equipped(10201,[7200016]);self.assertEqual(struct.unpack_from('>11I',equipped),
            (111001,112001,113001,901001,221001,0,231001,0,0,0,10201))
        self.assertEqual(struct.unpack_from('>II',equipped,44),(1,601002))
        self.assertEqual(r.handle(0x54c8,b'\0')[0],[(0x54c9,r.equipped())])
        self.assertEqual(r.handle(0x54c4,b'\0')[0],[(0x54c5,r.owned)])

    def test_default_and_unequip_clear_only_addressed_group(self):
        r=LobbyRewards(self.catalog(),{})
        for item,g in ((221001,4),(231001,11),(601002,15)):r.handle(0x54c6,struct.pack('>II',item,g))
        r.handle(0x54c6,struct.pack('>II',221000,4));self.assertNotIn('4',r.selected)
        self.assertEqual(r.selected['11'],231001)
        r.handle(0x54c6,struct.pack('>II',601001,15));self.assertFalse(r.vehicles)
        r.handle(0x54ca,struct.pack('>II',231001,11));self.assertFalse(r.selected)

    def test_unknown_wrong_group_and_malformed_do_not_mutate(self):
        r=LobbyRewards(self.catalog(),{});before=r.state()
        for item,g in ((111001,1),(901001,19),(0,3),(True,0)):
            self.assertEqual(r.handle(0x54c6,struct.pack('>II',item,g))[0],[(0x54c7,struct.pack('>I',1))])
            self.assertEqual(r.state(),before)
        for body in (b'',bytes(7),bytes(9)):self.assertEqual(r.handle(0x54c6,body),([],None))
        invalid=self.catalog();invalid['owned_reward_groups'][6]=list(range(1,602))
        with self.assertRaises(ValueError):LobbyRewards(invalid,{})
        with self.assertRaises(ValueError):LobbyRewards(self.catalog(),{'reward_selection':{'0':113001}})
        with self.assertRaises(ValueError):LobbyRewards(self.catalog(),{'vehicle_skin_selection':{'300108':601002}})

    def test_account_persistence_and_catalog_counts(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d)/'catalog.json';state=Path(d)/'state.json'
            p.write_text(json.dumps(dict(self.catalog(),owned_gun_skin_ids=[],state_file=str(state))))
            a=LocalCosmetics(p);a.handle(0x54c6,struct.pack('>II',112001,1))
            b=LocalCosmetics(p);self.assertEqual(b.rewards.selected,{'1':112001})
            self.assertIn((0x54c5,b.rewards.owned),b.initial(42))
            before=state.read_bytes();b.handle(0x54c6,struct.pack('>II',112001,2))
            self.assertEqual(state.read_bytes(),before)
        c=LocalCosmetics(Path(__file__).resolve().parents[1]/'config/cosmetics.json')
        self.assertEqual((len(c.ids),len(c.characters),len(c.clothes),len(c.accessories)),(450,361,189,197))
        self.assertEqual([len(c.rewards.groups[g])for g in (0,1,2,4,6,11,15)],( [14,12,8,293,502,119,105]))
