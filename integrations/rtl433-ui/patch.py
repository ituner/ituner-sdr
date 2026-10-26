"""Apply the small iTuner integration to the pinned upstream source checkout."""
from pathlib import Path
import shutil
import sys

root=Path(sys.argv[1]);source=Path(__file__).parent
for filename,destination in (('broker-adapter.cjs','server/ituner-broker.cjs'),('scanner.cjs','server/scanner.cjs'),('integration.cjs','server/ituner-integration.cjs'),('controls.js','frontend/ituner-controls.js'),('activity.cjs','server/activity.cjs'),('activity.js','frontend/decoder-activity.js')):
    shutil.copyfile(source/filename,root/destination)
shutil.copyfile(source.parent.parent/'UI/rtl433_profiles.json',root/'server/rtl433_profiles.json')
p=root/'server/scanner.cjs'
p.write_text(p.read_text().replace("require('../../UI/rtl433_profiles.json')","require('./rtl433_profiles.json')"))
(root/'server/rtl433proc.js').write_text("'use strict';\nmodule.exports = require('./ituner-broker.cjs').createAdapter();\n")
p=root/'server/index.js';s=p.read_text()
s=s.replace("app.use(express.static", "require('./ituner-integration.cjs')(app);\n\napp.use(express.static",1)
p.write_text(s)
p=root/'frontend/index.html';s=p.read_text().replace("'868M'","'868.3M'").replace('data-freq="868M"','data-freq="868.3M"')
s=s.replace('>868 MHz</button>','>868.3 MHz</button>')
s=s.replace('Without a config file rtl_433 runs on default settings hopping 433.92M / 868M / 315M / 915M with all protocols enabled.', 'The shared iTuner receiver listens on the selected band. Choose a listening band directly in the dashboard. Intelligent Scan explores the complete band list on CM5, even with the browser closed.')
s=s.replace('only if you need to override gain, protocols, or frequencies.', 'using frequency, gain and ppm. Other receiver directives are managed by iTuner.')
s=s.replace('</body>','<script src="ituner-controls.js"></script>\n</body>');p.write_text(s)
p=root/'frontend/app.js';s=p.read_text().replace("'868M'","'868.3M'")
s=s.replace('Math.floor((Date.now() - ts) / 1000)','Math.max(0, Math.floor((Date.now() - ts) / 1000))')
# Replace the browser hopping loop: there must only be one scanner authority.
start=s.index('// ── Frequency scanner ')
end=s.index('// ── RSSI filter ',start)
s=s[:start]+'// Intelligent Scan is managed on CM5 by ituner-controls.js.\n\n'+s[end:]
# Surface rejected managed configuration instead of claiming a save succeeded.
s=s.replace("    await fetch(API_BASE + '/api/rtl433/config', {", "    const saved = await fetch(API_BASE + '/api/rtl433/config', {",1)
needle="    // Show brief feedback on the button"
s=s.replace(needle,"    if (!saved.ok) throw new Error((await saved.json()).error || 'Configuration rejected');\n"+needle,1)
p.write_text(s)
