from importlib import metadata
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
parts=['Third-party notices for FB Live Analyzer\nGenerated from the build environment. Includes runtime and build-tool notices.\n']
for dist in sorted(metadata.distributions(),key=lambda x:x.metadata.get('Name','').lower()):
    name=dist.metadata.get('Name','unknown')
    parts.append('\n'+'='*80+'\n'+name+' '+dist.version+'\n')
    for key in ['License-Expression','License','Home-page']:
        if dist.metadata.get(key):parts.append(key+': '+dist.metadata[key]+'\n')
    for f in dist.files or []:
        s=str(f).lower()
        if any(w in Path(s).name for w in ['license','copying','notice']) and not s.endswith(('.py','.pyc','.pyd','.dll')):
            file=dist.locate_file(f)
            if file.is_file():
                try:parts.append('\n--- '+str(f)+' ---\n'+file.read_text(encoding='utf-8')+'\n')
                except UnicodeError:pass
runtime=Path(sys.base_prefix)/'LICENSE.txt'
if runtime.exists():parts.append('\nCPython Runtime License\n'+runtime.read_text(encoding='utf-8'))
out=root/'THIRD_PARTY_NOTICES.txt'
out.write_text(''.join(parts),encoding='utf-8')
print('Notices saved:',out.stat().st_size,'bytes')
