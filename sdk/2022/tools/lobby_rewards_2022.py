"""Постоянная косметика лобби2022: 54C5/54C9, без экономики и аренды.

Схемы ROE.Nexus CosmeticsSync; группы дополнительно сверены с141051AA0.
Это демо-владение каталогом, а не восстановленная история покупок.
"""
import struct

SLOTS={0:0,1:1,2:2,4:4,6:3,11:6,12:7,13:8,14:9,17:11,18:12}


def words(values,limit):
    values=list(values)
    if len(values)>limit or len(set(values))!=len(values) or any(type(x)is not int or not 0<x<2**32 for x in values):
        raise ValueError('Неверный массив косметики')
    return struct.pack('>I',len(values))+b''.join(struct.pack('>I',x)for x in values)


class LobbyRewards:
    def __init__(self,catalog,saved):
        self.groups=catalog.get('owned_reward_groups',[[]for _ in range(19)])
        self.enabled='owned_reward_groups'in catalog
        if not isinstance(self.groups,list)or len(self.groups)!=19:raise ValueError('Нужны19 групп косметики')
        self.owned=b''.join(words(g,600)for g in self.groups)+bytes(4)
        self.defaults=catalog.get('default_reward_ids',{})
        if not isinstance(self.defaults,dict):raise ValueError('Неверные стандартные медиа')
        for g,ids in self.defaults.items():
            if g not in ('4','11','15'):raise ValueError('Неверная группа стандартных медиа')
            words(ids,40)
        self.vehicle_types=catalog.get('reward_vehicle_types',{})
        all_vehicles=set(self.groups[15])|set(self.defaults.get('15',[]))
        if (not isinstance(self.vehicle_types,dict)or set(self.vehicle_types)!={str(x)for x in all_vehicles}
                or any(type(x)is not int or not 0<x<2**32 for x in self.vehicle_types.values())):
            raise ValueError('Неверные типы оформления машин')
        self.selected=self.load(saved.get('reward_selection',{}))
        self.vehicles=saved.get('vehicle_skin_selection',{})
        if (not isinstance(self.vehicles,dict)or len(self.vehicles)>10
                or any(type(v)is not int or v not in self.groups[15]or self.vehicle_types[str(v)]!=int(k)
                       or str(int(k))!=k for k,v in self.vehicles.items())):
            raise ValueError('Неверное сохранённое оформление машин')

    def load(self,value):
        if not isinstance(value,dict):raise ValueError('Неверный выбор косметики')
        for g,item in value.items():
            if g not in tuple(str(x)for x in SLOTS)or type(item)is not int or item not in self.groups[int(g)]:
                raise ValueError('Косметика не принадлежит выбранной группе')
        return dict(value)

    def state(self):
        return dict(reward_selection=self.selected,vehicle_skin_selection=self.vehicles)

    def equipped(self,gun_avatar=0,gun_skins=()):
        slots=[0]*13
        for g,item in self.selected.items():slots[SLOTS[int(g)]]=item
        slots[10]=gun_avatar
        return (struct.pack('>11I',*slots[:11])+words(sorted(self.vehicles.values()),10)
                +bytes(8)+words(sorted(x for x in gun_skins if x),80)+bytes(4)
                +struct.pack('>II',*slots[11:]))

    def handle(self,code,body,gun_avatar=0,gun_skins=()):
        if not self.enabled:return [],None
        sync=lambda:(0x54c9,self.equipped(gun_avatar,gun_skins))
        if code==0x54c4 and len(body)==1:return [(0x54c5,self.owned)],'reward_catalog'
        if code==0x54c8 and len(body)==1:return [sync()],'reward_sync'
        if code not in(0x54c6,0x54ca)or len(body)!=8:return [],None
        item,group=struct.unpack('>II',body);key=str(group)
        known=group in SLOTS or group==15
        allowed=known and (item==0 or item in self.groups[group]or item in self.defaults.get(key,[]))
        if not allowed:return [(code+1,struct.pack('>I',1))],'reward_not_owned'
        clear=code==0x54ca or item==0 or item in self.defaults.get(key,[])
        if group==15:
            if item==0:self.vehicles.clear()
            else:
                subtype=str(self.vehicle_types[str(item)])
                if not clear and subtype not in self.vehicles and len(self.vehicles)>=10:
                    return [(code+1,struct.pack('>I',1))],'reward_vehicle_limit'
                if clear:self.vehicles.pop(subtype,None)
                else:self.vehicles[subtype]=item
        elif clear:self.selected.pop(key,None)
        else:self.selected[key]=item
        return [(code+1,bytes(4)),sync()],'reward_changed'
