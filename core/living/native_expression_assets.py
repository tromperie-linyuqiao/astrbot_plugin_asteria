"""Manual expression images in the existing journal and private owned files.

Image bytes are inspected read-only and retained unchanged. Metadata and
request receipts share the current LivingJournal transaction; there is no new
database, model, timer, sender or supplied artwork. Async callers use a worker.
Selection reads only human captions/tags and never interprets image contents.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime,timezone
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
import unicodedata
import uuid

from PIL import Image

from .journal import JournalConflict
from .models import canonical,private_scope,scope_key

SCHEMA='tls.expression.asset.v1'
NAMESPACE='tls.expression.assets.v1'
REQUESTS='tls.expression.asset_requests.v1'
MAX_BYTES=3*1024*1024
MAX_PIXELS=50_000_000
MAX_FRAMES=240
MAX_ASSETS=256  # Includes soft-deleted files; deletion cannot evade the limit.
MAX_REQUESTS=1024
_ID=re.compile(r'[a-f0-9]{64}\Z')
_FORMATS={'PNG':('png','image/png'),'JPEG':('jpg','image/jpeg'),
          'GIF':('gif','image/gif'),'WEBP':('webp','image/webp')}
_FIELDS={'schema','scope','id','sha256','media_type','format','width','height','frames','total_pixels',
         'byte_size','caption','tags','enabled','deleted','revision','created_at','updated_at','deleted_at','source'}


class ExpressionAssetConflict(JournalConflict):pass
class ExpressionAssetError(RuntimeError):pass
class _AssetPermission(PermissionError):pass


def _identity(value):
    if not isinstance(value,str) or not _ID.fullmatch(value):raise ValueError('invalid expression asset ID')
    return value


def _revision(value):
    if type(value) is not int or value<1:raise ValueError('positive expected_revision required')


def _annotations(caption,tags,enabled):
    if (not isinstance(caption,str) or len(caption)>300
            or any(ord(char)<32 and char not in '\n\r\t' or ord(char)==127 for char in caption)):
        raise ValueError('caption must contain at most 300 plain characters')
    if not isinstance(tags,(list,tuple)) or len(tags)>16:raise ValueError('at most 16 manual tags required')
    seen=set()
    for tag in tags:
        if (not isinstance(tag,str) or not 1<=len(tag)<=32 or tag!=tag.strip()
                or any(ord(char)<32 or ord(char)==127 for char in tag)):
            raise ValueError('manual tag must contain 1 to 32 plain characters')
        normalized=unicodedata.normalize('NFKC',tag).casefold()
        if normalized in seen:raise ValueError('duplicate manual tag')
        seen.add(normalized)
    if type(enabled) is not bool:raise ValueError('explicit enabled flag required')
    return dict(caption=caption,tags=list(tags),enabled=enabled)


def _inspect(raw):
    if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_BYTES:raise ValueError('image must contain at most 3 MiB')
    try:
        with Image.open(BytesIO(raw)) as image:
            kind=image.format;width,height=image.size;frames=getattr(image,'n_frames',1)
            if kind not in _FORMATS:raise ValueError
            if (type(frames) is not int or not 1<=frames<=MAX_FRAMES or width<1 or height<1
                    or width*height*frames>MAX_PIXELS):raise ValueError
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            for index in range(frames):
                image.seek(index)
                if image.width*image.height>width*height:raise ValueError
                image.load()
        return dict(format=kind,media_type=_FORMATS[kind][1],width=width,height=height,
                    frames=frames,total_pixels=width*height*frames,byte_size=len(raw))
    except Exception:
        raise ValueError('valid bounded PNG, JPEG, GIF or WebP required') from None


def _normalize(text):return ' '.join(unicodedata.normalize('NFKC',text).casefold().split())


def _terms(text):
    result=set(re.findall(r'[a-z0-9]+',text))
    for run in re.findall(r'[\u3400-\u9fff]+',text):
        result.update(run[index:index+2] for index in range(len(run)-1))
        if len(run)==1:result.add(run)
    return result


class NativeExpressionAssets:
    """The synchronous authorizer must be current and safe on worker threads.

    It is checked again inside every mutation transaction. Host/API callers
    also retain their event-loop identity/object checks around worker calls.
    """
    backend='native_expression_assets'

    def __init__(self,journal,assets_root=None,*,authorize,clock=time.time):
        if not callable(authorize) or not callable(clock):raise ValueError('asset authorization and clock required')
        self.journal,self.authorize,self.clock=journal,authorize,clock;self.active=True
        self._parent=Path(journal.path).parent.absolute()
        self._root=Path(assets_root).absolute() if assets_root is not None else self._parent/'expression_assets'
        if self._root==self._parent or not self._root.is_relative_to(self._parent):
            raise ValueError('private asset directory must be inside the journal directory')
        for path in (self._parent,*self._parent.parents,self._root):
            if path.is_symlink() or getattr(path,'is_junction',lambda:False)():
                raise ValueError('linked asset directory refused')
        if self._root.parent!=self._parent:
            raise ValueError('asset directory must be a direct private journal child')

    def _scope(self,scope):
        scope=private_scope(scope)
        try:allowed=self.active and self.authorize(dict(scope)) is True
        except PermissionError:allowed=False
        if not allowed:raise _AssetPermission('expression asset scope unavailable')
        return scope

    def _now(self):
        value=self.clock()
        if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=253402300799:
            raise ValueError('invalid asset clock')
        return float(value),datetime.fromtimestamp(value,timezone.utc).isoformat().replace('+00:00','Z')

    @staticmethod
    @contextmanager
    def _resources():
        try:yield
        except _AssetPermission:raise
        except (OSError,sqlite3.Error):raise ExpressionAssetError('expression asset resource unavailable') from None

    @staticmethod
    def _folder(path,*,create=False):
        try:info=path.lstat()
        except FileNotFoundError:
            if not create:raise ExpressionAssetError('expression asset file unavailable') from None
            try:path.mkdir(mode=0o700)
            except FileExistsError:pass
            info=path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or path.is_symlink()
                or getattr(path,'is_junction',lambda:False)()):
            raise ExpressionAssetError('expression asset directory unavailable')
        if os.name!='nt' and stat.S_IMODE(info.st_mode)&0o077:
            raise ExpressionAssetError('private expression asset directory required')

    def _path(self,scope,row,*,create=False):
        # Every component is derived from validated scope/hash/format, never
        # an uploaded filename or a path accepted from an API request.
        try:
            if self._parent.resolve()!=self._parent:raise ExpressionAssetError('expression asset directory unavailable')
        except (OSError,RuntimeError):raise ExpressionAssetError('expression asset directory unavailable') from None
        self._folder(self._root,create=create)
        directory=self._root/scope_key(scope);self._folder(directory,create=create)
        path=directory/(row['id']+'.'+_FORMATS[row['format']][0])
        if path.is_symlink():raise ExpressionAssetError('expression asset file unavailable')
        try:
            if path.resolve()!=path:raise ExpressionAssetError('expression asset file unavailable')
        except (OSError,RuntimeError):raise ExpressionAssetError('expression asset file unavailable') from None
        return path

    def _read_file(self,scope,row):
        path=self._path(scope,row)
        flags=os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0)
        with os.fdopen(os.open(path,flags),'rb') as source:
            before=os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size!=row['byte_size']:
                raise ExpressionAssetError('expression asset file unavailable')
            raw=source.read(MAX_BYTES+1);after=os.fstat(source.fileno())
        identity=lambda info:(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
        if (identity(before)!=identity(after) or len(raw)!=row['byte_size']
                or hashlib.sha256(raw).hexdigest()!=row['sha256']):
            raise ExpressionAssetError('expression asset file unavailable')
        return raw

    def _install(self,scope,row,raw):
        path=self._path(scope,row,create=True)
        if path.exists():self._read_file(scope,row);return None
        temporary=path.parent/('.upload-'+uuid.uuid4().hex)
        linked=False
        try:
            flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0)
            with os.fdopen(os.open(temporary,flags,0o600),'wb') as target:
                target.write(raw);target.flush();os.fsync(target.fileno())
            try:os.link(temporary,path,follow_symlinks=False);linked=True
            except FileExistsError:self._read_file(scope,row)
        finally:
            temporary.unlink(missing_ok=True)
        if linked:
            info=path.lstat();return path,(info.st_dev,info.st_ino)
        return None

    def _load(self,db,scope,identity):
        record=db.execute('SELECT revision,data FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
            (NAMESPACE,identity,scope_key(scope))).fetchone()
        if record is None:return None
        try:
            _identity(identity)
            row=json.loads(record['data'])
            if (set(row)!=_FIELDS or row['schema']!=SCHEMA or row['scope']!=scope or row['id']!=identity
                    or row['sha256']!=identity or row['revision']!=record['revision'] or row['source']!='manual_upload'
                    or row['format'] not in _FORMATS or row['media_type']!=_FORMATS[row['format']][1]
                    or type(row['deleted']) is not bool):raise ValueError
            _revision(row['revision']);_annotations(row['caption'],row['tags'],row['enabled'])
            for key in ('width','height','frames','total_pixels','byte_size'):
                if type(row[key]) is not int or row[key]<1:raise ValueError
            if (row['frames']>MAX_FRAMES or row['total_pixels']!=row['width']*row['height']*row['frames']
                    or row['total_pixels']>MAX_PIXELS or row['byte_size']>MAX_BYTES):raise ValueError
            for key in ('created_at','updated_at','deleted_at'):
                if row[key] is None and key=='deleted_at':continue
                parsed=datetime.fromisoformat(row[key].replace('Z','+00:00'))
                if parsed.tzinfo is None or parsed.utcoffset().total_seconds()!=0:raise ValueError
            return row
        except (ValueError,TypeError,KeyError,AttributeError):
            raise ExpressionAssetError('expression asset metadata unavailable') from None

    def _put(self,db,namespace,key,scope,data,revision,now):
        self._scope(scope)
        if revision==0 and db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0]>=self.journal.max_records:
            raise ExpressionAssetError('expression asset checkpoint capacity reached')
        db.execute('''INSERT INTO checkpoints VALUES(?,?,?,?,?,?) ON CONFLICT(namespace,key,scope)
            DO UPDATE SET revision=excluded.revision,updated=excluded.updated,data=excluded.data''',
            (namespace,key,scope_key(scope),revision+1,now,canonical(data)))
        self._scope(scope)

    def _audit(self,db,scope,row,operation,now):
        db.execute('INSERT INTO audit(scope,occurred,event_type,entity_id,status,details) VALUES(?,?,?,?,?,?)',
            (scope_key(scope),now,'ExpressionAssetChanged',row['id'],operation,canonical({'revision':row['revision']})))
        db.execute('DELETE FROM audit WHERE seq NOT IN (SELECT seq FROM audit ORDER BY seq DESC LIMIT ?)',(self.journal.max_audit,))

    def _cleanup(self,scope,identity,installed):
        if installed is None:return
        path,expected=installed
        # A rollback owns only the new inode this call installed. A second
        # successful journal writer wins; cleanup never removes its asset.
        try:
            with self.journal._transaction() as db:
                if self._load(db,scope,identity) is not None:return
                current=path.lstat()
                if (current.st_dev,current.st_ino)==expected and not path.is_symlink():path.unlink()
        except (OSError,sqlite3.Error,RuntimeError):pass

    def import_bytes(self,scope,raw,*,request_id,caption='',tags=(),enabled=True):
        scope=self._scope(scope);annotations=_annotations(caption,tags,enabled)
        if (not isinstance(request_id,str) or not 1<=len(request_id)<=256 or request_id!=request_id.strip()
                or any(ord(char)<32 for char in request_id)):raise ValueError('bounded stable request_id required')
        metadata=_inspect(raw);self._scope(scope)
        identity=hashlib.sha256(raw).hexdigest();request_key=hashlib.sha256(request_id.encode()).hexdigest()
        signature=hashlib.sha256(canonical([identity,annotations]).encode()).hexdigest();installed=None
        # Keep the existing lifecycle lock through rollback and its owned-inode
        # cleanup. Host termination must not close the journal in the gap
        # between the failed SQL transaction and cleanup's reference check.
        # This is not an outer SQL transaction; other connections may still
        # commit and are protected by _cleanup's persisted-row/inode checks.
        with self._resources(),self.journal._lock:
            try:
                with self.journal._transaction() as db:
                    self._scope(scope)
                    receipt=db.execute('SELECT data FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
                        (REQUESTS,request_key,scope_key(scope))).fetchone()
                    if receipt:
                        try:
                            receipt=json.loads(receipt['data'])
                            if not isinstance(receipt,dict):raise ValueError
                        except (ValueError,TypeError):raise ExpressionAssetError('expression asset receipt unavailable') from None
                        if receipt.get('signature')!=signature:raise ExpressionAssetConflict('request_id reused with different image or annotations')
                        if receipt.get('scope')!=scope or receipt.get('asset_id')!=identity:raise ExpressionAssetError('expression asset receipt unavailable')
                        row=self._load(db,scope,identity)
                        if row is None:raise ExpressionAssetError('expression asset receipt unavailable')
                        self._scope(scope);return row
                    if db.execute('SELECT COUNT(*) FROM checkpoints WHERE namespace=? AND scope=?',(REQUESTS,scope_key(scope))).fetchone()[0]>=MAX_REQUESTS:
                        raise ExpressionAssetError('expression asset request capacity reached')
                    row=self._load(db,scope,identity);now,stamp=self._now()
                    if row is None:
                        if db.execute('SELECT COUNT(*) FROM checkpoints WHERE namespace=? AND scope=?',(NAMESPACE,scope_key(scope))).fetchone()[0]>=MAX_ASSETS:
                            raise ExpressionAssetError('expression asset scope capacity reached')
                        row=dict(schema=SCHEMA,scope=scope,id=identity,sha256=identity,**metadata,**annotations,
                            deleted=False,revision=1,created_at=stamp,updated_at=stamp,deleted_at=None,source='manual_upload')
                        installed=self._install(scope,row,raw)
                        self._put(db,NAMESPACE,identity,scope,row,0,now);self._audit(db,scope,row,'imported',now)
                    # An existing image keeps its caption, flags and deletion;
                    # changing those always needs explicit metadata CAS.
                    self._put(db,REQUESTS,request_key,scope,dict(schema=1,scope=scope,asset_id=identity,signature=signature),0,now)
                    self._scope(scope);return row
            except BaseException:
                self._cleanup(scope,identity,installed);raise

    def get(self,scope,identity,*,include_deleted=False):
        scope=self._scope(scope);_identity(identity)
        if type(include_deleted) is not bool:raise ValueError('explicit include_deleted flag required')
        with self._resources(),self.journal._lock:
            self.journal._ensure_open();row=self._load(self.journal._db,scope,identity);self._scope(scope)
            return row if row and (include_deleted or not row['deleted']) else None

    def list(self,scope,*,limit=50,offset=0,include_deleted=False):
        scope=self._scope(scope)
        if (type(limit) is not int or not 1<=limit<=MAX_ASSETS or type(offset) is not int or not 0<=offset<=MAX_ASSETS
                or type(include_deleted) is not bool):raise ValueError('bounded asset pagination required')
        with self._resources(),self.journal._lock:
            self.journal._ensure_open()
            keys=[row[0] for row in self.journal._db.execute('SELECT key FROM checkpoints WHERE namespace=? AND scope=? ORDER BY updated DESC,key LIMIT ?',
                (NAMESPACE,scope_key(scope),MAX_ASSETS+1))]
            if len(keys)>MAX_ASSETS:raise ExpressionAssetError('expression asset scope capacity reached')
            rows=[self._load(self.journal._db,scope,key) for key in keys]
            self._scope(scope)
            return [row for row in rows if include_deleted or not row['deleted']][offset:offset+limit]

    def _change(self,scope,identity,patch,expected_revision,operation):
        scope=self._scope(scope);_identity(identity);_revision(expected_revision)
        if not isinstance(patch,dict) or not patch or set(patch)-{'caption','tags','enabled','deleted'}:
            raise ValueError('invalid expression asset update')
        with self._resources(),self.journal._transaction() as db:
            self._scope(scope);row=self._load(db,scope,identity)
            if row is None:raise KeyError('expression asset not found')
            if row['revision']!=expected_revision:raise ExpressionAssetConflict('expression asset revision changed')
            if row['deleted'] and operation=='updated':raise KeyError('expression asset not found')
            proposed=dict(row,**patch);_annotations(proposed['caption'],proposed['tags'],proposed['enabled'])
            if all(row[key]==value for key,value in patch.items()):self._scope(scope);return row
            now,stamp=self._now();proposed.update(revision=row['revision']+1,updated_at=stamp)
            if 'deleted' in patch:proposed['deleted_at']=stamp if proposed['deleted'] else None
            self._put(db,NAMESPACE,identity,scope,proposed,row['revision'],now)
            self._audit(db,scope,proposed,operation,now);self._scope(scope);return proposed

    def update(self,scope,identity,patch,*,expected_revision):
        if not isinstance(patch,dict) or set(patch)-{'caption','tags','enabled'}:raise ValueError('only caption, tags and enabled may change')
        return self._change(scope,identity,patch,expected_revision,'updated')

    def delete(self,scope,identity,*,expected_revision):
        return self._change(scope,identity,{'deleted':True},expected_revision,'deleted')

    def restore(self,scope,identity,*,expected_revision):
        return self._change(scope,identity,{'deleted':False},expected_revision,'restored')

    def read_bytes(self,scope,identity,*,expected_revision=None):
        scope=self._scope(scope);_identity(identity)
        if expected_revision is not None:_revision(expected_revision)
        with self._resources():
            row=self.get(scope,identity)
            if row is None:raise KeyError('expression asset not found')
            if expected_revision is not None and row['revision']!=expected_revision:
                raise ExpressionAssetConflict('expression asset revision changed')
            raw=self._read_file(scope,row);current=self.get(scope,identity)
            if current is None:raise KeyError('expression asset not found')
            if current['revision']!=row['revision']:raise ExpressionAssetConflict('expression asset revision changed')
            self._scope(scope);return raw

    def _ranked_matches(self,scope,text):
        scope=self._scope(scope)
        if not isinstance(text,str) or len(text)>2000:
            raise ValueError('bounded manual-annotation query required')
        rows=[row for row in self.list(scope,limit=MAX_ASSETS) if row['enabled']]
        if not rows:self._scope(scope);return dict(state='empty_library',ranked=[])
        query=_normalize(text);terms=_terms(query);ranked=[]
        for row in rows:
            score=0
            for tag in row['tags']:
                tag=_normalize(tag)
                if re.fullmatch(r'[a-z0-9 ]+',tag):matched=bool(re.search(r'(?<![a-z0-9])'+re.escape(tag)+r'(?![a-z0-9])',query))
                else:matched=tag in query and (len(tag)>1 or len(query)==1)
                if matched:score+=10
            caption=_normalize(row['caption']);overlap=terms&_terms(caption)
            if any(len(term)>1 or len(query)==1 for term in overlap):score+=min(6,len(overlap))
            if score:ranked.append((-score,row['id'],row))
        self._scope(scope)
        return dict(state='selected' if ranked else 'no_match',ranked=sorted(ranked))

    def select(self,scope,text,*,limit=3):
        # Public preview contract remains 1..8 and exactly the existing ranking.
        scope=self._scope(scope)
        if not isinstance(text,str) or len(text)>2000 or type(limit) is not int or not 1<=limit<=8:
            raise ValueError('bounded manual-annotation query required')
        result=self._ranked_matches(scope,text)
        return dict(state=result['state'],assets=[item[2] for item in result['ranked'][:limit]])

    def stop(self):self.active=False
    def close(self):self.stop()  # The host retains the shared journal and files.
