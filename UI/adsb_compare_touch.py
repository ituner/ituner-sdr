"""Native multi-receiver scorecards and synchronized five-minute packet graph."""
import time
import math
from adsb_compare import comparison_history, comparison_plot, rate_tick_digits


class ComparisonTouch:
    def __init__(self,parent):self.parent=parent;self.data=None;self.next_read=0;self.span=300;self.plot=None
    def draw(self,cache):
        p=self.parent;ui=p.ui
        if time.monotonic()>=self.next_read:
            self.data=p.manager.comparison.snapshot();self.plot=comparison_plot(self.data,self.span);self.next_read=time.monotonic()+1
            # Bound native immediate-mode drawing even after an hour of reception.
            stride=max(1,math.ceil(sum(len(s) for s in self.plot['segments'])/600))
            self.plot['segments']=[s[::stride]+([s[-1]] if (len(s)-1)%stride else []) for s in self.plot['segments']]
        data=self.data;window=data['current'];elapsed=window['duration'] if window else 0
        receivers=(window or {}).get('receivers') or data.get('receivers') or [{},{}]
        colors=[p.CYAN,(173,155,255),(255,191,105),(249,139,169)]
        ui.draw_logical_rect(0,0,1280,800,p.BG)
        p.ink(cache,24,30,'RECEIVER COMPARISON',28)
        p.ink(cache,24,68,'1090 MHz · simultaneous reception',19,p.MUTED,width=520)
        for index,(seconds,label) in enumerate(((300,'5 MIN'),(1800,'30 MIN'),(3600,'1 HOUR'),(43200,'12 HOUR'),(86400,'24 HOUR'))):
            x=576+index*136;p.button(cache,(x,14,x+124,70),label,('comparison_range',seconds),active=self.span==seconds)
        p.ink(cache,24,107,data['status'].replace('_',' '),24,p.CYAN,width=700)
        remaining=max(0,300-int(elapsed));p.ink(cache,1256,107,f'{remaining//60}:{remaining%60:02d} remaining' if window else 'Waiting for every receiver',23,p.MUTED,anchor='rm')
        ui.draw_logical_rect(24,132,1256,137,(*p.LINE[:3],255));ui.draw_logical_rect(24,132,24+1232*min(1,elapsed/300),137,(*p.CYAN,255))
        count=len(receivers);segments=self.plot['segments'];rates=self.plot['rates'] or None
        width=(1232-16*(count-1))/count
        for index,identity in enumerate(receivers):
            color=colors[index%len(colors)];x=24+index*(width+16);row=window['receivers'][index] if window else None
            p.surface((x,154,x+width,374));letter=chr(65+index)
            label=identity.get('label','Primary ADS-B' if index==0 else 'Waiting for receiver').split(' · USB ')[0]
            p.text(cache,x+16,170,f'{letter} · {label}',20,color,width=width-32)
            p.ink(cache,x+16,240,f"{row['packets']:,}" if row else '—',38,color)
            p.ink(cache,x+16,270,'VALID PACKETS · THIS WINDOW',15,p.MUTED)
            values=f"{len(row['aircraft'])} aircraft · {len(row['positioned_aircraft'])} positioned" if row else identity.get('status','Waiting')
            p.ink(cache,x+16,302,values,19,p.MUTED,width=width-32)
            if row:
                rate=f'{rates[index]:.1f}' if rates else '—'
                distance=f"{row['max_range_km']:.1f} km" if row['max_range_km'] is not None else '— km'
                p.ink(cache,x+16,333,f'{rate} pkt/s · {distance}',19,width=width-32)
                p.ink(cache,x+16,357,f"Gain {row['gain']} dB · drops {row['samples_dropped']}",16,p.MUTED,width=width-32)
        p.ink(cache,24,402,'PACKETS / SECOND · AUTO SCALE',20,p.MUTED)
        maximum=self.plot['max']
        left,right,top,bottom=80,1236,426,550
        for i in range(3):
            y=bottom-i*(bottom-top)/2
            ui.draw_logical_polyline([(left,y),(right,y)],(*p.LINE[:3],255),1)
            p.ink(cache,left-10,y,f'{maximum*i/2:,.{rate_tick_digits(maximum)}f}',15,p.MUTED,anchor='rm')
        for minute in range(6):
            label='Now' if minute==5 else f'−{self.span/3600*(5-minute)/5:g}h' if self.span>=43200 else f'−{int(self.span/60*(5-minute)/5)}m'
            p.ink(cache,left+(right-left)*minute/5,568,label,16,p.MUTED,anchor='cm')
        for segment in segments:
            for index in range(count):
                points=[(left+(right-left)*s['elapsed']/self.span,bottom-(bottom-top)*s['rates'][index]/maximum) for s in segment]
                if len(points)>1:ui.draw_logical_polyline(points,(*colors[index%len(colors)],255),3)
        rows=[w for w in comparison_history(data) if w['complete'] and w['valid']]
        if rows:
            latest=rows[-1];text='Last completed · '+time.strftime('%H:%M UTC',time.gmtime(latest['start']))+' · '+'   '.join(f"{chr(65+i)} {r['packets']:,}" for i,r in enumerate(latest['receivers']))
        else:text='Counters reset together every five minutes · results saved automatically'
        p.ink(cache,24,605,text,20,p.MUTED,width=1232)
        p.button(cache,(24,636,540,692),'Stop & restore UAT' if data['enabled'] else 'Start comparison',('comparison_control','comparison_stop' if data['enabled'] else 'comparison_start'))
        reset_recent=data.get('graph_reset_at',0)>0 and data['now']-data['graph_reset_at']<8
        p.button(cache,(556,636,820,692),'GRAPHS RESET' if reset_recent else 'RESET GRAPHS',('comparison_control','comparison_reset'))
        collected=self.plot['available_seconds'];duration=f'{collected/3600:.1f} h' if collected>=3600 else f'{int(collected/60)} min'
        p.ink(cache,1256,666,f'{duration} collected · '+('older data: 1 min avg' if self.span>3600 else '30 s smoothing'),18,p.MUTED,anchor='rm',width=420)
        p.draw_back(cache);p.draw_status(cache,'RECEIVER COMPARISON · '+data['status'],p.message or 'All receivers · five-minute windows · independent antennas',full_width=True)
