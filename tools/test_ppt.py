"""Synthetic PPTX checks; never opens or edits a user's deck."""
from pathlib import Path
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT/'yl-ppt/scripts/pptx_inspect.py'
spec = importlib.util.spec_from_file_location('ppt_inspect', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def deck(path, text='原文', shape_id='2', first='2', image=b'original-image'):
    ns = mod.NS
    main = f'<p:presentation xmlns:p="{ns["p"]}" xmlns:r="{ns["r"]}"><p:sldIdLst><p:sldId id="256" r:id="rId{first}"/></p:sldIdLst><p:sldSz cx="9144000" cy="5143500"/></p:presentation>'
    slide = f'<p:sld xmlns:p="{ns["p"]}" xmlns:a="{ns["a"]}" xmlns:r="{ns["r"]}"><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="shape{shape_id}"/></p:nvSpPr><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp><p:pic><p:nvPicPr><p:cNvPr id="7" name="picture"/></p:nvPicPr><p:blipFill><a:blip r:embed="rId5"/></p:blipFill></p:pic></p:spTree></p:cSld></p:sld>'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('ppt/presentation.xml', main)
        z.writestr('ppt/_rels/presentation.xml.rels', f'<Relationships xmlns="{mod.REL}"><Relationship Id="rId{first}" Type="slide" Target="slides/slide{first}.xml"/></Relationships>')
        z.writestr(f'ppt/slides/slide{first}.xml', slide)
        z.writestr(f'ppt/slides/_rels/slide{first}.xml.rels', f'<Relationships xmlns="{mod.REL}"><Relationship Id="rId5" Type="image" Target="../media/pic.png"/></Relationships>')
        z.writestr('ppt/media/pic.png', image)


class PPTChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.a = Path(self.temp.name)/'a.pptx'
        self.b = Path(self.temp.name)/'b.pptx'
        deck(self.a)

    def test_order_comes_from_presentation_relationships(self):
        inv = mod.inventory(self.a)
        self.assertEqual(inv['slides'][0]['part'], 'ppt/slides/slide2.xml')
        self.assertEqual(inv['slides'][0]['text'], '原文')

    def test_shape_identity_noise_is_not_content_change(self):
        deck(self.b, shape_id='99')
        diff = mod.compare(self.a, self.b)
        self.assertTrue(diff['changed_parts'])
        self.assertEqual(diff['changed_slide_positions'], [])

    def test_content_and_embedded_image_changes_are_detected(self):
        deck(self.b, text='改文')
        self.assertEqual(mod.compare(self.a, self.b)['changed_slide_positions'], [1])
        deck(self.b, image=b'replacement-image')
        self.assertEqual(mod.compare(self.a, self.b)['changed_slide_positions'], [1])

    def test_input_cannot_be_used_as_report(self):
        before = self.a.read_bytes()
        result = subprocess.run([sys.executable, '-B', str(SCRIPT), 'inventory', str(self.a), '--out', str(self.a)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.a.read_bytes(), before)

    def test_invalid_xml_fails(self):
        with zipfile.ZipFile(self.b, 'w') as z:
            z.writestr('ppt/presentation.xml', '<broken')
        with self.assertRaises(mod.ET.ParseError):
            mod.inventory(self.b)


if __name__ == '__main__':
    unittest.main(verbosity=2)
