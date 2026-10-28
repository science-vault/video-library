"""Build a public catalogue from files and JSON link descriptors; standard library only."""
import json,re,hashlib,zipfile,shutil,os,subprocess
from pathlib import Path
from urllib.parse import urlsplit,quote
from xml.etree import ElementTree as ET
from datetime import date

SCIENCE={'physics','chemistry','biology','human biology','science','earth and environmental science'}
HUMANITIES={'history','geography','economics','humanities','economics and business','legal studies'}
def https(value):
 try:
  u=urlsplit(value)
  return u.scheme=='https' and bool(u.hostname) and not u.username and not u.password
 except (ValueError,TypeError):return False

def validate(b):
 for k in ['title','subject','url']:
  if not isinstance(b.get(k),str) or not b[k].strip():raise ValueError('Missing '+k)
 if not https(b['url']):raise ValueError('URL must be HTTPS without credentials')
 years=b.get('years',[])
 if not isinstance(years,list) or any(type(y) is not int or y not in range(1,13) for y in years):raise ValueError('Year levels must be integers from 1 to 12')
 for k in ['thumbnail','previewUrl']:
  if b.get(k) and not https(b[k]) and not (k=='thumbnail' and re.fullmatch(r'assets/[a-zA-Z0-9.-]+',b[k])):raise ValueError('Invalid '+k)
 for k in ['author','topic','description','format','duration','subjectGroup']:
  if k in b and not isinstance(b[k],str):raise ValueError(k+' must be text')
 if 'slideCount' in b and (type(b['slideCount']) is not int or b['slideCount']<0):raise ValueError('Invalid slide count')
 return b

def infer(path):
 parts=path.parts; year=[]; subject='Uncategorised';topic=''
 for i,p in enumerate(parts[:-1]):
  m=re.fullmatch(r'Year[ _-]*(\d{1,2})',p,re.I)
  if m:
   n=int(m[1]);year=[n] if n in range(1,13) else []
   if i>0 and parts[i-1] not in ['Primary','Secondary','resources']:subject=parts[i-1]
   if i+1<len(parts)-1:topic=' / '.join(parts[i+1:-1])
 title=re.sub(r'[_]+',' ',path.stem).strip()
 return dict(title=title,subject=subject,years=year,topic=topic)

def pptx_info(path):
 result={};thumb=None
 try:
  with zipfile.ZipFile(path) as z:
   result['slideCount']=sum(bool(re.fullmatch(r'ppt/slides/slide\d+\.xml',s)) for s in z.namelist())
   if 'ppt/slides/slide1.xml' in z.namelist():
    r=ET.fromstring(z.read('ppt/slides/slide1.xml'));ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
    title=None
    for shape in r.findall('.//p:sp',ns):
     ph=shape.find('.//p:ph',ns)
     if ph is not None and ph.get('type') in ['title','ctrTitle']:
      title=' '.join(t.text or '' for t in shape.findall('.//a:t',ns)).strip();break
    if title:result['title']=title
   if 'docProps/core.xml' in z.namelist():
    r=ET.fromstring(z.read('docProps/core.xml'));a=r.find('{http://purl.org/dc/elements/1.1/}creator')
    if a is not None and a.text:result['author']=a.text.strip()
   for f in ['docProps/thumbnail.jpeg','docProps/thumbnail.jpg','docProps/thumbnail.png']:
    if f in z.namelist():
     data=z.read(f)
     if len(data)<5_000_000 and (data.startswith(b'\xff\xd8\xff') or data.startswith(b'\x89PNG\r\n\x1a\n')):thumb=(data,'.png' if data.startswith(b'\x89PNG') else '.jpg')
     break
 except (zipfile.BadZipFile,ET.ParseError,KeyError):pass
 return result,thumb

def build(root,kind,repo):
 root=Path(root);resources=root/'resources';site=root/'site';site.mkdir(exist_ok=True);assets=site/'assets';assets.mkdir(exist_ok=True)
 ext={'.ppt','.pptx','.pdf'} if kind=='powerpoint' else {'.mp4','.webm','.ogv','.ogg'}
 files=sorted(p for p in resources.rglob('*') if p.is_file());rows=[];seen={};seen_urls={};sidecars=set()
 def finish(b,p,ident):
  b.setdefault('author','');b.setdefault('description','');b.setdefault('years',[]);b['years']=sorted(set(b['years']))
  b.setdefault('subjectGroup','Science' if b['subject'].lower() in SCIENCE else 'Humanities' if b['subject'].lower() in HUMANITIES else b['subject'])
  b['sourcePath']=p.relative_to(root).as_posix()
  if not b.get('added'):
   try:added=subprocess.check_output(['git','log','--diff-filter=A','--format=%aI','--',b['sourcePath']],cwd=root,stderr=subprocess.DEVNULL,text=True).strip().splitlines();b['added']=added[-1][:10] if added else date.today().isoformat()
   except (subprocess.CalledProcessError,FileNotFoundError):b['added']=date.today().isoformat()
  b['id']=kind+'-'+hashlib.sha256(ident.encode()).hexdigest()[:16];validate(b)
  old=seen.get(ident) or seen_urls.get(b['url'])
  if old:old.setdefault('alternateSourcePaths',[]).append(b['sourcePath'])
  else:seen[ident]=b;seen_urls[b['url']]=b;rows.append(b)
 for p in files:
  if p.suffix.lower() not in ext:continue
  if p.suffix.lower()=='.pdf' and any(x.exists() for x in [p.with_suffix('.pptx'),p.with_suffix('.ppt')]):continue
  rel=p.relative_to(root);b=infer(rel);thumb=None
  if p.suffix.lower()=='.pptx':info,thumb=pptx_info(p);b.update(info)
  data=p.read_bytes();sha=hashlib.sha256(data).hexdigest();b['fileSHA256']=sha;b['url']='https://raw.githubusercontent.com/'+repo+'/main/'+quote(rel.as_posix());b['format']=p.suffix[1:].upper()
  side=p.with_suffix('.json')
  if side.exists():
   override=json.loads(side.read_text());
   if 'url' not in override:b.update(override);sidecars.add(side)
  preview=p.with_suffix('.pdf')
  if kind=='powerpoint' and p.suffix.lower() in ['.ppt','.pptx'] and preview.exists():
   target='assets/'+sha[:20]+'.pdf';shutil.copyfile(preview,site/target);b['previewUrl']='https://'+repo.split('/')[0]+'.github.io/'+repo.split('/')[1]+'/'+target
  if thumb and not b.get('thumbnail'):
   target='assets/'+sha[:20]+thumb[1];(site/target).write_bytes(thumb[0]);b['thumbnail']=target
  finish(b,p,'file:'+sha)
 for p in files:
  if p.suffix.lower()!='.json' or p in sidecars:continue
  b=json.loads(p.read_text())
  if not isinstance(b,dict):raise ValueError(str(p)+': resource must be a JSON object')
  base=infer(p);base.update(b);base.setdefault('format','Video link' if kind=='video' else 'Presentation link');validate(base);finish(base,p,'url:'+base['url'])
 rows.sort(key=lambda b:b['title'].casefold());catalog={'version':1,'resources':rows};(site/'catalog.json').write_text(json.dumps(catalog,indent=2,ensure_ascii=False)+'\n');print(f'{len(rows)} {kind} resources indexed');return catalog
if __name__=='__main__':
 root=Path(__file__).resolve().parents[1];config=json.loads((root/'site/config.js').read_text().split('=',1)[1].rstrip(';\n'));build(root,config['kind'],os.environ.get('GITHUB_REPOSITORY',config['repo']))
