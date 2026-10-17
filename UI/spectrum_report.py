"""Self-contained, printable RF survey reports and machine-readable exports."""
import base64
import csv
import html
import io
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image
from spectrum_history import signature


def comparison(data,baseline):
    if not data.get('settings') or not baseline or signature(data)!=signature(baseline):
        return dict(matched=False,reason='Use the same receiver, range, actual gain, PPM, bins, sample rate and FFT.')
    from spectrum_analysis import measured
    a=data.get('power',[]);b=baseline.get('power',[]);_,mask=measured(data);_,other=measured(baseline);delta=[]
    for i in range(min(len(a),len(b))):
        valid=a[i] is not None and b[i] is not None and not (i<len(mask) and mask[i]) and not (i<len(other) and other[i])
        delta.append(round(a[i]-b[i],2) if valid else None)
    values=[d for d in delta if d is not None]
    return dict(matched=True,delta=delta,bins=len(values),median=round(float(np.median(values)),2) if values else None,
                minimum=min(values,default=None),maximum=max(values,default=None),label=baseline.get('label','Saved baseline'),
                method='Latest completed sweep B minus saved sweep A; each sweep averages FFT power in linear units. No mixture of before/after running averages. Relative receive path, not antenna gain or SWR.')


def create_report(survey,label='RF survey',notes='',baseline_id=''):
    with survey.lock:data=json.loads(json.dumps(survey.completed or survey.data))
    if not data.get('updated'):raise ValueError('Receive measurements before exporting a report')
    root=survey.root/'reports';root.mkdir(exist_ok=True)
    if len(list(root.iterdir()))>=100:raise ValueError('Report storage is full (100 reports). Copy or remove old report directories first.')
    identity=str(time.time_ns());target=root/identity;target.mkdir()
    analysis=survey.insights.snapshot(data,columns=800,history=survey.history)
    difference=comparison(data,survey.trace(baseline_id)) if baseline_id else None
    payload=dict(label=str(label).strip()[:80] or 'RF survey',antenna_notes=str(notes).strip()[:2000],comparison=difference,created=time.time(),data=data,analysis=analysis,
                 notes=['Power is uncalibrated dBFS/Hz.','Activity is detected visits / valid sampled visits, not continuous airtime.',
                        'Widths are estimates limited by bin resolution; allocations do not identify a transmitter.',
                        'Each broad sweep samples its frequencies sequentially. Minute history preserves measured peaks and visit counts.'])
    (target/'report.json').write_text(json.dumps(payload,allow_nan=False))
    (target/'metadata.json').write_text(json.dumps({key:payload[key] for key in ('label','created')}))
    output=io.StringIO();writer=csv.writer(output);writer.writerow(('Frequency Hz','Estimated width Hz','Peak dBFS/Hz','Excess above estimated floor dB','Detected visits','Valid visits','Activity percent','First UTC epoch','Last UTC epoch'))
    for s in analysis['signals']:writer.writerow((s['frequency'],s['width'],s['level'],s['excess'],s['active_visits'],s['visits'],s['activity'],s['first'],s['last']))
    (target/'signals.csv').write_text(output.getvalue())
    if difference and difference.get('matched'):
        stream=io.StringIO();writer=csv.writer(stream);writer.writerow(('Frequency Hz','B minus A dB'))
        for i,value in enumerate(difference['delta']):writer.writerow((data['settings']['low']+(i+.5)*data['settings']['bin'],value))
        (target/'comparison.csv').write_text(stream.getvalue())
    if analysis['timeline']:
        codes=np.vstack([np.frombuffer(base64.b64decode(r['values']),np.uint8) for r in reversed(analysis['timeline'])]);palette=np.array(((7,21,37),(25,78,145),(32,170,168),(196,225,116),(255,240,188)),float)
        t=np.clip((codes.astype(float)-202+130)/70,0,1)*4;i=np.minimum(3,t.astype(int));f=(t-i)[...,None];rgb=(palette[i]*(1-f)+palette[i+1]*f).astype('uint8');rgb[codes==0]=(8,18,29);rgb[codes==1]=(232,148,72)
        Image.fromarray(rgb).resize((1000,max(180,min(800,len(codes)*3))),Image.Resampling.NEAREST).save(target/'waterfall.png')
    else:Image.new('RGB',(1000,180),(8,18,29)).save(target/'waterfall.png')
    config=data['settings'];power=data.get('peak',[]);finite=[p for p in power if p is not None];lo=min(finite,default=-130)-5;hi=max(max(finite,default=-60)+5,lo+20)
    segments=[];points=[]
    for index,value in enumerate(power):
        if value is None:
            if points:segments.append(points);points=[]
            continue
        points.append(f'{50+index/max(1,len(power)-1)*920:.1f},{30+(hi-value)/(hi-lo)*240:.1f}')
    if points:segments.append(points)
    svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 330"><rect width="1000" height="330" fill="#0c1620"/>'
    for i in range(6):
        y=30+i*48;svg+=f'<path d="M50 {y}H970" stroke="#294052"/><text x="4" y="{y+4}" fill="#a7bccc" font-size="14">{hi-(hi-lo)*i/5:.0f}</text>'
    for pts in segments:svg+=f'<polyline points="{" ".join(pts)}" fill="none" stroke="#70e2c0" stroke-width="1"/>'
    svg+=f'<text x="50" y="310" fill="#bfd7e5" font-size="18">{config["low"]/1e6:g}–{config["high"]/1e6:g} MHz · peak hold · relative dBFS/Hz</text></svg>'
    (target/'spectrum.svg').write_text(svg)
    esc=html.escape;rows=''.join('<tr>'+''.join('<td>'+esc(str(v))+'</td>' for v in (f'{s["frequency"]/1e6:.6f}',f'{s["width"]/1000:g}',f'{s["excess"]:.1f}',f'{s["active_visits"]}/{s["visits"]}',s['activity']))+'</tr>' for s in analysis['signals'])
    picture=base64.b64encode((target/'waterfall.png').read_bytes()).decode()
    metadata=f'{config["low"]/1e6:g}–{config["high"]/1e6:g} MHz · {config["bin"]/1000:g} kHz bins · {config["gain"]:g} dB actual gain · USB {data.get("device",{}).get("serial","unknown")}'
    comparison_html=''
    if difference:
        comparison_html='<h2>Antenna / cable comparison</h2><p>'+esc(f"Median B − A: {difference['median']} dB across {difference['bins']} valid bins. "+difference['method'] if difference.get('matched') else difference['reason'])+'</p>'
        if difference.get('matched'):comparison_html+='<a href="comparison.csv">Download frequency differences CSV</a>'
    body=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{esc(payload['label'])}</title>
<style>body{{font:16px system-ui;margin:32px auto;max-width:1100px;padding:0 24px;color:#1a2f3b}}h1{{font-size:32px}}p{{line-height:1.6}}img,svg{{width:100%;height:auto}}table{{border-collapse:collapse;width:100%}}td,th{{padding:10px;text-align:left;border-bottom:1px solid #ccd5db}}button,a{{padding:12px;display:inline-block}}@media print{{button,.downloads{{display:none}}}}</style>
<h1>{esc(payload['label'])}</h1><p>{time.strftime('%d %b %Y %H:%M UTC',time.gmtime(payload['created']))}<br>{esc(metadata)}</p>
<p><strong>Antenna / cable notes:</strong> {esc(payload['antenna_notes']) or 'Not supplied'}</p>{comparison_html}
<button onclick="window.print()">Print / save PDF</button><div class="downloads"><a href="signals.csv">Signal CSV</a><a href="report.json">Full survey JSON</a><a href="waterfall.png">Waterfall PNG</a></div>
{svg}<h2>Time history · newest at top</h2><p>Measured minute buckets; peak per bin, counts retained. Missing frequencies remain dark. Frequency span matches the spectrum above. Colour scale −130 to −60 dBFS/Hz.</p><img src="data:image/png;base64,{picture}" alt="Measured spectrum history">
<h2>Discovered signals</h2><p>{analysis['visits']} completed visits · +{analysis['threshold']:g} dB detection threshold above estimated local floor.</p><table><thead><tr><th>MHz</th><th>Width kHz</th><th>Excess dB</th><th>Detected / valid</th><th>Activity %</th></tr></thead><tbody>{rows}</tbody></table><h2>Measurement notes</h2><ul>{''.join('<li>'+esc(n)+'</li>' for n in payload['notes'])}</ul></html>'''
    (target/'index.html').write_text(body);survey.event('report','Report saved · '+identity);return identity
