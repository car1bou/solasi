import unittest
from PIL import Image
from experiments.handwriting_regions import crop_regions,parse_layout


class HandwritingRegionTests(unittest.TestCase):
    def setUp(self):
        self.image=Image.new('RGB',(100,80),'white');self.image.putpixel((99,40),(1,2,3))

    def test_crop_keeps_pixels_source_position_and_explicit_reading_order(self):
        rows=[{'id':'condition','kind':'mixed','bbox':[50,20,100,60]},
              {'id':'title','kind':'text','bbox':[0,0,100,20]}]
        crops=crop_regions(self.image,rows)
        self.assertEqual([r['id']for r,im in crops],['condition','title'])
        self.assertEqual(crops[0][1].getpixel((49,20)),(1,2,3))
        self.assertEqual(crops[0][0]['bbox'],[50,20,100,60])
        self.assertEqual(self.image.size,(100,80))

    def test_invalid_regions_are_rejected_without_clipping_to_page(self):
        for bbox in ([-1,0,10,10],[0,0,101,10],[10,0,10,10],[0,0,10],[0,0,True,10],[0,0,10.2,10]):
            with self.subTest(bbox=bbox),self.assertRaises(ValueError):
                crop_regions(self.image,[{'id':'a','kind':'formula','bbox':bbox}])
        for rows in ([],[{'id':'a','kind':'unknown','bbox':[0,0,10,10]}],
                     [{'id':'a','kind':'text','bbox':[0,0,10,10]}]*2):
            with self.subTest(rows=rows),self.assertRaises(ValueError):crop_regions(self.image,rows)

    def test_layout_uses_actual_resized_pixel_coordinates_and_keeps_model_order(self):
        raw='[{"bbox":[50,40,100,80],"category":"Formula"},{"bbox":[0,0,50,20],"category":"Text"}]'
        rows=parse_layout(raw,(100,80),(200,160))
        self.assertEqual(rows[0]['bbox'],[25,20,50,40]);self.assertEqual(rows[0]['kind'],'formula')
        self.assertEqual(rows[1]['kind'],'mixed')

    def test_malformed_layout_never_becomes_successful_partial_detection(self):
        for raw in ('not JSON','[]','{}','[{"bbox":[0,0,999,9],"category":"Text"}]',
                    '[{"bbox":[0,0,10,9],"category":"unknown"}]',
                    '[{"bbox":[0,0,10,9],"category":"Text"},{"bbox":[0,0,0,9],"category":"Text"}]'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):parse_layout(raw,(100,80),(100,80))

    def test_fractional_layout_rounds_outward_and_preserves_unsupported_category(self):
        rows=parse_layout('[{"bbox":[1.1,2.1,9.1,10.1],"category":"Picture"}]',(100,80),(200,160))
        self.assertEqual(rows[0]['bbox'],[0,1,5,6])
        self.assertEqual(rows[0]['kind'],'unsupported')

    def test_crops_use_exif_oriented_coordinates(self):
        self.image.getexif()[274]=6
        row={'id':'rotated','kind':'text','bbox':[0,0,80,100]}
        crops=crop_regions(self.image,[row])
        self.assertEqual(crops[0][1].size,(80,100))
        self.assertEqual(crops[0][1].getpixel((39,99)),(1,2,3))
        self.assertEqual(self.image.size,(100,80))
