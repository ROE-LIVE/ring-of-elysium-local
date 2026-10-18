"""Собственный controller лут→safe→эвакуация на измеренном графе2022.

Один NPC/одна диагностическая сессия. Не исходный AI, не общая комната.
Инвентарь NPC отделён от own; в землю коммитятся только её изменения.
"""
from copy import deepcopy
from dataclasses import replace
import math
import struct

from weapon_probe_2022 import WeaponState
from peer_equipment_2022 import encode_peer_equipment


class BotController:
    def __init__(self, actor, player_weapon):
        self.actor = actor
        self.config = actor.fixture.behavior
        self.graph = actor.fixture.ground_route
        self.points = dict(self.graph.nodes)
        self.inventory = WeaponState(replace(player_weapon.fixture,gun_on_start=False,
                                    reserve=0,starting_equipment=(),starter_items=(),
                                    winter_starter_inventory=False,
                                    cosmetics_config_file=None),actor.fixture.uid)
        self.phase = 'waiting'
        self.started = None
        self.goal = None
        self.pending = list(self.config['loot_indexes'])
        self.next_attempt = 0
        self.last_block = None
        self.finished = False
        self.actor.fixture = replace(actor.fixture,speed=0)

    def event(self, action, **fields):
        return dict(action=action,uid=hex(self.actor.fixture.uid),experimental=True,
                    controller='diagnostic_graph',**fields)

    def route_to(self, goal):
        start = min(self.points,key=lambda n:math.dist(self.actor.position,self.points[n]))
        # Для поворота маршрута ждём измеренного узла, не прыгаем к нему.
        if math.dist(self.actor.position,self.points[start]) > 5:
            return False
        nodes = self.graph.path(start,goal)
        self.goal = goal
        if len(nodes) == 1:
            self.actor.fixture = replace(self.actor.fixture,speed=0)
        else:
            positions = tuple(self.points[n] for n in nodes)
            self.actor.fixture = replace(self.actor.fixture,waypoints=positions,
                                         speed=self.config['speed_cm_seconds'])
            self.actor.waypoint = 1
            self.actor.motion_path_once = True
            self.actor.last_move = None
        return True

    def arrived(self):
        return self.goal is not None and math.dist(self.actor.position,self.points[self.goal]) <= 5

    @staticmethod
    def safe(position, world):
        x0,y0,x1,y1 = world.fixture.hazard
        if x0 <= position[0] <= x1 and y0 <= position[1] <= y1:
            return False
        grid = world.fixture.region_grid
        if grid is None:
            return True
        regions = grid.regions(position)
        if world.fixture.zero_region_is_frozen and hasattr(grid,'region_id') and grid.region_id(position) in (0,None):
            return False
        return bool(regions) and not regions <= world.closed

    def take(self, player_weapon, index):
        item = player_weapon.loot_registry.get(index)
        if (item is None or index in player_weapon.picked_loot
                or item.entity_uid not in player_weapon.available_loot
                and not (item == player_weapon.fixture.loot and player_weapon.loot_available)):
            return [], self.event('bot_loot_rejected',index=index,reason='unavailable')
        if item.definition not in (10402,30004):
            return [], self.event('bot_loot_rejected',index=index,reason='unsupported_bot_item')
        if math.dist(self.actor.position,item.position) > 150:
            return [], self.event('bot_loot_rejected',index=index,reason='distance')
        # Готовим состояние полностью, затем коммитим. Own inventory не выдаётся.
        staged = deepcopy(self.inventory)
        staged.loot_registry = dict(player_weapon.loot_registry)
        staged.available_loot = set(player_weapon.available_loot)
        staged.picked_loot = set(player_weapon.picked_loot)
        staged.loot_available = player_weapon.loot_available
        staged.loot_picked = player_weapon.loot_picked
        # Собственный счётчик NPC выделяем в отдельный namespace, чтобы
        # предмет игрока и новый предмет бота не получили одинаковый UID.
        staged.instance_counter = max(staged.instance_counter,0x100000)
        staged.update_position(self.actor.position)
        request = struct.pack('>IIQBHB3iB',index,0,0,0,0,1,*map(round,self.actor.position),0)
        packets,result = staged.handle(0x3b63,request)
        if result.get('action') != 'pickup' or result.get('quantity',0) <= 0:
            return [], self.event('bot_loot_rejected',index=index,reason=result.get('reason','capacity'))
        # Выбираем оружие NPC, но не посылаем его5FB/4A0 в own actor.
        if staged.guns:
            staged.hand_slot = min(staged.guns)
        equipment = encode_peer_equipment(staged,self.actor.fixture.uid)
        ground = [(code,body) for code,body in packets if code in (0x82b,0x821)]
        self.inventory = staged
        player_weapon.loot_registry[index] = staged.loot_registry[index]
        player_weapon.picked_loot.update(staged.picked_loot)
        if index in staged.picked_loot:
            player_weapon.available_loot.discard(item.entity_uid)
            if item == player_weapon.fixture.loot:
                player_weapon.loot_picked = True
                player_weapon.loot_available = False
        return ground+[(0x547,equipment)],self.event('bot_loot_pickup',index=index,
                definition=item.definition,quantity=result['quantity'],remaining=result['remaining'],
                npc_reserve=staged.reserve,npc_guns={slot:gun.definition for slot,gun in staged.guns.items()})

    def poll(self, now, player_weapon, world, vehicles=None):
        if not self.actor.started or not self.actor.hp or self.finished:
            return [], []
        if self.started is None:
            self.started = now
        if now-self.started < self.config['after_seconds']:
            return [], []
        packets,events = [],[]
        if self.phase == 'waiting':
            self.phase = 'looting'
            events.append(self.event('bot_behavior_begin'))
        if self.phase == 'looting':
            if self.pending:
                index = self.pending[0]
                item = player_weapon.loot_registry.get(index)
                if item is None or index in player_weapon.picked_loot:
                    self.pending.pop(0)
                    events.append(self.event('bot_loot_rejected',index=index,reason='unavailable'))
                elif math.dist(self.actor.position,item.position) <= 150:
                    output,event = self.take(player_weapon,index)
                    packets.extend(output);events.append(event);self.pending.pop(0)
                elif self.goal is None:
                    node = min(self.points,key=lambda n:math.dist(self.points[n],item.position))
                    if math.dist(self.points[node],item.position) > 150:
                        self.pending.pop(0);events.append(self.event('bot_loot_rejected',index=index,reason='outside_graph'))
                    elif self.route_to(node):
                        events.append(self.event('bot_loot_route',index=index,goal=node))
                elif self.arrived():
                    self.actor.fixture = replace(self.actor.fixture,speed=0)
                    self.goal = None
                return packets,events
            self.goal = None;self.phase = 'seeking_safe'
        if self.phase == 'seeking_safe':
            if self.safe(self.actor.position,world):
                self.actor.fixture = replace(self.actor.fixture,speed=0)
                self.phase = 'seeking_evac';self.goal = None
                events.append(self.event('bot_safe_reached',position=self.actor.position))
            elif self.goal is None or not self.safe(self.points[self.goal],world):
                start = min(self.points,key=lambda n:math.dist(self.actor.position,self.points[n]))
                choices=[]
                for node,position in self.graph.nodes:
                    if self.safe(position,world):
                        try:path=self.graph.path(start,node)
                        except ValueError:continue
                        cost=sum(math.dist(self.points[a],self.points[b]) for a,b in zip(path,path[1:]))
                        choices.append((cost,node))
                if choices and self.route_to(min(choices)[1]):
                    events.append(self.event('bot_safe_route',goal=self.goal))
                elif not choices and self.last_block != 'no_safe_node':
                    self.last_block = 'no_safe_node';self.actor.fixture = replace(self.actor.fixture,speed=0)
                    events.append(self.event('bot_safe_blocked',reason='no_safe_node'))
        if self.phase == 'seeking_evac' and now >= self.next_attempt:
            self.next_attempt = now+5
            helicopter = next(((uid,v) for uid,v in (vehicles.vehicles.items() if vehicles else [])
                               if v['configuration']==6),None)
            reason = 'no_helicopter'
            if helicopter:
                uid,vehicle = helicopter
                target = vehicle['position']
                node = min(self.points,key=lambda n:math.hypot(self.points[n][0]-target[0],self.points[n][1]-target[1]))
                distance = math.hypot(self.points[node][0]-target[0],self.points[node][1]-target[1])
                reason = 'outside_verified_graph' if distance > 750 else 'rope_and_boarding_unimplemented'
                if distance <= 750 and self.goal != node and self.route_to(node):
                    events.append(self.event('bot_evac_route',goal=node,vehicle=hex(uid)))
            if self.last_block != reason:
                self.last_block = reason
                events.append(self.event('bot_evac_blocked',reason=reason))
        return packets,events
