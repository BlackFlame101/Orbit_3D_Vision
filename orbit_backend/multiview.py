"""C2-C3 role identities and narrowly audited B4 compatibility. No model imports."""
import json
import re
from collections.abc import Mapping
from pathlib import Path

from .inference import fingerprint, sha256, file_digest

ROLES = ('front', 'left', 'back', 'right')
VIEW_INDICES = {'front': 0, 'left': 1, 'back': 2, 'right': 3}
MAPPING_REVISION = 'hunyuan3d-2mv-cardinal-v1'


def canonical_roles(mode, roles):
    roles=list(roles)
    if mode not in ('front_only','multiview') or len(roles)!=len(set(roles)) or any(r not in ROLES for r in roles):
        raise ValueError('Unsupported reconstruction mode, duplicate role, or unknown model role.')
    selected=tuple(r for r in ROLES if r in roles)
    if (mode=='front_only' and selected!=('front',)) or (mode=='multiview' and ('front' not in selected or not 2<=len(selected)<=4)):
        raise ValueError('Use front_only with front, or multiview with front plus selected left/back/right views.')
    return selected


def selection_identity(images, settings, manifest, mode):
    roles=canonical_roles(mode,images)
    _,legacy=fingerprint(images['front'],settings,manifest)
    hashes={role:sha256(images[role]) for role in roles}
    identity={'schema':2,'mode':mode,'mappingRevision':MAPPING_REVISION,'views':list(roles),
              'modelViewIndices':{r:VIEW_INDICES[r] for r in roles},'inputHashes':hashes,
              'inputSha256':hashes['front'],'config':legacy['config'],'runner':manifest}
    return identity_key(identity),identity


def identity_key(identity):
    return sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode())


def identity_hashes(identity):
    if 'schema' not in identity:
        if any(k in identity for k in ('mode','inputHashes','views','mappingRevision')):
            raise ValueError('Incomplete legacy identity.')
        hashes={'front':identity['inputSha256']}
    elif identity['schema']==2:
        hashes=identity['inputHashes']
        if not isinstance(hashes,dict):raise ValueError('Invalid frozen input hashes.')
        roles=canonical_roles(identity['mode'],hashes)
        if identity['views']!=list(roles) or identity['mappingRevision']!=MAPPING_REVISION or identity['modelViewIndices']!={r:VIEW_INDICES[r] for r in roles} or identity['inputSha256']!=hashes['front']:
            raise ValueError('Frozen viewpoint mapping is inconsistent.')
    else:
        raise ValueError('Unknown frozen identity schema.')
    if any(not isinstance(h,str) or not re.fullmatch('[a-f0-9]{64}',h) for h in hashes.values()):
        raise ValueError('Invalid frozen input checksum.')
    return {r:hashes[r] for r in ROLES if r in hashes}


def verified_paths(identity, paths):
    hashes=identity_hashes(identity)
    if isinstance(paths,(str,Path)):paths={'front':Path(paths)}
    if not isinstance(paths,Mapping) or set(paths)!=set(hashes):
        raise ValueError('Snapshot paths must exactly match the selected frozen roles.')
    result={}
    for role in hashes:
        path=Path(paths[role])
        if not path.is_file() or file_digest(path)!=hashes[role]:
            raise ValueError(f'Missing or corrupted immutable {role} snapshot.')
        result[role]=path
    return result


def snapshot_paths(store,payload):
    identity=payload['identity']
    if 'schema' not in identity:
        if 'inputs' in payload:raise ValueError('Legacy payload cannot contain additional views.')
        return verified_paths(identity,store.path(payload['input']))
    paths=payload['inputs']
    if payload.get('input')!=paths.get('front'):
        raise ValueError('Primary front snapshot does not match the selected inputs.')
    return verified_paths(identity,{r:store.path(p) for r,p in paths.items()})


def write_snapshots(store,key,images):
    # DB caller enqueues only after this entire write/verification barrier succeeds.
    # If I/O fails, no job is committed. Already-written immutable files are retained
    # and checked on retry; no file referenced by another job is ever deleted.
    result={}
    for role in ROLES:
        if role not in images:continue
        relative=f'inputs/{key}/{role}.png'
        path=store.path(relative)
        if path.exists():
            if path.read_bytes()!=images[role]:raise ValueError(f'Immutable {role} snapshot failed integrity checks.')
        else:
            store.atomic_bytes(relative,images[role])
        result[role]=relative
    return result


def compatibility_policy():
    try:
        return json.loads(Path(__file__).with_name('cache_compatibility.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):
        return {}


def compatible_runner(previous,current,legacy=False):
    if previous==current:return True
    policy=compatibility_policy()
    audited=policy.get('compatibleCodes',[])+([policy['fromCode']] if legacy and 'fromCode' in policy else [])
    if not policy or previous.get('code') not in audited or current.get('code')!=policy.get('toCode'):
        return False
    # Nothing except this explicitly audited adapter code transition may differ.
    return {k:v for k,v in previous.items() if k!='code'}=={k:v for k,v in current.items() if k!='code'}


def legacy_cached_result(store,conn,identity):
    # Reuse exact C2-C3 identities across the observation-only C5 transition.
    current=identity['runner'];policy=compatibility_policy()
    if policy and current.get('code')==policy.get('toCode'):
        for code in policy.get('compatibleCodes',[]):
            previous={**current,'code':code}
            if not compatible_runner(previous,current):continue
            old_identity={**identity,'runner':previous}
            key=identity_key(old_identity)
            row=conn.execute('SELECT * FROM reconstruction_cache WHERE fingerprint=?',(key,)).fetchone()
            if not row:continue
            try:
                path=store.path(row['model'])
                if json.loads(row['manifest'])==old_identity and path.is_file() and 20<path.stat().st_size<=64*1024*1024 and file_digest(path)==row['sha256']:
                    return {**dict(row),'compatibilityReuse':True,'compatibilityName':'audited-c2-c5-diagnostics'}
            except (OSError,ValueError):continue
    if identity.get('mode')!='front_only':return None
    current=identity['runner'];policy=compatibility_policy()
    if not policy or current.get('code')!=policy.get('toCode'):return None
    old_runner={**current,'code':policy['fromCode']}
    if not compatible_runner(old_runner,current,legacy=True):return None
    old_identity={'inputSha256':identity['inputHashes']['front'],'config':identity['config'],'runner':old_runner}
    old_key=identity_key(old_identity)
    row=conn.execute('SELECT * FROM reconstruction_cache WHERE fingerprint=?',(old_key,)).fetchone()
    if not row:return None
    try:
        if json.loads(row['manifest'])!=old_identity:return None
        path=store.path(row['model'])
        if not path.is_file() or not 20<path.stat().st_size<=64*1024*1024 or file_digest(path)!=row['sha256']:return None
    except (OSError,ValueError):return None
    # Read-only reuse. Do not rewrite, migrate, delete or relabel the legacy row.
    return {**dict(row),'compatibilityReuse':True,'compatibilityName':'audited-b4-front-only'}
