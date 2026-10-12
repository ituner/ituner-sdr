import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
try:
    from decoder_bench import errors,read_wav,write_wav,synth
except ModuleNotFoundError as exc:
    if exc.name in ('scipy','scipy.signal'):
        raise unittest.SkipTest('Optional decoder comparison requires scipy') from exc
    raise

class ComparisonTests(unittest.TestCase):
    def test_score_counts_substitution_insertion_deletion(self):
        self.assertEqual(errors('ABC','AXC')['edit_distance'],1)
        self.assertEqual(errors('ABC','ABCD')['edit_distance'],1)
        self.assertEqual(errors('ABC','AC')['edit_distance'],1)
        self.assertEqual(errors('CQ DE',' cq\n de ')['cer'],0)
        self.assertEqual(errors('','EEE')['extra_characters'],3)
        self.assertIsNone(errors('','')['cer'])
        self.assertGreater(errors('A','ABCDE')['cer'],1)

    def test_wav_preserves_generated_signal_and_rejects_wrong_rate(self):
        import wave
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'test.wav';audio=synth('CQ',20)
            write_wav(path,audio)
            np.testing.assert_allclose(read_wav(path),audio,atol=1/16384)
            with wave.open(str(path),'wb') as wav:
                wav.setparams((1,2,12000,0,'NONE','none'));wav.writeframes(b'\0\0'*100)
            with self.assertRaises(ValueError):read_wav(path)

if __name__=='__main__':unittest.main()
