import sys
from pathlib import Path
import tempfile
import unittest
import wave
import numpy as np
from PIL import Image
from test_sstv import tone, header
from sstv_decoder import FrameAssembler, decoder_for, decode_file, RATE
from sstv_modes import EXTENDED_VIS_MAP, NARROW_VIS_MAP, MODE_COUNT


def extended_header(code):
    return tone(1900,.3)+tone(1200,.01)+tone(1900,.3)+tone(1200,.03)+b''.join(tone(1100 if code>>i&1 else 1300,.03) for i in range(16))+tone(1200,.03)


def narrow_header(code):
    values=[0x2d,0x15,code,code^0x15]
    return tone(1900,.3)+tone(2100,.1)+tone(1900,.022)+b''.join(tone(1900 if value>>(5-i)&1 else 2100,.022) for value in values for i in range(6))


class AdditionalFramingTests(unittest.TestCase):
    def test_extended_and_narrow_headers_across_packets(self):
        self.assertEqual(MODE_COUNT,48)
        for mapping,make_header in ((EXTENDED_VIS_MAP,extended_header),(NARROW_VIS_MAP,narrow_header)):
            for code,mode in mapping.items():
                for prefix in (0,5900,17222,23500):
                    states=[]
                    asm=FrameAssembler(lambda *a:None,lambda *a:states.append(a))
                    pcm=bytes(prefix)+make_header(code)+tone(2044 if getattr(mode,'NARROW',False) else 1500,3)
                    for i in range(0,len(pcm),1024):asm.feed(pcm[i:i+1024])
                    self.assertIn(('RECEIVING',mode.NAME),states,(mode.NAME,prefix,states))

    def test_noise_and_bad_stop_do_not_report_unsupported_modes(self):
        states=[]
        asm=FrameAssembler(lambda *a:None,lambda *a:states.append(a))
        rng=np.random.default_rng(22)
        pcm=rng.integers(-9000,9000,RATE*30,dtype=np.int16).tobytes()
        for i in range(0,len(pcm),4096):asm.feed(pcm[i:i+4096])
        self.assertFalse(states)
        pcm=header(124)[:-720]+tone(1500,.03)+bytes(24000)
        decoder=decoder_for(pcm)
        at=decoder._find_header()
        with self.assertRaisesRegex(ValueError,'stop bit'):decoder._decode_vis(at)

    def test_narrow_checksum(self):
        pcm=narrow_header(2)
        pcm=pcm[:-528]+tone(2100,.022)+tone(1500,1)
        d=decoder_for(pcm);at=d._find_header()
        with self.assertRaisesRegex(ValueError,'checksum'):d._decode_vis(at)


try:
    from pysstv import color,grayscale
except ImportError:color=grayscale=None


@unittest.skipIf(color is None,'PySSTV test encoder is optional')
class IndependentModeTests(unittest.TestCase):
    def test_all_pysstv_added_modes(self):
        classes=[color.PD90,color.PD120,color.PD160,color.PD180,color.PD240,color.PD290,
                 color.PasokonP3,color.PasokonP5,color.PasokonP7,color.WraaseSC2120,color.WraaseSC2180,
                 grayscale.Robot8BW,grayscale.Robot24BW]
        with tempfile.TemporaryDirectory() as temp:
            for cls in classes:
                with self.subTest(mode=cls.__name__):
                    a=np.zeros((cls.HEIGHT,cls.WIDTH,3),dtype=np.uint8)
                    a[:,:,0]=np.linspace(0,255,cls.WIDTH,dtype=np.uint8)[None,:]
                    a[:,:,1]=np.linspace(0,255,cls.HEIGHT,dtype=np.uint8)[:,None]
                    a[:,:,2]=255-a[:,:,0]
                    source=Image.fromarray(a)
                    if cls in grayscale.MODES:source=source.convert('L').convert('RGB')
                    wav=Path(temp)/'test.wav';png=Path(temp)/'test.png'
                    cls(source,RATE,16).write_wav(str(wav))
                    result=decode_file(wav,png)
                    output=Image.open(png).convert('RGB')
                    self.assertEqual(output.size,source.size)
                    self.assertGreater(result['row_corr_mean'],.8)
                    self.assertLess(abs(np.array(source,float)[8:-8,8:-8]-np.array(output,float)[8:-8,8:-8]).mean(),15)


class MMSSpecificationTests(unittest.TestCase):
    def test_mmsstv_mp_mr_ml_and_narrow_image_fixtures(self):
        # Independent protocol fixtures from JE3HHT's mode.txt and sstv.cpp,
        # not constructed from our decoder's mode objects or offsets.
        fixtures=[('MP73',0x2523,320,256,.140,'pair',False),
                  ('MR73',0x4523,320,256,.138,'half',False),
                  ('ML180',0x8523,640,496,.1765,'half',False),
                  ('MP73-N',2,320,256,.140,'pair',True),
                  ('MC110-N',0x14,320,256,.140,'rgb',True)]
        colors=np.array([[230,30,20],[20,210,40],[30,50,220],[220,210,40],
                         [20,210,210],[210,40,210],[190,190,190],[40,40,40]],dtype=np.uint8)
        with tempfile.TemporaryDirectory() as temp:
            for name,code,width,height,scan,kind,narrow in fixtures:
                with self.subTest(mode=name):
                    image=Image.fromarray(np.tile(np.repeat(colors,width//8,axis=0)[None,:,:],(height,1,1)))
                    values=np.asarray(image.convert('YCbCr'))[0,::width//8]
                    chunks=[narrow_header(code) if narrow else extended_header(code)]
                    total=0.;count=0;phase=0.
                    def add(frequency,seconds):
                        nonlocal total,count,phase
                        total+=seconds*RATE;n=round(total)-count;count+=n
                        angles=phase+np.arange(n)*2*np.pi*frequency/RATE
                        chunks.append((np.sin(angles)*12000).astype('<i2').tobytes())
                        phase=(phase+n*2*np.pi*frequency/RATE)%(2*np.pi)
                    def component(samples,duration):
                        for sample in samples:
                            frequency=(2044+float(sample)*256/255) if narrow else (1500+float(sample)*800/255)
                            add(frequency,duration/8)
                        return frequency
                    for line in range(height//2 if kind=='pair' else height):
                        add(1900 if narrow else 1200,.008 if kind=='rgb' else .009)
                        add(2044 if narrow else 1500,.0005 if kind=='rgb' else .001)
                        if kind=='pair':
                            for c in (0,2,1,0):component(values[:,c],scan)
                        elif kind=='half':
                            for c,duration in ((0,scan),(2,scan/2),(1,scan/2)):
                                last=component(values[:,c],duration);add(last,.0001)
                        else:
                            for c in (0,1,2):component(colors[:,c],scan)
                    wav=Path(temp)/'test.wav';png=Path(temp)/'test.png'
                    with wave.open(str(wav),'wb') as w:
                        w.setnchannels(1);w.setsampwidth(2);w.setframerate(RATE);w.writeframes(b''.join(chunks))
                    result=decode_file(wav,png)
                    output=Image.open(png).convert('RGB')
                    self.assertEqual(result['mode'],name)
                    self.assertEqual(output.size,image.size)
                    self.assertGreater(result['row_corr_mean'],.8)
                    self.assertLess(abs(np.array(image,float)[8:-8,8:-8]-np.array(output,float)[8:-8,8:-8]).mean(),18)


if __name__=='__main__':unittest.main()
