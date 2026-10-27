"""Set this source checkout's app name and actual Android launcher image before building.

The caller supplies a square PNG. This tool copies its bytes and never edits the
original, generates a signing key, uploads anything, or changes an installed app.
"""
from pathlib import Path
import argparse,json,struct
from xml.sax.saxutils import escape

APP=Path(__file__).resolve().parent
STAR_PATH='M54,22 L63,42 L85,45 L69,61 L73,84 L54,73 L35,84 L39,61 L23,45 L45,42 Z'
DEFAULT_VECTOR=f'''<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="108dp" android:height="108dp" android:viewportWidth="108" android:viewportHeight="108"><path android:fillColor="#D8C1A0" android:pathData="{STAR_PATH}" /></vector>
'''

def png(raw):
    if not 33<=len(raw)<=8*1024*1024 or raw[:8]!=b'\x89PNG\r\n\x1a\n' or raw[12:16]!=b'IHDR':
        raise ValueError('Choose an actual square PNG no larger than 8 MiB')
    width,height=struct.unpack('>II',raw[16:24])
    if width!=height or not 48<=width<=4096:
        raise ValueError('Crop a square PNG of 48–4096 pixels before importing')
    return width,height

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name',help='Visible application name, 1–60 characters')
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--icon',type=Path,help='Your own square PNG; preserve its rights and source')
    mode.add_argument('--reset-icon',action='store_true')
    args=parser.parse_args()
    brand=json.loads((APP/'brand.json').read_text(encoding='utf8'))
    name=args.name if args.name is not None else brand['name']
    if not 1<=len(name.strip())<=60 or any(ord(c)<32 for c in name):
        raise ValueError('Name must contain 1–60 visible characters')
    name=name.strip();brand['name']=name
    icon_bytes=None;dimensions=None
    if args.icon:
        source=args.icon.expanduser().resolve(strict=True)
        if not source.is_file()or source.is_symlink():raise ValueError('Icon must be a regular file')
        icon_bytes=source.read_bytes();dimensions=png(icon_bytes)
    image='brand.svg';mime='image/svg+xml'
    if icon_bytes is not None:
        resource=APP/'android/res/drawable-nodpi/ic_launcher_custom.png';resource.parent.mkdir(exist_ok=True)
        resource.write_bytes(icon_bytes);(APP/'web/brand-custom.png').write_bytes(icon_bytes)
        bitmap='''<?xml version="1.0" encoding="utf-8"?>
<bitmap xmlns:android="http://schemas.android.com/apk/res/android" android:src="@drawable/ic_launcher_custom" android:gravity="fill" android:filter="true" />
'''
        for target in ('ic_launcher.xml','ic_launcher_foreground.xml'):
            (APP/'android/res/drawable'/target).write_text(bitmap,encoding='utf8')
        brand['custom_icon']=True
    elif args.reset_icon:
        for target in ('ic_launcher.xml','ic_launcher_foreground.xml'):
            (APP/'android/res/drawable'/target).write_text(DEFAULT_VECTOR,encoding='utf8')
        for relative in ('web/brand-custom.png','android/res/drawable-nodpi/ic_launcher_custom.png'):
            target=APP/relative
            if target.exists():
                if target.is_symlink()or not target.resolve().is_relative_to(APP.resolve()):raise ValueError('Unexpected icon path')
                target.unlink()
        brand['custom_icon']=False
    if brand.get('custom_icon'):
        image='brand-custom.png';mime='image/png'
    index=APP/'web/index.html';html=index.read_text(encoding='utf8')
    html=html.replace('brand-custom.png','brand.svg').replace('href="brand.svg" type="image/png"','href="brand.svg" type="image/svg+xml"')
    html=html.replace('brand.svg',image).replace('href="'+image+'" type="image/svg+xml"','href="'+image+'" type="'+mime+'"')
    index.write_text(html,encoding='utf8')
    (APP/'android/res/values/strings.xml').write_text('<?xml version="1.0" encoding="utf-8"?><resources><string name="app_name">'+escape(name).replace("'","\\'")+'</string></resources>\n',encoding='utf8')
    (APP/'brand.json').write_text(json.dumps(brand,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    (APP/'web/brand-config.js').write_text("'use strict';\nwindow.AsteriaBrand="+json.dumps(dict(name=name),ensure_ascii=False)+";\ndocument.addEventListener('DOMContentLoaded',()=>{const name=window.AsteriaBrand.name;document.title=name;const brand=document.querySelector('.brand strong');if(brand)brand.textContent=name;const about=document.querySelector('.about-app>span');if(about&&about.firstChild)about.firstChild.textContent=name+' ';},{once:true});\n",encoding='utf8')
    print(json.dumps(dict(name=name,custom_icon=bool(brand.get('custom_icon')),dimensions=dimensions,
        source_original_modified=False,installed_app_modified=False,signing_keys_generated=False,
        next_step='Inspect web input and build with your own signing key'),ensure_ascii=False))

if __name__=='__main__':main()
