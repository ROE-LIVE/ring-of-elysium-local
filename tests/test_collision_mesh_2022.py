"""Синтетический SFC/RepX: bounds, ближайшая грань и атомарный server guard."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server/directory'))
from collision_mesh_2022 import CollisionMesh,load_collision_meshes
from actor_probe_2022 import ActorFixture,ActorState


class MeshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        # Две грани перекрывают часть плоскости x=2; место внутри AABB
        # за пределами треугольника намеренно остаётся пустым.
        self.raw = (b'<PhysX30Collection version="3.3.4"><PxTriangleMesh>'
                    b'<Points>2 -1000 -1000 2 1000 -1000 2 -1000 1000</Points>'
                    b'<Triangles>0 1 2</Triangles></PxTriangleMesh></PhysX30Collection>')
        self.descriptor = dict(id='synthetic',archive_file='own.sfc',payload_offset=20,
                               sha256=hashlib.sha256(self.raw).hexdigest(),material_id=305,
                               pose=[0,0,0,1,0,0,0])
        self.write(self.raw)

    def write(self, raw):
        # Достаточно корректного literal-only raw LZ4 для синтетического SFC.
        size=len(raw);extension=bytearray();extra=max(0,size-15)
        while extra>=255:extension.append(255);extra-=255
        if size>=15:extension.append(extra)
        packed=bytes([min(size,15)<<4])+bytes(extension)+raw
        self.archive = self.directory/'own.sfc'
        self.archive.write_bytes(bytes(16)+struct.pack('<I',len(packed))+packed+struct.pack('<I',len(raw)))
        self.descriptor['sha256'] = hashlib.sha256(raw).hexdigest()

    def load(self):
        return CollisionMesh.load(self.descriptor,self.directory)

    def test_known_segment_two_sides_and_empty_corner(self):
        mesh = self.load()
        self.assertEqual(mesh.first_hit((0,-100,-100),(4,-100,-100)),(.5,0))
        self.assertEqual(mesh.first_hit((4,-100,-100),(0,-100,-100)),(.5,0))
        self.assertIsNone(mesh.first_hit((0,900,900),(4,900,900)))
        self.assertIsNone(mesh.first_hit((0,-100,-100),(1,-100,-100)))
        self.assertEqual(self.archive.read_bytes()[:16],bytes(16))

    def test_pose_scale_and_quaternion_transform(self):
        self.descriptor.update(pose=[0,0,0,1,371000,544000,259000],scale=[2,1,1])
        mesh = self.load()
        self.assertEqual(mesh.first_hit((371000,543900,258900),(371008,543900,258900)),(.5,0))
        # Поворот90° вокруг Z: плоскость x=2 переходит в y=2.
        q=2**-.5
        self.descriptor.update(pose=[0,0,q,q,0,0,0],scale=[1,1,1])
        self.assertAlmostEqual(self.load().first_hit((100,0,-100),(100,4,-100))[0],.5)

    def test_bvh_nearest_face_instead_of_input_order(self):
        points=[];indices=[]
        # Дальний слой записан первым; больше8граней заставляют строить BVH.
        for x in (4,2):
            for y in range(-4,4):
                offset=len(points)//3
                points.extend((x,y,0,x,y+1,0,x,y,1))
                indices.extend((offset,offset+1,offset+2))
        raw=('<PhysX30Collection><PxTriangleMesh><Points>'+ ' '.join(map(str,points))+
             '</Points><Triangles>'+' '.join(map(str,indices))+'</Triangles></PxTriangleMesh></PhysX30Collection>').encode()
        self.write(raw);mesh=self.load()
        for y in (-3.8,-2.8,-1.8,-.8,.2,1.2,2.2,3.2):
            hit=mesh.first_hit((0,y,.2),(6,y,.2))
            self.assertAlmostEqual(hit[0],1/3)
            self.assertGreaterEqual(hit[1],8)
        self.assertIsNone(mesh.first_hit((0,10,.2),(6,10,.2)))

    def test_hash_truncation_sizes_and_bad_offset_fail(self):
        self.descriptor['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'SHA'):self.load()
        self.descriptor['sha256']=hashlib.sha256(self.raw).hexdigest()
        data=self.archive.read_bytes();self.archive.write_bytes(data[:-1])
        with self.assertRaises(ValueError):self.load()
        self.archive.write_bytes(bytes(16)+struct.pack('<I',2*1024*1024+1))
        with self.assertRaises(ValueError):self.load()
        self.write(self.raw);self.descriptor['payload_offset']=10**9
        with self.assertRaises(ValueError):self.load()

    def test_invalid_geometry_transform_or_descriptor_rejected(self):
        for bad in (None,{},dict(self.descriptor,pose=[0,0,0,0,0,0,0]),
                    dict(self.descriptor,scale=[-1,1,1]),dict(self.descriptor,material_id=True),
                    dict(self.descriptor,pose=[0,0,0,1,float('nan'),0,0])):
            with self.subTest(bad=repr(bad)[:80]),self.assertRaises(ValueError):
                CollisionMesh.load(bad,self.directory)
        for raw in (self.raw.replace(b'0 1 2',b'0 1 9'),self.raw.replace(b'2 -1000',b'nan -1000',1),
                    b'<!DOCTYPE t>'+self.raw,self.raw.replace(b'PhysX30Collection',b'Other')):
            self.write(raw)
            with self.subTest(raw=raw[:60]),self.assertRaises(ValueError):self.load()

    def test_manifest_bounds_unique_ids_and_no_asset_outputs(self):
        path=self.directory/'manifest.json'
        path.write_text(json.dumps({'meshes':[self.descriptor]}))
        self.assertEqual(load_collision_meshes(path)[0].vertex_count,3)
        self.assertEqual(set(p.name for p in self.directory.iterdir()),{'own.sfc','manifest.json'})
        for value in ([],[self.descriptor]*2,[self.descriptor]*9,None):
            path.write_text(json.dumps({'meshes':value}))
            with self.assertRaises(ValueError):load_collision_meshes(path)

    def test_mesh_hit_guard_preserves_hp_armor_dedup_and_feedback(self):
        self.descriptor['pose']=[0,0,0,1,448,0,0]
        # Положительная часть этой плоскости не покрывает impactZ75, поэтому
        # сдвигаем её вверх относительно луча.
        self.descriptor['pose'][6]=300
        fixture=ActorFixture(900,bytes(23),bytes(1516),bytes(40),(900,0,0),((900,0,0),),0,1000,50,
                             collision_meshes=(self.load(),))
        actor=ActorState(fixture);actor.begin(0)
        fire=struct.pack('>6fIBIIfII',0,0,150,900,0,120,7,0,100,0,480,0,0)
        actor.note_fire(fire,{'action':'fire','gun_definition':10201})
        hit=bytearray(106);struct.pack_into('>IQ',hit,0,1,900)
        struct.pack_into('>3f',hit,25,0,0,150);struct.pack_into('>3i',hit,37,900,0,0)
        struct.pack_into('>3f',hit,50,890,0,75);hit[62]=2
        struct.pack_into('>I',hit,88,7);struct.pack_into('>I',hit,96,100)
        actor.armor_durability=20
        packets,event=actor.hit(hit,shooter_uid=10)
        self.assertEqual((packets,event['reason'],event['blocking_mesh']),([],'line_of_sight','synthetic'))
        self.assertEqual((actor.hp,actor.armor_durability,actor.hits),(1000,20,set()))
        actor.fixture=replace(actor.fixture,collision_meshes=())
        packets,event=actor.hit(hit,shooter_uid=10)
        self.assertEqual(event['action'],'hit_damage')
        self.assertIn(0x11eb,[code for code,_ in packets])
