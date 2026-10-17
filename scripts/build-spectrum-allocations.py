#!/usr/bin/env python3
"""Build the offline hover lookup from official EFIS CSV and visible NTIA cells.

NTIA input: DOM export of #frequency-table .allocation-cell from the official
Redbook (columns 4/5), with column, label, and direct child text/notes fields.
See docs/spectrum-allocations.md for provenance and refresh instructions.
No network activity. Reviewed PDF supplements cover omissions in the CSV export.
"""
import argparse,csv,hashlib,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LOW,HIGH=25e6,1700e6

def hz(text):
 m=re.fullmatch(r'\s*([\d.]+)\s*(Hz|kHz|MHz|GHz)\s*',text)
 if not m:raise ValueError('Unrecognized frequency: '+text)
 return round(float(m[1])*dict(Hz=1,kHz=1000,MHz=1000000,GHz=1000000000)[m[2]])

def refs(text):return sorted(set(re.findall(r'\b(?:5\.\d+[A-Z]*|ECA\d+|US\d+[A-Z]*|NG\d+[A-Z]*|G\d+)\b',text)))

def service(text):
 name=re.sub(r'\((?:(?:5\.\d+[A-Z]*|ECA\d+|US\d+[A-Z]*|NG\d+[A-Z]*|G\d+)[,\s]*)+\)','',text).strip()
 letters=''.join(c for c in name.split('(')[0] if c.isalpha())
 return dict(name=name,priority='primary' if letters.isupper() else 'secondary',references=refs(text))

def application(name,note):
 # EFIS frequently lists narrow applications under a much wider allocation.
 # Only apply explicit "Within the band(s) ..." ranges as cursor constraints.
 ranges=[]
 if note.lower().startswith(('within the band ','within the bands ')):
  clause=re.split(r'\.\s',note,maxsplit=1)[0]
  matches=list(re.finditer(r'([\d.]+)\s*[-–]\s*([\d.]+)(?:\s*(Hz|kHz|MHz|GHz))?',clause))
  for match in matches:
   unit=match[3]
   if not unit:
    next_unit=re.search(r'\b(Hz|kHz|MHz|GHz)\b',clause[match.end():]);unit=next_unit[1] if next_unit else None
   if unit:ranges.append([hz(match[1]+' '+unit),hz(match[2]+' '+unit)])
 return dict(name=name,ranges=ranges,note=note)

def build(eca,ntia):
 groups={}
 for row in csv.DictReader(eca.read_text(encoding='utf-8-sig').splitlines(),delimiter=';'):
  if 'footnotenumber' in row['Lower Frequency'].lower():break
  low,high=hz(row['Lower Frequency']),hz(row['Upper Frequency'])
  if high<=LOW or low>HIGH:continue
  allocation=row['European Common Allocation and ECA footnotes']
  key=(low,high,allocation)
  if key not in groups:
   names=re.split(r',\s*(?![^()]*\))',allocation)
   groups[key]=dict(low=low,high=high,services=[service(n) for n in names if n.strip()],references=refs(allocation+' '+row['ECA frequency range footnotes']),applications=[])
  app=row['Applications'].strip()
  if app and app!='-':
   item=application(app,row['Notes'].strip())
   if item not in groups[key]['applications']:groups[key]['applications'].append(item)
 eu=list(groups.values())
 for row in json.loads((ROOT/'UI/spectrum_allocation_supplements.json').read_text())['eu']:
  if not any(existing['low']==row['low'] and existing['high']==row['high'] for existing in eu):eu.append(row)
 eu.sort(key=lambda r:(r['low'],r['high']))
 us=[];raw=json.loads(ntia.read_text());cells=raw['cells'];notes=raw['notes']
 for cell in cells:
  if not cell['lines']:continue
  match=re.match(r'Frequency range ([\d.]+) to ([\d.]+) (kHz|MHz|GHz)\.',cell['label'] or '')
  if not match:raise ValueError('Unrecognized NTIA range: '+str(cell['label']))
  low,high=hz(match[1]+' '+match[3]),hz(match[2]+' '+match[3])
  if high<=LOW or low>HIGH:continue
  start,end=cell['column'];rules=start=='6'
  lines=cell['lines'] if rules else cell['lines'][1:]
  services=[service(row['text']) for row in lines if not row['notes']] if not rules else []
  references=refs(' '.join(row['text'] for row in lines))
  audience='FCC rule categories' if rules else 'Federal / non-federal' if start=='4' and end=='6' else 'Federal' if start=='4' else 'Non-federal'
  us.append(dict(low=low,high=high,services=services,references=references,audience=audience,applications=[dict(name=row['text'],ranges=[],note='FCC rule category for this allocation band') for row in lines] if rules else []))
 # Explicit additional allocations can be in a US footnote rather than a cell.
 # Derive only the unambiguous single-band sentence form; retain all other notes.
 used={note for row in us for note in row['references']}
 for key,text in notes.items():
  if key not in used:continue
  match=re.search(r'The band ([\d.]+)[-–]([\d.]+)\s*MHz is allocated on a (primary|secondary) basis to the ([a-z -]+) service',text)
  if not match:continue
  low,high=hz(match[1]+' MHz'),hz(match[2]+' MHz')
  if high<=LOW or low>HIGH:continue
  us.append(dict(low=low,high=high,services=[dict(name=match[4].capitalize(),priority=match[3],references=[key])],references=[key],audience='By footnote '+key,applications=[]))
 notes={key:value for key,value in notes.items() if key in used}
 us.sort(key=lambda r:(r['low'],r['high'],r['audience']))
 return dict(schema=1,snapshot='2026-10-17',sources=dict(
  eu=dict(title='CEPT / EFIS European Common Allocation Table',version='ERC Report 25 · live EFIS snapshot 2026-10-17',url='https://efis.cept.org/sitecontent.jsp?sitecontent=ecatable',download='https://efis.cept.org/reports/ReportDownloader?reportid=3',sha256=hashlib.sha256(eca.read_bytes()).hexdigest()),
  us=dict(title='NTIA Redbook · United States Table of Frequency Allocations',version='Updated 2026-08-11 · captured 2026-10-17',url='https://redbook.ntia.gov/view/4-17#frequency-table',sha256=hashlib.sha256(ntia.read_bytes()).hexdigest())),eu=eu,us=us,footnotes=dict(us=notes))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--eca-csv',type=Path);p.add_argument('--ntia-dom',type=Path);a=p.parse_args()
 data_path=ROOT/'UI/spectrum_allocations.json'
 if a.eca_csv and a.ntia_dom:
  data=build(a.eca_csv,a.ntia_dom);data_path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
 else:data=json.loads(data_path.read_text())
 main=ROOT/'UI/spectrum.js';text=main.read_text()
 text=re.sub(r'/\* BEGIN GENERATED ALLOCATION LOOKUP \*/.*?/\* END GENERATED ALLOCATION LOOKUP \*/\s*','',text,flags=re.S)
 block='/* BEGIN GENERATED ALLOCATION LOOKUP */\n\'use strict\';\n// Rebuild with scripts/build-spectrum-allocations.py; edit the source module/data.\n'+(ROOT/'UI/spectrum_bands.js').read_text()+'\nconst SPECTRUM_ALLOCATION_DATA='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n/* END GENERATED ALLOCATION LOOKUP */\n'
 main.write_text(block+text)
 print('Packaged',len(data['eu']),'European bands and',len(data['us']),'US entries')
