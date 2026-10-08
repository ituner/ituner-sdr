import io
import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import urlopen
from urllib.error import HTTPError
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'UI'))
import numpy as np
from PIL import Image
from sstv_decoder import FrameAssembler, RATE, decode_file
from sstv_monitor import Gallery, GalleryServer, SSTVManager, Session, PRESETS, DecodeQueue
from sstv_vendor import spec


def tone(freq, seconds):
    return (np.sin(np.arange(round(seconds*RATE))*2*np.pi*freq/RATE)*12000).astype('<i2').tobytes()


def header(vis=40, bad_parity=False):
    bits = [(vis >> i) & 1 for i in range(7)]
    bits.append((sum(bits) % 2) ^ bad_parity)
    return tone(1900,.3)+tone(1200,.01)+tone(1900,.3)+tone(1200,.03)+b''.join(tone(1100 if b else 1300,.03) for b in bits)+tone(1200,.03)


def wait_for(predicate, timeout=5):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate(): return
        time.sleep(.02)
    raise AssertionError('Timed out waiting for condition')


class FramingTests(unittest.TestCase):
    def test_every_supported_vis_and_chunk_boundary(self):
        for vis, mode in spec.VIS_MAP.items():
            for prefix in (0, 5900, 12000, 17222, 23500):
                statuses=[]
                decoder=FrameAssembler(lambda *a:None, lambda *a:statuses.append(a))
                pcm=bytes(prefix)+header(vis)+bytes(RATE*4)
                for start in range(0,len(pcm),1024): decoder.feed(pcm[start:start+1024])
                self.assertTrue(any(row==('RECEIVING',mode.NAME) for row in statuses),(vis,prefix,statuses))

    def test_invalid_parity_and_noise_are_not_frames(self):
        events=[]
        decoder=FrameAssembler(lambda *a:events.append(a))
        pcm=header(bad_parity=True)+np.random.default_rng(42).integers(-3000,3000,RATE*5,dtype=np.int16).tobytes()
        for start in range(0,len(pcm),2048): decoder.feed(pcm[start:start+2048])
        self.assertIsNone(decoder.mode)
        self.assertFalse(events)
        self.assertLessEqual(len(decoder.buffer), RATE*2*3)

    def test_two_back_to_back_frames_and_same_id_for_partial(self):
        events=[]
        decoder=FrameAssembler(lambda p,m:events.append((p,m)))
        mode=spec.M2
        pcm=header()+tone(1800,mode.LINE_TIME*mode.LINE_COUNT)
        both=pcm+pcm+bytes(RATE*4)
        for start in range(0,len(both),4096): decoder.feed(both[start:start+4096])
        finals=[m for p,m in events if m['kind']=='full']
        self.assertEqual(len(finals),2)
        self.assertNotEqual(finals[0]['id'],finals[1]['id'])
        self.assertEqual(events[0][1]['id'],finals[0]['id'])
        self.assertEqual(finals[0]['progress_pct'],100)

    def test_scottie_dx_does_not_truncate_at_old_140_seconds(self):
        events=[]
        decoder=FrameAssembler(lambda p,m:events.append(m))
        data=header(76)+tone(1800,150)
        for i in range(0,len(data),4096): decoder.feed(data[i:i+4096])
        self.assertEqual(decoder.mode.NAME,'Scottie DX')
        self.assertGreater(decoder.expected/(RATE*2),260)
        self.assertTrue(events)
        self.assertFalse(any(m['kind']=='full' for m in events))

    def test_reset_discards_incomplete_transmission(self):
        events=[]
        decoder=FrameAssembler(lambda p,m:events.append(m))
        decoder.feed(header()+bytes(RATE*6))
        self.assertIsNotNone(decoder.mode)
        decoder.reset()
        decoder.feed(bytes(RATE*6))
        self.assertIsNone(decoder.mode)
        self.assertFalse(events)


class GalleryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.gallery=Gallery(self.root/'images')
        self.meta=dict(id='a'*32,session_id='s',mode='Martin 2',band='20 m',freq_khz=14230,
                       receiver='<script>test</script>',capture_utc='2026-10-05T12:00:00Z',kind='partial',progress_pct=50,updated_ns=1)

    def tearDown(self): self.temp.cleanup()

    def publish(self, meta):
        p=self.root/'temp.png';Image.new('RGB',(320,256),'red').save(p)
        self.gallery.publish(p,meta)

    def test_partial_replaced_and_restored(self):
        self.publish(self.meta)
        self.publish(dict(self.meta,kind='full',progress_pct=100))
        loaded=Gallery(self.root/'images')
        self.assertEqual(len(loaded.snapshot()),1)
        self.assertEqual(loaded.snapshot()[0]['kind'],'full')
        self.assertEqual(loaded.snapshot('different'),[])

    def test_retention(self):
        with patch('sstv_monitor.GALLERY_LIMIT',2):
            for index in range(3): self.publish(dict(self.meta,id=f'{index:032x}',capture_utc=str(index)))
        self.assertEqual(len(self.gallery.snapshot()),2)
        self.assertFalse(self.gallery.image_path('0'*32).exists())

    def test_api_image_and_traversal(self):
        self.publish(self.meta)
        server=GalleryServer(self.gallery,lambda:[],('127.0.0.1',0))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            data=json.load(urlopen(base+'/api/sstv'))
            self.assertEqual(data['images'][0]['receiver'],self.meta['receiver'])
            self.assertTrue(urlopen(base+'/images/'+'a'*32+'.png').read().startswith(b'\x89PNG'))
            html=urlopen(base+'/sstv').read()
            self.assertNotIn(b'<script>test</script>',html)
            self.assertIn(b'textContent',html)
            with self.assertRaises(HTTPError): urlopen(base+'/images/../../sessions.png')
        finally: server.shutdown();server.server_close();thread.join()

    def test_session_persistence_stop_and_delete(self):
        # Full decoder round-trip is covered below with an independent encoder.
        with patch('sstv_monitor.Session.start'):
            manager=SSTVManager(None,'test',self.root/'state',web_port=-1)
            try:
                key=manager.add('RX','host:8073',PRESETS[4])
                manager.toggle(key)
                manager.configs[0]['paused']=True;manager.save()
                restored=SSTVManager(None,'test',self.root/'state',web_port=-1)
                try:
                    self.assertEqual(restored.configs[0]['id'],key)
                    self.assertTrue(restored.configs[0]['paused'])
                    restored.tick();self.assertEqual(restored.sessions,{})
                    restored.delete(key);self.assertEqual(restored.configs,[])
                finally: restored.stop()
            finally: manager.stop()


class TransportTests(unittest.TestCase):
    def test_handshake_endian_gap_and_shutdown(self):
        class WS:
            def __init__(self):
                self.sock,self.peer=socket.socketpair();self.commands=[];self.messages=[]
            def send_text(self,text): self.commands.append(text)
            def recv(self): self.sock.recv(1);return self.messages.pop(0)
            def push(self,data): self.messages.append(data);self.peer.send(b'x')
            def send_close(self): self.sock.close();self.peer.close()
        ws=WS()
        from types import SimpleNamespace
        kiwi=SimpleNamespace(KiwiWebSocket=SimpleNamespace(connect=lambda *a,**k:ws),
            send_kiwi_setup=lambda *a:None,parse_msg_params=lambda data:json.loads(data[3:]),
            send_snd_setup=lambda *a:ws.commands.append(a),SND_FLAG_COMPRESSED=16,
            SND_FLAG_STEREO=8,SND_FLAG_LITTLE_ENDIAN=128,
            swap_s16_bytes=lambda pcm:np.frombuffer(pcm,dtype='>i2').astype('<i2').tobytes())
        frames=[];resets=[]
        class Assembler:
            def __init__(self,*a): pass
            def reset(self): resets.append(1)
            def feed(self,pcm): frames.append(pcm)
        config=dict(id='x',name='test',server='localhost',band='40 m',freq_khz=7165,mode='lsb')
        with patch('sstv_decoder.FrameAssembler',Assembler):
            session=Session(config,kiwi,None,'test');session.start()
            ws.push(b'MSG'+json.dumps({'badp':0,'audio_rate':12000,'sample_rate':12000}).encode())
            wait_for(lambda:session.status=='LISTENING')
            ws.push(b'SND'+struct.pack('<BI',0,10)+b'\0\0'+b'\x01\x02')
            ws.push(b'SND'+struct.pack('<BI',128,12)+b'\0\0'+b'\x03\x04')
            wait_for(lambda:len(frames)==2)
            self.assertEqual(frames,[b'\x02\x01',b'\x03\x04'])
            self.assertGreaterEqual(len(resets),2)
            setup=next(c for c in ws.commands if isinstance(c,tuple))
            self.assertEqual(setup[2:5],('lsb',-2700,-500))
            session.stop();session.thread.join(2)
            self.assertFalse(session.thread.is_alive())


class WorkspaceTests(unittest.TestCase):
    def test_gallery_add_and_enlarged_actions_fit_1280_by_800(self):
        from types import SimpleNamespace
        from sstv_workspace import SSTVWorkspace
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            manager=SSTVManager(None,'test',tmp,web_port=-1)
            ui=SimpleNamespace(draw_logical_rect=Mock(),draw_text=Mock(),
                fit_station_text=lambda cache,value,*args:str(value),
                station_fields=lambda row:(row[0],row[1],row[2],None,None),
                contains=lambda box,x,y:box[0]<=x<=box[2] and box[1]<=y<=box[3],
                LOCAL_KIWI_SERVER='kiwisdr.local:8073')
            workspace=SSTVWorkspace(ui,manager)
            workspace.image=lambda *args:None
            rows=[('Local Kiwi','LAN','kiwisdr.local:8073')]
            manager.configs=[dict(id=str(i),name='Local Kiwi',server=rows[0][2],band=preset[0],
                                  freq_khz=preset[1],mode=preset[2],paused=True) for i,preset in enumerate(PRESETS[:6])]
            for i in range(17):
                png=Path(tmp)/'tmp.png';Image.new('RGB',(320,256),'red').save(png)
                manager.gallery.publish(png,dict(id=f'{i:032x}',session_id='0',mode='Martin 2',band='20 m',
                    capture_utc=str(i),progress_pct=100,kind='full',receiver='RX',freq_khz=14230))
            try:
                workspace.show(rows[0][2],14230,'usb')
                for view in ('gallery','decoders','add','enlarged'):
                    workspace.decoders_open=view=='decoders'
                    workspace.add_open=view=='add';workspace.enlarged='0'*32 if view=='enlarged' else None
                    workspace.draw(None,rows)
                    for box,action in workspace.actions:
                        x0,y0,x1,y1=box
                        self.assertTrue(0<=x0<x1<=1280 and 0<=y0<y1<=800,(view,action,box))
                        self.assertGreaterEqual(y1-y0,48,(view,action))
                    if view=='decoders':
                        self.assertEqual(sum(a[0]=='toggle' for _,a in workspace.actions),6)
                    if view=='gallery':
                        self.assertFalse(any(a[0] in ('toggle','delete') for _,a in workspace.actions))
                        self.assertEqual(sum(a[0]=='image' for _,a in workspace.actions),15)
                        workspace.tap(350,755,rows);self.assertEqual(workspace.page,1)
                        workspace.draw(None,rows)
                        self.assertEqual(sum(a[0]=='image' for _,a in workspace.actions),2)
                workspace.tap(1140,40,rows);self.assertIsNone(workspace.enlarged)
            finally: manager.stop()


try:
    from pysstv.color import MartinM2, Robot36
except ImportError:
    MartinM2=Robot36=None


@unittest.skipIf(MartinM2 is None,'Install PySSTV==0.5.7 for independent encoder round-trip tests')
class RoundTripTests(unittest.TestCase):
    def test_independent_encoder_decoder_and_gallery(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            image=Image.new('RGB',(320,256))
            data=np.zeros((256,320,3),dtype=np.uint8)
            data[:,:,0]=np.linspace(0,255,320,dtype=np.uint8)[None,:]
            data[:,:,1]=np.arange(256,dtype=np.uint8)[:,None]
            data[:,:,2]=255-data[:,:,0]
            image=Image.fromarray(data)
            for cls in (MartinM2,Robot36):
                wav=root/'source.wav';out=root/'decoded.png'
                source=image.resize((cls.WIDTH,cls.HEIGHT))
                cls(source,RATE,16).write_wav(str(wav))
                result=decode_file(wav,out)
                self.assertGreater(result['row_corr_mean'],.8)
                decoded=Image.open(out).convert('RGB')
                # M2 transmits 160 source pixels; this decoder displays a 320-wide raster.
                self.assertEqual(decoded.size, (320, cls.HEIGHT))
                source = source.resize(decoded.size)
                # Compare interior pixels; sync edge artifacts are not part of this check.
                a=np.asarray(source,dtype=float)[8:-8,8:-8]
                b=np.asarray(decoded,dtype=float)[8:-8,8:-8]
                self.assertLess(float(np.abs(a-b).mean()),20)
            # Exercise the actual subprocess queue with complete audio and persistent image.
            with wave.open(str(wav)) as inp: pcm=inp.readframes(inp.getnframes())
            gallery=Gallery(root/'gallery');queue=DecodeQueue(gallery)
            session=Session(dict(id='test',band='20 m',freq_khz=14230,name='Test',server='fake',mode='usb'),None,queue,'test')
            try:
                queue.submit(session,pcm,dict(id='b'*32,mode='Robot 36',kind='full',progress_pct=100,capture_utc='2026-10-05T00:00:00Z'))
                wait_for(lambda:len(gallery.snapshot())==1,20)
                self.assertEqual(gallery.snapshot()[0]['kind'],'full')
            finally: queue.stop()


if __name__=='__main__': unittest.main()
