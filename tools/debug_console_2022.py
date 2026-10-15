"""Собственные debug marker и Lua-снимок публичного HUD2022; не server host."""
import hashlib
from pathlib import Path
import re
import shutil
import uuid


def lua_snapshot(output_name):
    """Только числовые getters из HUD; не перечисляет globals/аккаунт/AUTH."""
    if not isinstance(output_name, str) or not re.fullmatch(r'ROE_Probe_state_[0-9a-f]{12}\.tsv', output_name):
        raise ValueError('Ожидается собственное имя snapshot TSV')
    return '''-- Публичные HUD getters2022; без AUTH и dump globals.
ROE_Probe_snapshot_index=(ROE_Probe_snapshot_index or 0)+1
local f=assert(io.open("''' + output_name + '''","a"))
f:write("snapshot\\t",ROE_Probe_snapshot_index,"\\n")
local function number(name,fn)
 local ok,value=pcall(fn)
 if ok and type(value)=="number" and value==value and math.abs(value)<1e15 then f:write(name,"\\t",string.format("%.6f",value),"\\n") else f:write(name,"\\tunavailable\\n") end
end
number("qs_current_map_id_unclassified",function() return qs.GetCurrentMapId() end)
number("magazine_slot1",function() return qs.GetInventoryWeaponAmmoLoaded(1) end)
number("magazine_slot2",function() return qs.GetInventoryWeaponAmmoLoaded(2) end)
number("magazine_slot3",function() return qs.GetInventoryWeaponAmmoLoaded(3) end)
number("reserve_citori",function() return qs.GetInventoryWeaponAmmoInBag(10402) end)
number("reserve_m4",function() return qs.GetInventoryWeaponAmmoInBag(10201) end)
number("reserve_ak47",function() return qs.GetInventoryWeaponAmmoInBag(10202) end)
number("reserve_glock",function() return qs.GetInventoryWeaponAmmoInBag(20002) end)
number("reserve_de",function() return qs.GetInventoryWeaponAmmoInBag(20003) end)
number("bandages",function() return qs.GetInventoryNumber(70001) end)
number("first_aid",function() return qs.GetInventoryNumber(70002) end)
number("medkit",function() return qs.GetInventoryNumber(70003) end)
number("glider_kit",function() return qs.GetInventoryNumber(200907) end)
number("snowboard_kit",function() return qs.GetInventoryNumber(200906) end)
number("climb_kit",function() return qs.GetInventoryNumber(200904) end)
number("weather_id",function() return qs.GetFinalMapWeather() end)
number("game_day_fraction",function() return qs.GetGameTime() end)
number("body_temperature_raw",function() return qs.GetPlayerRawAttri(qs.ATR_BODY_TEMPERATURE) end)
number("init_equip_type1",function() return qs.GetPlayerRawAttri(qs.ATR_INIT_EQUIP_1) end)
number("init_equip_type2",function() return qs.GetPlayerRawAttri(qs.ATR_INIT_EQUIP_2) end)
number("init_equip_type3",function() return qs.GetPlayerRawAttri(qs.ATR_INIT_EQUIP_3) end)
f:close()
'''


class DebugConsoleSession:
    """Вызывать только для уже проверенной независимой runtime-копии."""
    def __init__(self, runtime, run):
        self.runtime = Path(runtime)
        self.run = Path(run)
        token = uuid.uuid4().hex[:12]
        self.script = self.runtime / ('ROE_Probe_state_' + token + '.lua')
        self.output = self.runtime / ('ROE_Probe_state_' + token + '.tsv')
        self.marker = self.runtime / 'FileDriven/_GM_CONTROL_'
        self.body = lua_snapshot(self.output.name).encode('utf-8')
        self.owned_marker = False
        self.installed = False
        self.command = '/lua assert(loadstring(assert(io.open("' + self.script.name + '")):read("*a")))()'

    def install(self):
        if self.installed:
            raise ValueError('Debug session уже установлен')
        if not self.runtime.is_dir() or not self.run.is_dir():
            raise ValueError('Сначала создать проверенный runtime и run')
        if self.marker.is_symlink() or (self.marker.exists() and not self.marker.is_file()):
            raise ValueError('Необычный существующий debug marker')
        if self.output.exists() or self.output.is_symlink():
            raise ValueError('Snapshot имя занято')
        with self.script.open('xb') as stream:
            stream.write(self.body)
        try:
            self.marker.parent.mkdir(exist_ok=True)
            if not self.marker.exists():
                with self.marker.open('xb'):
                    pass
                self.owned_marker = True
            self.installed = True
            (self.run / 'client-debug-command.txt').write_text(self.command + '\n', encoding='utf-8')
        except BaseException:
            self.close()
            raise
        return self.command

    def close(self):
        try:
            if self.output.is_file() and not self.output.is_symlink():
                # Единственный собственный файл числовых HUD getters.
                if self.output.stat().st_size <= 8 * 1024 * 1024:
                    with self.output.open('rb') as stream, (self.run / 'client-state.tsv').open('wb') as target:
                        shutil.copyfileobj(stream, target)
                    self.output.unlink()
            if self.script.is_file() and not self.script.is_symlink() and self.script.stat().st_size == len(self.body):
                if hashlib.sha256(self.script.read_bytes()).digest() == hashlib.sha256(self.body).digest():
                    self.script.unlink()
        finally:
            if self.owned_marker and self.marker.is_file() and not self.marker.is_symlink() and self.marker.stat().st_size == 0:
                self.marker.unlink()
            self.owned_marker = False
            self.installed = False
