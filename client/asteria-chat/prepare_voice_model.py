"""Create an attributed phone import ZIP from the exact official SenseVoiceSmall int8 model directory. No download or recognition."""
from pathlib import Path
import argparse,hashlib,zipfile
FILES={'model.int8.onnx':(239233841,'c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51'),'tokens.txt':(315894,'f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc')}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
 for name,(size,digest) in FILES.items():
  file=args.source/name
  if file.is_symlink() or not file.is_file() or file.stat().st_size!=size or hashlib.sha256(file.read_bytes()).hexdigest()!=digest:raise RuntimeError('Wrong/incomplete pinned model file: '+name)
 for name in ('LICENSE','MODEL_LICENSE.txt','README.md'):
  if not (args.source/name).is_file():raise RuntimeError('Retain original model attribution/license: '+name)
 with zipfile.ZipFile(args.output,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
  for name in [*FILES,'LICENSE','MODEL_LICENSE.txt','README.md']:archive.write(args.source/name,name)
 print('Model ZIP created; retain FunAudioLLM/Alibaba Group SenseVoice attribution and FunASR Model Open Source License Agreement v1.1:',args.output)
if __name__=='__main__':main()
