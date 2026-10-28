import unittest,tempfile,json,zipfile
from pathlib import Path
from build_catalog import build,validate,infer
class CatalogueTests(unittest.TestCase):
 def test_bad_links_and_years(self):
  valid={'title':'Lesson','subject':'Physics','url':'https://example.com/video.mp4','years':[12]}
  validate(valid)
  for change in [{'url':'javascript:alert(1)'},{'url':'https://user:secret@example.com/a'},{'years':[True]},{'years':[13]},{'thumbnail':'data:text/html,unsafe'}]:
   with self.assertRaises(ValueError):validate({**valid,**change})
 def test_folder_inference(self):
  x=infer(Path('resources/Secondary/Physics/Year 12/Electrical circuits/Current.pptx'));self.assertEqual(x['years'],[12]);self.assertEqual(x['subject'],'Physics');self.assertEqual(x['topic'],'Electrical circuits')
 def test_dedup_links_and_empty(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);(r/'resources').mkdir();self.assertEqual(build(r,'video','owner/video-library')['resources'],[])
   b={'title':'Lesson','url':'https://example.com/test.mp4','subject':'Physics','years':[12]}
   for n in ['one','two']:(r/'resources'/f'{n}.json').write_text(json.dumps(b))
   result=build(r,'video','owner/video-library')['resources'];self.assertEqual(len(result),1);self.assertEqual(len(result[0]['alternateSourcePaths']),1);self.assertEqual(result[0]['subjectGroup'],'Science')
 def test_pptx_metadata_and_sidecar(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);p=r/'resources/Secondary/Physics/Year 12/Forces';p.mkdir(parents=True);f=p/'forces.pptx'
   with zipfile.ZipFile(f,'w') as z:z.writestr('ppt/slides/slide1.xml','<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:sp><p:ph type="title"/><a:t>Forces and motion</a:t></p:sp></p:sld>')
   f.with_suffix('.json').write_text('{"author":"A teacher"}')
   f.with_suffix('.pdf').write_bytes(b'%PDF-test')
   out=build(r,'powerpoint','owner/powerpoint-library')['resources'];self.assertEqual(len(out),1);self.assertEqual(out[0]['title'],'Forces and motion');self.assertEqual(out[0]['slideCount'],1);self.assertEqual(out[0]['author'],'A teacher');self.assertIn('previewUrl',out[0]);self.assertTrue(list((r/'site/assets').glob('*.pdf')))
if __name__=='__main__':unittest.main()
