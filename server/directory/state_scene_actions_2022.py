"""Явные административные действия одиночного стенда2022, не оригинальная console."""
from copy import deepcopy
import struct

from world_probe_2022 import encode_health
from death_parcel_2022 import DeathParcelState


def validate_state_action(row):
    action = row.get('action')
    parameter = {'set_own_health':'hp','give_ammo':'quantity','damage_npc':'damage'}.get(action)
    if parameter is None:
        raise ValueError('Неизвестное state action')
    allowed = {'id','action','recipient_actor_uid',parameter}
    if action == 'give_ammo':allowed.add('definition')
    if set(row)-allowed:
        raise ValueError('State action не принимает wire payload/неизвестные поля')
    value = row.get(parameter)
    maximum = 100 if action == 'give_ammo' else 1000
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError('State action: неверный '+parameter)
    result = dict(action=action,**{parameter:value})
    if action == 'give_ammo':
        definition = row.get('definition')
        if type(definition) is not int or definition not in (30004,30001,30002,30005):
            raise ValueError('give_ammo: поддержаны12ga/5.56/7.62/.45')
        result['definition'] = definition
    return result


def apply_state_action(state, request, reserved_indexes=()):
    action = request['action']
    event = dict(action=action,accepted=False,administrative=True,experimental=True)
    world,weapon = state.get('world'),state.get('weapon')
    if world is None or weapon is None or getattr(world,'dead',False):
        return [],dict(event,reason='active_alive_world_required')
    if action == 'set_own_health':
        hp = request['hp']
        if not 1 <= hp <= world.fixture.hp:
            return [],dict(event,reason='outside_profile_health')
        body = encode_health(state['actor_uid'],hp)
        before = world.hp;world.hp = hp
        return [(0x1069,body)],dict(event,accepted=True,before=before,hp=hp)
    if action == 'give_ammo':
        definition,quantity = request['definition'],request['quantity']
        if weapon.ammunition_room(definition) < quantity:
            return [],dict(event,reason='insufficient_bag_capacity')
        staged = deepcopy(weapon)
        before = staged.ammunition_quantity(definition)
        staged.set_ammunition_quantity(definition,before+quantity)
        packets = [staged.ammunition_slot_sync(definition),*staged.magazine_syncs(),staged.capacity_sync()]
        weapon.set_ammunition_quantity(definition,before+quantity)
        return packets,dict(event,accepted=True,definition=definition,before=before,quantity=before+quantity)
    actor = state.get('target_actor')
    if actor is None or not actor.started or actor.hp <= 0:
        return [],dict(event,reason='active_npc_required')
    staged_actor = deepcopy(actor)
    packets,result = staged_actor.diagnostic_area_damage(request['damage'])
    # Пакет смерти готовится до commitHP и inventory; malformed fixture
    # не оставляет NPC мёртвым с невыданными предметами.
    corpse_event = None
    inventory = state.get('target_inventory')
    if staged_actor.hp == 0 and inventory is not None:
        staged_inventory = deepcopy(inventory)
        if staged_actor.fixture.armor_definition:
            staged_inventory.equipment_durability[12] = staged_actor.armor_durability
        corpses = deepcopy(state.get('death_parcels',DeathParcelState()))
        loot,corpse_event = corpses.transfer(staged_inventory,actor.position,reserved_indexes)
        packets.extend(loot)
    actor.__dict__.update(staged_actor.__dict__)
    if corpse_event is not None:
        inventory.__dict__.update(staged_inventory.__dict__)
        state['death_parcels'] = corpses
    return packets,dict(event,accepted=True,target=hex(actor.fixture.uid),hp=actor.hp,
                        damage=result['damage'],corpse=corpse_event)
