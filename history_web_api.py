"""AstrBot-authenticated, read-only administration of the native history archive."""
from __future__ import annotations

import asyncio
import re
import sqlite3

from astrbot.api.web import error_response, json_response, request


PAGE_API_PREFIX = '/astrbot_plugin_virtual_body/page/history'


def _integer(value, default, minimum, maximum):
    if value is None:
        return default
    if isinstance(value,str) and re.fullmatch('[0-9]+',value):
        value=int(value)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('invalid history pagination')
    return value


def _text(value, *, blank=False):
    if not isinstance(value,str) or len(value)>512 or '\x00' in value or (not blank and not value.strip()):
        raise ValueError('invalid history query')
    return value


class NativeHistoryWebApi:
    def __init__(self, plugin):
        self.plugin=plugin

    def register_routes(self):
        for name in ('stats','records','search','detail'):
            self.plugin.context.register_web_api(PAGE_API_PREFIX+'/'+name,
                getattr(self,'history_'+name),['GET'],'Native historical archive administrator '+name)

    def _archive(self):
        host=getattr(getattr(self.plugin,'_presence',None),'living_host',None)
        archive=getattr(getattr(host,'runtime',None),'history_archive',None)
        if (getattr(archive,'backend',None)!='native_history_archive'
                or getattr(archive,'retrieval_enabled',True) is not False or getattr(archive,'closed',True)):
            raise RuntimeError('native historical archive unavailable')
        return archive

    async def _respond(self,name):
        try:
            username=getattr(request,'username',None)
        except RuntimeError:
            username=None
        if not isinstance(username,str) or not username.strip():
            return error_response('需要通过 AstrBot 管理后台认证',status_code=401)
        try:
            archive=self._archive()
            query=getattr(request,'query',None)
            data=dict(query.items()) if query is not None else {}
            allowed={'id'} if name=='detail' else (set() if name=='stats' else {'limit','offset','source_hash','scope','source_plugin'}|({'q'} if name=='search' else set()))
            if set(data)-allowed:
                raise ValueError('unknown historical archive parameter')
            if name=='stats':
                method,args,kwargs,key='stats',(),{},'stats'
            elif name=='detail':
                method,args,kwargs,key='get',(_text(data.get('id')),),{},'record'
            else:
                kwargs={'limit':_integer(data.get('limit'),50,1,100),'offset':_integer(data.get('offset'),0,0,1000000)}
                for field in ('source_hash','scope','source_plugin'):
                    if field in data:
                        kwargs[field]=_text(data[field],blank=True)
                method,args,key=('query',(_text(data.get('q')),),'records') if name=='search' else ('list',(),'records')
            def operate():
                if self._archive() is not archive:
                    raise RuntimeError('historical archive changed')
                return getattr(archive,method)(*args,**kwargs)
            result=await asyncio.to_thread(operate)
            return json_response({'ok':True,'backend':'native_history_archive','access':'authenticated_administrator',
                'archive_only':True,'retrieval_enabled':False,key:result},headers={'Cache-Control':'no-store'})
        except KeyError:
            return error_response('找不到该历史档案',status_code=404)
        except ValueError:
            return error_response('历史档案查询参数无效',status_code=400)
        except (RuntimeError,sqlite3.Error,OSError):
            return error_response('历史档案暂不可用',status_code=503)
        except Exception:
            return error_response('历史档案读取失败',status_code=500)

    async def history_stats(self):
        return await self._respond('stats')

    async def history_records(self):
        return await self._respond('records')

    async def history_search(self):
        return await self._respond('search')

    async def history_detail(self):
        return await self._respond('detail')
