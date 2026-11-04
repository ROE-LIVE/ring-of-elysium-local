"""Локальный каталог внешности2022; владение и выбор — отдельные сообщения."""
import json
from pathlib import Path
import struct
from base_character_2022 import validate_head,login_head_span,patch_login_head,decode_reset_finish,reset_finish_reply,appearance_record,default_head
from local_clothing_2022 import ClothingSelection
from lobby_rewards_2022 import LobbyRewards


def counted_words(ids, maximum):
    if len(ids) > maximum or any(type(x) is not int or not 0 < x <= 0xffffffff for x in ids) or len(set(ids)) != len(ids):
        raise ValueError('Неверный локальный каталог U32')
    return struct.pack('>I', len(ids)) + b''.join(struct.pack('>I', x) for x in ids)


def gun_skin_sync(ids):
    ids = tuple(ids)
    counted_words(ids, 600)
    # Decoder140c8cca0 v117; каждый вложенный140c26650 ограничен300.
    return counted_words(ids[:300],300) + counted_words(ids[300:],300)


def character_container(ids):
    ids = tuple(ids)
    # CHARACTER_CONT: два набора пяти контейнеров, каждый максимум400.
    return counted_words(ids,400) + bytes(9*4)


def accessory_container(ids):
    ids = tuple(ids)
    counted_words(ids,240)
    # Первая/третья части — владение, средняя — второй отдельный список.
    return b''.join(struct.pack('>I',len(part)) + b''.join(struct.pack('>II',x,1) for x in part)
                    for part in (ids[:120],(),ids[120:]))


def clothing_inventory(ids, uid, container=2):
    ids = tuple(ids)
    counted_words(ids,255)
    if type(container) is not int or container not in (2,6):
        raise ValueError('Неподдержанный контейнер одежды')
    records = []
    for index, definition in enumerate(ids):
        record = bytearray(82)
        record[:4] = bytes((container,index,1,0))
        struct.pack_into('>IQ',record,4,definition,0x1d00000000000000+definition)
        struct.pack_into('>H',record,80,1)
        records.append(bytes(record))
    return struct.pack('>I',len(records)) + b''.join(records) + struct.pack('>QB',uid,0)


class LocalCosmetics:
    def __init__(self,path):
        catalog_path = Path(path)
        if catalog_path.stat().st_size > 262144:
            raise ValueError('Слишком большой каталог внешности')
        value = json.loads(catalog_path.read_text())
        self.ids = tuple(value['owned_gun_skin_ids'])
        self.sync = gun_skin_sync(self.ids)
        self.skin_weapons = value.get('weapon_skin_to_weapon', {})
        if (not isinstance(self.skin_weapons, dict)
                or any(not isinstance(k, str) or not k.isascii() or not k.isdecimal()
                       or str(int(k)) != k or int(k) not in self.ids
                       or type(v) is not int or not 0 < v <= 0xffffffff
                       for k, v in self.skin_weapons.items())
                or self.skin_weapons and set(map(int, self.skin_weapons)) != set(self.ids)):
            raise ValueError('Неверная привязка скинов к оружию')
        self.characters = tuple(value.get('owned_character_ids',[]))
        self.accessories = tuple(value.get('owned_accessory_ids',[]))
        self.clothes = tuple(value.get('owned_clothing_ids',[]))
        # Исследовательский контроль: OnSaveEquip использует source container6.
        self.clothing_container = value.get('clothing_inventory_container',2)
        clothing_inventory((),1,self.clothing_container)
        self.state_path = Path(value['state_file']) if value.get('state_file') else None
        if self.state_path and not self.state_path.is_absolute():
            self.state_path = catalog_path.parent / self.state_path
        self.base_defaults=value.get('base_character_defaults',{})
        self.base_heads={}
        self.base_head = None
        self.gun_avatar = 0
        self.character_selection = {}
        self.avatar = bytes(20)
        self.avatar_applied = False
        # Адресный opt-in для проверки холодного default wardrobe.
        self.initialize_default_avatar = value.get('initialize_default_avatar', False)
        if type(self.initialize_default_avatar) is not bool:
            raise ValueError('initialize_default_avatar должен быть bool')
        self.character_groups = value.get('character_groups',{})
        self.selected = {}
        self.accessory_selection = {}
        saved = {}
        if self.state_path and self.state_path.exists():
            if self.state_path.stat().st_size > 65536:
                raise ValueError('Слишком большой локальный выбор внешности')
            saved = json.loads(self.state_path.read_text())
            head=saved.get('base_head_hex')
            if head is not None:
                if not isinstance(head,str)or len(head)>2680:raise ValueError('Неверный сохранённый базовый персонаж')
                self.base_head=validate_head(bytes.fromhex(head))
            heads=saved.get('base_heads',{})
            if not isinstance(heads,dict)or any(k not in('0','1')or not isinstance(v,str)or len(v)>2680 for k,v in heads.items()):
                raise ValueError('Неверные сохранённые базовые лица')
            for k,v in heads.items():
                h=validate_head(bytes.fromhex(v))
                if str(struct.unpack_from('>I',h)[0])!=k:raise ValueError('Пол не совпал с записью лица')
                self.base_heads[k]=h
            self.gun_avatar=saved.get('lobby_gun_avatar',0)
            if type(self.gun_avatar)is not int or not 0<=self.gun_avatar<=0xffffffff:raise ValueError('Неверное оружие лобби')
            self.character_selection=saved.get('character_selection',{})
            if (not isinstance(self.character_selection,dict)or len(self.character_selection)>100
                    or any(type(v)is not int or v not in self.characters
                        or str(self.character_groups.get(str(v),'id:'+str(v)))!=k
                        for k,v in self.character_selection.items())):
                raise ValueError('Неверный выбор вариантов персонажа')
            selected = saved.get('gun_skins', {})
            if (not isinstance(selected, dict) or len(selected) > 300
                    or any(not isinstance(k, str) or not k.isascii() or not k.isdecimal()
                           or str(int(k)) != k or not self.valid_skin(int(k), v)
                           for k, v in selected.items())):
                raise ValueError('Неверный сохранённый выбор оружейного скина')
            self.selected = {int(k): v for k, v in selected.items()}
            avatar = saved.get('avatar',[0]*5)
            if (len(avatar)!=5 or any(type(x)is not int or not 0<=x<=0xffffffff for x in avatar)
                    or avatar[0]and avatar[0]not in self.characters):
                raise ValueError('Сохранённый персонаж отсутствует в каталоге')
            self.avatar = struct.pack('>5I',*avatar)
            self.avatar_applied = saved.get('avatar_applied',False) is True
            for row in saved.get('accessory_selection',[]):
                slot,index,item,flag = row
                if not 0 < slot <= 0xffffffff or not 0 <= index < 6 or item not in self.accessories or flag not in (0,1):
                    raise ValueError('Неверный сохранённый брелок')
                self.accessory_selection[(slot,index)] = (item,flag)
        self.rewards = LobbyRewards(value,saved)
        self.wardrobe = ClothingSelection(self.clothes, value.get('clothing_equipment_slots',{}), saved)
        # Проверка всех границ ещё до создания сокетов.
        self.initial(1)

    def choose_base_gender(self,gender):
        if type(gender)is not int or gender not in(0,1):raise ValueError('Пол:0/1')
        if self.base_head is not None:
            self.base_heads[str(struct.unpack_from('>I',self.base_head)[0])]=self.base_head
        if str(gender)not in self.base_heads and str(gender)not in self.base_defaults:
            raise ValueError('На сервере не подготовлен базовый персонаж: обновите каталог')
        self.base_head=self.base_heads.get(str(gender)) or default_head(gender,self.base_defaults)
        self.avatar_applied=False
        self.save()

    def valid_skin(self, weapon, skin):
        if (type(weapon) is not int or not 0 < weapon <= 0xffffffff
                or type(skin) is not int or skin != 0 and skin not in self.ids):
            return False
        if not self.skin_weapons:
            return True
        return (self.skin_weapons.get(str(skin)) == weapon if skin
                else weapon in self.skin_weapons.values())

    def initial(self,uid):
        packets = [self.cache_primer(),(0x54e1,self.sync)]
        if self.rewards.enabled:
            packets.extend([(0x54c5,self.rewards.owned),(0x54c9,self.rewards.equipped(self.gun_avatar,self.selected.values()))])
        # 54E3→1412B6D10 обновляет map выбора по weapon ID.
        # 54E5→1412B69C0 копирует другой контейнер по object+118;
        # холодный324 показал, что он не восстанавливает выбранный skin.
        packets.extend((0x54e3,struct.pack('>III',0,weapon,skin))
                       for weapon,skin in sorted(self.selected.items()))
        if self.characters:packets.append((0x73aa,character_container(self.characters)))
        if self.accessories:packets.append((0x73b0,accessory_container(self.accessories)))
        if any(self.avatar) or self.initialize_default_avatar:packets.append((0x73a1,self.avatar_sync()))
        # Полный73B1→1412E0370 требует уже существующий cache profile.
        # EquipRSP→1412E0770 вызывает GetOrCreate140D9F130 для своего actor.
        for (slot,index), (item,flag) in sorted(self.accessory_selection.items()):
            packets.append((0x73b3,struct.pack('>4IB',0,slot,index,item,flag)))
        if self.accessory_selection:packets.append((0x73b1,self.accessory_sync()))
        if self.clothes:
            packets.append((0x5fb,self.wardrobe.snapshot(uid) if self.clothing_container == 6
                            else clothing_inventory(self.clothes,uid,self.clothing_container)))
        return packets

    def avatar_sync(self):
        return self.avatar + bytes((int(self.avatar_applied),)) + counted_words(self.character_selection.values(),100)

    def appearance_replies(self,uid):
        """703F/type3 обновляет модель команды без посещения Accessories.

        Схема140C4FF40/140C4FE50 и ROE.Nexus CharacterModule/CosmeticsSync.
        В нашем локальном lobby proxy создаётся team_id=1. Для базового лица
        используется kind1 с сохранённым ActorHeadCfg вместо skin-kind2.
        """
        replies=[]
        if self.base_head is not None or struct.unpack_from('>I',self.avatar)[0]:
            record=appearance_record(uid,self.avatar,self.avatar_applied,self.base_head,
                self.wardrobe.equipped,self.gun_avatar)
            replies.append((0x703f,struct.pack('>QI',1,3)+record))
        replies.append((0x73a1,self.avatar_sync()))
        return replies

    def apply_login_profile(self,body):
        start,end=login_head_span(body)
        if self.base_head is None:
            self.base_head=validate_head(body[start:end])
        result=patch_login_head(body,self.base_head)
        return result

    def accessory_sync(self):
        groups = {}
        for (slot,index), (item,flag) in sorted(self.accessory_selection.items()):
            # Sync140da0980 хранит пару item,index; RSP140da0b60 — index,item.
            groups.setdefault(slot,[]).append((item,index,flag))
        if len(groups) > 400:raise ValueError('Слишком много accessory-групп')
        return struct.pack('>I',len(groups)) + b''.join(
            struct.pack('>II',slot,len(rows)) + b''.join(struct.pack('>IIB',*row) for row in rows)
            for slot,rows in sorted(groups.items()))

    def save(self):
        if self.state_path:
            self.state_path.parent.mkdir(parents=True,exist_ok=True)
            temporary = self.state_path.with_suffix('.tmp')
            if self.base_head is not None:self.base_heads[str(struct.unpack_from('>I',self.base_head)[0])]=self.base_head
            value = {'base_heads':{k:v.hex()for k,v in self.base_heads.items()},'gun_skins':self.selected,'avatar':list(struct.unpack('>5I',self.avatar)),
                     'avatar_applied':self.avatar_applied,'character_selection':self.character_selection,
                     'base_head_hex':self.base_head.hex()if self.base_head is not None else None,
                     'lobby_gun_avatar':self.gun_avatar,
                     'accessory_selection':[[*key,*value] for key,value in sorted(self.accessory_selection.items())]}
            if self.clothes:value.update(self.wardrobe.state())
            if self.rewards.enabled:value.update(self.rewards.state())
            temporary.write_text(json.dumps(value,indent=2)+'\n')
            temporary.replace(self.state_path)

    @staticmethod
    def cache_primer():
        # 1412E082B вызывает GetOrCreate140D9F130 до работы с descriptor.
        # Нулевой descriptor не находится в таблице140DA0BA4..0C45 и не
        # добавляет аксессуар; это адресная инициализация cache, не владение.
        return (0x73b3,bytes(17))

    def handle(self,code,body,uid=1):
        replies,action=self._handle(code,body,uid)
        if action in ('equip_character','apply_character','select_character','move_clothing',
                      'base_editor_saved','choose_weapon'):
            replies=[self.cache_primer(),*replies]
        return replies,action

    def _handle(self,code,body,uid=1):
        packets,action=self.rewards.handle(code,body,self.gun_avatar,self.selected.values())
        if action:
            if action=='reward_changed':self.save()
            return packets,action
        if code == 0x3e80 and self.clothing_container == 6:
            packets,action = self.wardrobe.handle(body,uid)
            if action == 'move_clothing':
                # Одежда редактирует базовую модель, не заменяет скин-костюм.
                self.avatar_applied=False;self.save()
                packets.extend(self.appearance_replies(uid))
            return packets,action

        if code==0x30d and 2<=len(body)<=66:
            # Бесплатный редактор пола/лица: никакой платёжной логики в демо.
            return [(0x30e,bytes(4)+body[2:])],'base_editor_open'
        if code==0x30f:
            try:save,head=decode_reset_finish(body)
            except ValueError:return [],'base_editor_invalid'
            if save:
                self.base_head=head;self.avatar_applied=False;self.save()
            replies=[(0x310,reset_finish_reply(save,head))]
            if save:replies.extend(self.appearance_replies(uid))
            return replies,('base_editor_saved'if save else 'base_editor_cancelled')

        if code == 0x73a2 and len(body) == 20:
            selected = struct.unpack('>5I',body)
            if selected[0] and selected[0] not in self.characters:
                return [(0x73a3,struct.pack('>I',1))],'character_not_owned'
            self.avatar = body
            self.save()
            return [(0x73a3,bytes(4)),*self.appearance_replies(uid)],'equip_character'
        if code == 0x73ab and body in (b'\x00',b'\x01'):
            self.avatar_applied = bool(body[0])
            self.save()
            return [(0x73ac,bytes(4)),*self.appearance_replies(uid)],'apply_character'
        if code == 0x73ad and len(body) == 4:
            selected = struct.unpack('>I',body)[0]
            if selected not in self.characters:
                return [(0x73ae,struct.pack('>I',1)+counted_words(self.character_selection.values(),100))],'character_not_owned'
            group=str(self.character_groups.get(str(selected),'id:'+str(selected)))
            if group not in self.character_selection and len(self.character_selection)>=100:
                return [(0x73ae,struct.pack('>II',1,0))],'character_selection_limit'
            self.character_selection[group]=selected;self.save()
            return [(0x73ae,bytes(4)+counted_words(self.character_selection.values(),100))],'select_character'

        if code == 0x73b2 and len(body) == 13:
            slot,index,item,flag = struct.unpack('>3IB',body)
            slots = {key[0] for key in self.accessory_selection}
            if slot == 0 or index >= 6 or item not in self.accessories or flag not in (0,1) or slot not in slots and len(slots) >= 400:
                return [(0x73b3,struct.pack('>I',1)+body)],'accessory_not_owned'
            self.accessory_selection[(slot,index)] = (item,flag)
            self.save()
            return [(0x73b3,bytes(4)+body),(0x73b1,self.accessory_sync())],'equip_accessory'

        if code in (0x73b6,0x73b7) and len(body) == 1:
            if code == 0x73b6:
                return [(0x73b1,self.accessory_sync())],'sync_accessory_selection'
            return [(0x73b0,accessory_container(self.accessories))],'sync_accessory_catalog'

        if code == 0x73b4 and len(body) == 8:
            slot,index = struct.unpack('>II',body)
            selected = self.accessory_selection.get((slot,index))
            # 1412E0B60: result, descriptor, index, rental; не item ID.
            if selected is None:
                return [(0x73b5,struct.pack('>3IB',1,slot,index,0))],'accessory_slot_empty'
            _,flag = self.accessory_selection.pop((slot,index))
            self.save()
            return [(0x73b5,struct.pack('>3IB',0,slot,index,flag)),
                    (0x73b1,self.accessory_sync())],'unequip_accessory'

        if code == 0x73b8 and len(body) == 12:
            slot,first,second = struct.unpack('>III',body)
            a=self.accessory_selection.get((slot,first),(0,0))
            b=self.accessory_selection.get((slot,second),(0,0))
            valid=slot>0 and first<6 and second<6 and first!=second and a[0]!=0
            if valid:
                self.accessory_selection.pop((slot,first),None)
                self.accessory_selection.pop((slot,second),None)
                if b[0]:self.accessory_selection[(slot,first)]=b
                if a[0]:self.accessory_selection[(slot,second)]=a
                self.save()
            # 1412E0E80: два назначения index/item; затем два rental-флага.
            result=struct.pack('>6I2B',0 if valid else 1,slot,first,b[0],second,a[0],b[1],a[1])
            return [(0x73b9,result)]+([(0x73b1,self.accessory_sync())] if valid else []),('swap_accessory' if valid else 'accessory_swap_invalid')

        if code == 0x54df and len(body) == 4:
            self.gun_avatar=struct.unpack('>I',body)[0];self.save()
            return [(0x54e0,struct.pack('>I',0)+body),*self.appearance_replies(uid)],'choose_weapon'
        if code == 0x54e2 and len(body) == 8:
            weapon,skin = struct.unpack('>II',body)
            if not self.valid_skin(weapon, skin) or weapon not in self.selected and len(self.selected) >= 300:
                return [(0x54e3,struct.pack('>III',1,weapon,skin))],'skin_not_owned'
            self.selected[weapon] = skin
            self.save()
            return [(0x54e3,struct.pack('>III',0,weapon,skin))],'equip_gun_skin'
        return [],None
