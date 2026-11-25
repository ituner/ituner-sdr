import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import app_update as u

class DeviceStepsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.stage=self.base/'stage';self.stage.mkdir()
        self.cfg=dict(platform='linux',state=str(self.base/'state'),user='ituner',system_steps_version=1,cm5_quiet_halt=True)
        Path(self.cfg['state']).mkdir()
        self.calls=[];self.current='[all]\nBOOT_ORDER=0xf2461\nPOWER_OFF_ON_HALT=1\n'
        self.mapping={}
        for absolute,text in [('/proc/device-tree/model','Raspberry Pi Compute Module 5 Rev 1.0'),('/proc/sys/kernel/random/boot_id','boot-one')]:
            target=self.base/absolute.lstrip('/');target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text);self.mapping[absolute]=target
        firmware=self.base/'firmware';image=firmware/'latest/pieeprom-2025-11-27.bin';image.parent.mkdir(parents=True);image.write_bytes(b'firmware')
        self.mapping['/usr/lib/firmware/raspberrypi/bootloader-2712']=firmware
        for absolute in ['/usr/local/sbin/ituner-power','/etc/sudoers.d/90-ituner-power','/usr/local/sbin/ituner-network','/etc/sudoers.d/90-ituner-network']:
            target=self.base/absolute.lstrip('/');target.parent.mkdir(parents=True,exist_ok=True);self.mapping[absolute]=target
        source=self.stage/'scripts/ituner-power';source.parent.mkdir();source.write_text('fixed helper')
        (self.stage/'systemd').mkdir()
        (self.stage/'systemd/ituner-network').write_text('network helper')
        (self.stage/'systemd/90-ituner-network').write_text('ituner ALL=(root) NOPASSWD: /usr/local/sbin/ituner-network status\n')
        def path(value): return self.mapping.get(str(value),Path(value))
        self.paths=patch.object(u,'Path',side_effect=path);self.paths.start();self.addCleanup(self.paths.stop)
        self.owner=patch.object(u.os,'chown');self.owner.start();self.addCleanup(self.owner.stop)
    def runner(self,args,**kwargs):
        self.calls.append(args)
        if args==['rpi-eeprom-config']: return SimpleNamespace(stdout=self.current)
        if args==['vcgencmd','bootloader_version']:return SimpleNamespace(stdout='timestamp 1764250826\n')
        return SimpleNamespace(stdout='up to date')
    def run_steps(self):return u.system_update_steps(self.cfg,self.stage,{'system_steps':list(u.SYSTEM_STEPS)},runner=self.runner)
    def test_applies_matching_image_and_preserves_boot_order(self):
        self.assertIn('Reboot',self.run_steps())
        apply=next(c for c in self.calls if '--apply' in c)
        text=Path(apply[2]).read_text()
        self.assertIn('BOOT_ORDER=0xf2461',text);self.assertEqual(text.count('POWER_OFF_ON_HALT='),1)
        self.assertTrue(apply[3].endswith('/latest/pieeprom-2025-11-27.bin'))
        self.assertEqual((Path(self.cfg['state'])/'device-steps/eeprom-before-quiet-halt.conf').read_text(),self.current)
        self.assertEqual(self.mapping['/usr/local/sbin/ituner-power'].stat().st_mode & 0o777,0o755)
    def test_retry_before_reboot_does_not_flash_twice(self):
        self.run_steps();self.run_steps()
        self.assertEqual(sum('--apply' in c for c in self.calls),1)
    def test_failed_write_is_not_marked_complete(self):
        def fail(args,**kwargs):
            if '--apply' in args:raise subprocess.CalledProcessError(1,args)
            return self.runner(args,**kwargs)
        with self.assertRaises(subprocess.CalledProcessError):
            u.system_update_steps(self.cfg,self.stage,{'system_steps':['cm5-quiet-halt-v1']},runner=fail)
        journal=u.read_json(Path(self.cfg['state'])/'device-steps/cm5-quiet-halt-v1.json')
        self.assertFalse(journal['applied'])
    def test_existing_quiet_halt_does_not_flash(self):
        self.current=self.current.replace('=1','=0');self.run_steps()
        self.assertFalse(any('--apply' in c for c in self.calls))
    def test_reboot_verification_failure_is_visible(self):
        self.run_steps();self.mapping['/proc/sys/kernel/random/boot_id'].write_text('boot-two')
        with self.assertRaisesRegex(RuntimeError,'did not verify'):self.run_steps()
    def test_other_carriers_receive_power_controls_without_eeprom_changes(self):
        self.cfg['cm5_quiet_halt']=False;self.run_steps()
        self.assertFalse(any(c[0].startswith('rpi-eeprom') for c in self.calls))
    def test_missing_current_image_never_uses_default_firmware(self):
        for image in self.mapping['/usr/lib/firmware/raspberrypi/bootloader-2712'].glob('*/*'):image.unlink()
        with self.assertRaisesRegex(RuntimeError,'Matching EEPROM'):self.run_steps()
        self.assertFalse(any('--apply' in c for c in self.calls))
    def test_unknown_step_and_old_helper_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'newer updater'):
            u.system_update_steps(self.cfg,self.stage,{'system_steps':['arbitrary-script']},runner=self.runner)
        self.cfg['system_steps_version']=0
        with self.assertRaisesRegex(RuntimeError,'Upgrade the updater'):self.run_steps()
        self.assertEqual(self.calls,[])
    def test_mac_skips_all_device_changes(self):
        self.cfg['platform']='darwin';self.assertEqual(self.run_steps(),'');self.assertEqual(self.calls,[])
    def test_merge_overrides_conditional_settings_without_losing_them(self):
        original='[all]\nBOOT_ORDER=0xf2461\n[board]\nPOWER_OFF_ON_HALT=1\nBOOT_UART=1\n'
        result=u.quiet_halt_config(original)
        self.assertIn('[board]\nBOOT_UART=1',result)
        self.assertTrue(result.endswith('[all]\nPOWER_OFF_ON_HALT=0\n'))
