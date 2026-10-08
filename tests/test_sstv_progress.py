import json
from pathlib import Path
import tempfile
import unittest
from urllib.request import urlopen
import threading
from test_sstv import header, tone
from sstv_decoder import FrameAssembler, RATE
from sstv_monitor import Session, Gallery, GalleryServer, image_snapshot
from PIL import Image


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.session = Session(dict(id='s',name='RX',band='20 m',freq_khz=14230,mode='usb',server='test'),None,None,'test')
        self.temp = tempfile.TemporaryDirectory()
        self.gallery = Gallery(self.temp.name)

    def tearDown(self):
        self.session.stop()
        self.temp.cleanup()

    def test_live_placeholder_preview_processing_completion_and_disconnect(self):
        events=[]
        assembler=FrameAssembler(lambda pcm,meta:events.append(meta),self.session.report,self.session.progress)
        assembler.feed(header()+tone(1800,2))
        row=self.session.snapshot()
        self.assertEqual(row['status'],'RECEIVING')
        live=image_snapshot(self.gallery,[row]);self.assertEqual(len(live),1)
        self.assertFalse(live[0]['has_image']);self.assertEqual(live[0]['kind'],'receiving')
        self.assertGreater(live[0]['progress_pct'],0)
        key=live[0]['id']
        assembler.feed(tone(1800,10))
        self.assertTrue(events,'A first preview must be requested before 30 seconds')
        path=Path(self.temp.name)/'preview.png';Image.new('RGB',(320,256),'red').save(path)
        self.gallery.publish(path,dict(live[0],kind='partial',progress_pct=10,updated_ns=1))
        live=image_snapshot(self.gallery,[self.session.snapshot()])
        self.assertEqual(len(live),1);self.assertTrue(live[0]['has_image'])
        self.assertGreater(live[0]['progress_pct'],10)
        assembler.feed(tone(1800,60))
        live=image_snapshot(self.gallery,[self.session.snapshot()])
        self.assertEqual(live[0]['kind'],'processing');self.assertEqual(live[0]['progress_pct'],100)
        self.session.finish_capture(key)
        self.assertEqual(image_snapshot(self.gallery,[self.session.snapshot()])[0]['kind'],'partial')
        assembler.feed(header()+tone(1800,3))
        assembler.reset()
        self.assertEqual(self.session.snapshot()['in_progress'],[])
        self.assertEqual(len(image_snapshot(self.gallery,[self.session.snapshot()])),1)

    def test_live_api_filter_stop_and_no_missing_image_requests(self):
        FrameAssembler(lambda *a:None,self.session.report,self.session.progress).feed(header()+tone(1800,3))
        server=GalleryServer(self.gallery,lambda:[self.session.snapshot()],('127.0.0.1',0))
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            data=json.load(urlopen(base+'/api/sstv'))
            self.assertEqual(len(data['images']),1);self.assertFalse(data['images'][0]['has_image'])
            self.assertEqual(json.load(urlopen(base+'/api/sstv?session=other'))['images'],[])
            self.session.stop()
            self.assertEqual(json.load(urlopen(base+'/api/sstv'))['images'],[])
        finally:server.shutdown();server.server_close();worker.join()

if __name__=='__main__':unittest.main()
