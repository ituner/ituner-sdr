"""Defer stock Belchertown reports until a real archive record exists.

A dedicated waiting page is served meanwhile. No placeholder observations or
archive timestamps are inserted to satisfy upstream template assumptions.
"""
from weewx.cheetahgenerator import CheetahGenerator
from user.belchertown import HighchartsJsonGenerator

class EmptyCheetah(CheetahGenerator):
 def run(self):
  if self.db_binder.get_manager().firstGoodStamp() is not None:super().run()

class EmptyHighcharts(HighchartsJsonGenerator):
 def run(self):
  if self.db_binder.get_manager().firstGoodStamp() is not None:super().run()
