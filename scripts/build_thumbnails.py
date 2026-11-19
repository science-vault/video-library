"""Generate card images from uploaded media; cache by source content hash."""
import concurrent.futures,hashlib,json,os,shutil,subprocess,tempfile,threading
from pathlib import Path
import fitz

ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'.thumbnail-cache'
_LOCK=threading.Lock()

def pdf_thumbnail(source,target):
 with fitz.open(source) as doc:
  if not len(doc):raise ValueError('Document has no pages')
  page=doc[0];scale=min(640/page.rect.width,480/page.rect.height)
  pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
  pix.save(str(target),jpg_quality=80)

def generate(row):
 source=(ROOT/row['sourcePath']).resolve()
 if not source.is_relative_to((ROOT/'resources').resolve()) or not source.is_file():return None
 digest=row.get('fileSHA256') or hashlib.sha256(source.read_bytes()).hexdigest()
 target=CACHE/(digest+'.jpg')
 if target.exists():return target
 with tempfile.TemporaryDirectory(prefix='vault-thumb-') as folder:
  work=Path(folder);out=work/'frame.jpg'
  suffix=source.suffix.lower()
  with source.open('rb') as f:header=f.read(8)
  if header.startswith(b'%PDF-'):pdf_thumbnail(source,out)
  elif suffix in ['.mp4','.webm','.ogg','.ogv']:
   # Seek past the opening logo. Retry at the first frame for very short clips.
   for seconds in ['8','0']:
    subprocess.run(['ffmpeg','-nostdin','-v','error','-ss',seconds,'-i',str(source),'-frames:v','1','-vf','scale=640:360:force_original_aspect_ratio=decrease','-q:v','3','-y',str(out)],check=False,capture_output=True,timeout=90)
    if out.exists() and out.stat().st_size:break
  elif suffix in ['.ppt','.pptx']:
   # A separate profile isolates concurrent conversions and disables macros.
   profile=work/'profile';user=profile/'user';user.mkdir(parents=True)
   (user/'registrymodifications.xcu').write_text('<oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item></oor:items>')
   subprocess.run(['libreoffice','-env:UserInstallation='+profile.as_uri(),'--headless','--nologo','--nodefault','--norestore','--convert-to','pdf:impress_pdf_Export:{"PageRange":{"type":"string","value":"1"}}','--outdir',str(work),str(source)],check=True,capture_output=True,timeout=90)
   converted=list(work.glob('*.pdf'))
   if not converted:raise ValueError('No slide preview produced')
   pdf_thumbnail(converted[0],out)
  else:raise ValueError('Unsupported source format')
  if not out.exists() or not out.stat().st_size:raise ValueError('No image produced')
  # Concurrent duplicates use independent temp files and an atomic replacement.
  temporary=CACHE/(digest+'.'+str(threading.get_ident())+'.tmp')
  shutil.copyfile(out,temporary);temporary.replace(target)
 return target

def build():
 CACHE.mkdir(exist_ok=True);assets=ROOT/'site/assets';assets.mkdir(exist_ok=True)
 catalog_path=ROOT/'site/catalog.json';catalog=json.loads(catalog_path.read_text());rows=catalog['resources']
 missing=[r for r in rows if not r.get('thumbnail')];unique={}
 for row in missing:unique.setdefault(row.get('fileSHA256') or row['sourcePath'],row)
 generated={};failures=[]
 def run(pair):
  key,row=pair
  try:return key,generate(row),None
  except Exception as exc:return key,None,type(exc).__name__+': '+str(exc)[:250]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  for count,(key,path,error) in enumerate(pool.map(run,unique.items()),1):
   if path:generated[key]=path
   else:failures.append({'sourcePath':unique[key]['sourcePath'],'reason':error or 'Source not available locally'})
   if count%50==0:print(f'Thumbnails: {count}/{len(unique)} processed',flush=True)
 for row in missing:
  path=generated.get(row.get('fileSHA256') or row['sourcePath'])
  if path:
   name='thumb-'+path.name;shutil.copyfile(path,assets/name);row['thumbnail']='assets/'+name
 catalog_path.write_text(json.dumps(catalog,ensure_ascii=False,separators=(',',':'))+'\n')
 report={'resources':len(rows),'withThumbnails':sum(bool(r.get('thumbnail')) for r in rows),'failedSources':failures}
 (ROOT/'site/thumbnail-report.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({k:v for k,v in report.items() if k!='failedSources'}),flush=True)
 print(f'{len(failures)} sources could not be rendered',flush=True)
if __name__=='__main__':build()
