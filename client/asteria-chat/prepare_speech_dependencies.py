"""Explicit preparation of pinned public dependencies. The APK builder itself stays offline."""
from pathlib import Path
import argparse,hashlib,urllib.request
from build_apk import ROOT,SPEECH_ARTIFACTS,speech_inputs
ASSETS={'sherpa-onnx-jvm-2.0.1.jar':680047520,'sherpa-onnx-static-link-onnxruntime-2.0.1.aar':678842484}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,default=ROOT/'.runtime/speech-deps-2.0.1');p.add_argument('--download',action='store_true',help='Explicitly download the two fixed official release artifacts, then verify SHA-256');args=p.parse_args()
 args.directory.mkdir(parents=True,exist_ok=True)
 if args.download:
  for name,(size,digest) in SPEECH_ARTIFACTS.items():
   target=args.directory/name
   if target.exists():
    if target.stat().st_size!=size or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise RuntimeError('Existing dependency differs: '+name)
    continue
   part=target.with_suffix(target.suffix+'.part');request=urllib.request.Request('https://api.github.com/repos/k2-fsa/sherpa-onnx/releases/assets/'+str(ASSETS[name]),headers={'Accept':'application/octet-stream','User-Agent':'Asteria-offline-speech-build'})
   with urllib.request.urlopen(request,timeout=60) as source,part.open('wb') as output:
    total=0
    while True:
     chunk=source.read(65536)
     if not chunk:break
     total+=len(chunk)
     if total>size:raise RuntimeError('Dependency exceeds pinned length')
     output.write(chunk)
   if total!=size or hashlib.sha256(part.read_bytes()).hexdigest()!=digest:raise RuntimeError('Dependency verification failed: '+name)
   part.rename(target)
 speech_inputs(args.directory);print('Pinned speech dependencies verified:',args.directory)
if __name__=='__main__':main()
