"""Базовое лицо/пол2022: ActorHeadCfg, редактор030D/030F и LOGIN_WORLD2EF.

Сверено с read-only ROE.Nexus ActorHeadCfg{,1,2}/ActorModule/UserCfg и
первичными decoder140BD0450/140BD09A0/140BDBC30. Не профиль скина73A1.
"""
import math
import struct

HEAD_FIXED = 140
HEAD_MAX = HEAD_FIXED + 30 * 40


def head_end(data, at=0):
    if at < 0 or len(data)-at < HEAD_FIXED:
        raise ValueError('Обрыв ActorHeadCfg2022')
    count=struct.unpack_from('>I',data,at+136)[0]
    if count>30 or len(data)-at<HEAD_FIXED+40*count:
        raise ValueError('Неверный массив FaceShaping')
    gender=struct.unpack_from('>I',data,at)[0]
    if gender not in (0,1):raise ValueError('Пол базового персонажа:0/1')
    offsets=[12,32,68,72,*range(84,136,4)]
    offsets.extend(HEAD_FIXED+i*40+j for i in range(count)for j in range(4,40,4))
    if any(not math.isfinite(struct.unpack_from('>f',data,at+offset)[0])for offset in offsets):
        raise ValueError('Неконечный параметр ActorHeadCfg')
    return at+HEAD_FIXED+40*count


def validate_head(head):
    if head_end(head)!=len(head):raise ValueError('Лишние данные ActorHeadCfg')
    return bytes(head)


def login_head_span(body):
    if (len(body)<41 or struct.unpack_from('>I',body)[0]!=0
            or struct.unpack_from('>I',body,16)[0]!=1):
        raise ValueError('LOGIN_WORLD требует одну успешную запись')
    size=struct.unpack_from('>I',body,32)[0]
    if not 1<=size<=128 or len(body)<41+size or body[35+size]!=0:raise ValueError('Неверное имя LOGIN_WORLD')
    start=41+size
    return start,head_end(body,start)


def patch_login_head(body,head):
    validate_head(head);start,end=login_head_span(body)
    return bytes(body[:start])+head+bytes(body[end:])


def decode_reset_finish(body):
    if not body or body[0]not in(0,1):raise ValueError('Неверное сохранение внешности')
    head=validate_head(body[1:])
    return bool(body[0]),head


def reset_finish_reply(saved,head,result=0):
    validate_head(head)
    return bytes((int(saved),))+struct.pack('>I',result)+head+bytes(12)


def appearance_record(uid,avatar,applied,head,clothes,gun_avatar=0):
    """703F/type3: skin-kind2 либо созданное лицо-kind1, затем одежда."""
    if type(uid)is not int or not 0<uid<2**64 or len(avatar)!=20:
        raise ValueError('Неверная идентичность внешности')
    created=head is not None and not applied
    model=validate_head(head)if created else avatar
    kind=1 if created else 2
    entries=sorted(clothes.items())
    if len(entries)>30 or any(type(k)is not int or not 0<=k<30 or type(v)is not int or not 0<v<=0xffffffff for k,v in entries):
        raise ValueError('Неверные слоты внешности')
    return (struct.pack('>QI',uid,kind)+model+bytes((0 if created else int(applied),))
            +struct.pack('>I',len(entries))+b''.join(struct.pack('>BI',k,v)for k,v in entries)
            +struct.pack('>II',0,gun_avatar))


def default_head(gender,config):
    """Начальное лицо по DefaultMakeupConfigTable, без заимствования чужой формы.

    Морфы пустые; неопределённые параметры нейтральны. Это наш начальный
    пресет. После редактора сохраняется полный штатный ActorHeadCfg клиента.
    """
    if type(gender)is not int or gender not in(0,1):raise ValueError('Пол:0/1')
    row=config[str(gender)];data=bytearray(HEAD_FIXED)
    def integer(index,name):struct.pack_into('>I',data,index*4,int(row[name])&0xffffffff)
    struct.pack_into('>I',data,0,gender)
    for index,name in ((1,'m_iFaceID'),(2,'m_iDefaultHairID'),(5,'m_iDefaultBeardID'),
            (6,'m_iDefaultLipsID'),(7,'m_iDefaultEyebrowID'),(9,'m_iDefaultPupilID'),
            (10,'m_iDefaultEyelashID'),(11,'m_iDefaultSkinColorID'),(12,'m_iDefaultEyeLinerID'),
            (13,'m_iDefaultEyeShadowID'),(14,'m_iDefaultBlusherID'),(15,'m_iDefaultTattooID'),
            (16,'m_iDefaultNormalDetailID'),(19,'m_iDefaultLipsColorID'),(20,'m_iDefaultNormalWrinkleID')):
        integer(index,name)
    values={8:float(row['mPupilSize']),17:max(0,float(row['mBlusherAreaScale'])),
            18:float(row['mSkinGlossFactor']),21:1.,23:float(row['mLipGlossFactor']),
            24:float(row['mTattooSize']),26:1.,27:1.,31:1.,32:1.,33:float(row['mEyelashScale'])}
    for index,value in values.items():struct.pack_into('>f',data,index*4,value)
    return validate_head(data)
