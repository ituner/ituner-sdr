"""Bounded QRSS acquisition from spectrum history; never confirms a callsign.

Searches for keyed carriers and complementary FSK tone pairs across the visible
band. Fits mark/space run lengths to Morse's 1:3:7 timing, then replays the
buffered signal so acquisition does not discard the beginning of a message.
"""
from collections import deque
import numpy as np


def runs(states, times):
    """Complete runs only: a capture may begin/end halfway through an element."""
    edges=np.flatnonzero(np.diff(states)!=0)+1
    return [(int(states[a]),float(times[b]-times[a])) for a,b in zip(edges[:-1],edges[1:])]


def timing(states,times):
    values=runs(states,times)
    values=[(s,d) for s,d in values if s>=0 and d>=.8]
    if len(values)<6 or sum(s==1 for s,d in values)<3 or sum(s==0 for s,d in values)<3:return None
    s=np.array([s for s,d in values]);d=np.array([d for s,d in values])
    candidates=np.unique(np.round(np.concatenate([d,d/3,d/7]),2))
    candidates=candidates[(candidates>=2)&(candidates<=90)]
    best=None
    for dot in candidates:
        ratios=d/dot
        expected=np.where(s[:,None]==1,np.array([1.,3.,3.]),np.array([1.,3.,7.]))
        distance=np.abs(ratios[:,None]-expected)
        closest=expected[np.arange(len(d)),distance.argmin(axis=1)]
        error=np.min(distance,axis=1)/np.sqrt(closest)
        good=error<.42
        if np.mean(good)<.80:continue
        # Reject subharmonic timing: real single-dot marks AND gaps must exist.
        if not np.any(good&(s==1)&(closest==1)) or not np.any(good&(s==0)&(closest==1)):continue
        loss=float(np.mean(np.minimum(error,2)))
        if best is None or loss<best[0]:
            # Keyed CW FFT edges lengthen marks and shorten spaces (or vice
            # versa). Fit that opposite edge bias separately from dot time.
            design=np.stack([closest[good],2*s[good]-1],axis=1)
            solution=np.linalg.lstsq(design,d[good],rcond=None)[0]
            refined=float(solution[0])
            if not 2-1e-8<=refined<=90+1e-8:continue
            refined=float(np.clip(refined,2,90))
            best=(loss,refined,float(np.mean(good)))
    return None if best is None else dict(dot=best[1],fit=best[2],loss=best[0],runs=len(values))


def fit_timing(states,times):
    """Fit first, then reject dropouts too short for this station's cadence.

    A strong neighbor's keying edge can briefly lift the band noise floor.
    Filtering uses the individual dot estimate, never a shared fixed speed.
    Unknown carrier-loss states are not bridged into invented Morse elements.
    """
    fit=timing(states,times)
    if fit is None:return states,None
    cleaned=states.copy()
    edges=np.r_[0,np.flatnonzero(np.diff(states)!=0)+1,len(states)]
    for k in range(1,len(edges)-2):
        a,b=edges[k:k+2]
        if times[b]-times[a]>=.25*fit['dot']:continue
        if states[a]>=0 and states[a-1]>=0 and states[a-1]==states[b]:cleaned[a:b]=states[a-1]
    refined=timing(cleaned,times)
    return (cleaned,refined) if refined is not None else (states,fit)


class AutoAcquisition:
    MAX_TRACKS = 6
    MAX_RECENT = 12

    def __init__(self,frequencies,morse_factory,hop_seconds):
        self.frequencies=np.asarray(frequencies)
        self.df=float(np.median(np.diff(frequencies)))
        self.factory=morse_factory
        self.capacity=int(1200/hop_seconds)+1
        self.reset()

    def reset(self):
        self.history=deque(maxlen=self.capacity);self.times=deque(maxlen=self.capacity)
        self.next_analysis=0;self.lock=None
        self.tracks=[];self.next_track_id=1;self.superseded=deque(maxlen=128)
        self.events=deque(maxlen=2000)
        self.status=dict(state='searching',detail='Searching the waterfall for a keyed signal')

    def feed(self,when,db):
        # Relative spectral level; independent of Kiwi AGC's absolute level.
        self.history.append((db-np.median(db)).astype(np.float32));self.times.append(when)
        if when>=self.next_analysis and len(self.times)>30:
            self.next_analysis=when+10
            self.analyze()

    @staticmethod
    def clean(states):
        # A three-frame median removes isolated FFT transition/impulse glitches.
        result=states.copy()
        if len(states)>2:result[1:-1]=np.median(np.stack([states[:-2],states[1:-1],states[2:]]),axis=0)
        return result

    def candidates(self,times,data):
        """Apply the same signal/timing gates independently to one interval."""
        strength=np.percentile(data,85,axis=0)
        # Bounded search includes weaker peaks, not only the loudest station.
        peaks=[]
        for i in np.argsort(strength)[::-1]:
            if strength[i]<12:break
            if i<1 or i>=len(strength)-1:continue
            if any(abs(i-j)<=2 for j in peaks):continue
            if strength[i]<max(strength[i-1],strength[i+1]):continue
            peaks.append(int(i))
            if len(peaks)==24:break
        envelopes={i:np.max(data[:,max(0,i-1):i+2],axis=1) for i in peaks}
        candidates=[]
        for a,i in enumerate(peaks):
            high=envelopes[i]
            for j in peaks[a+1:]:
                shift=abs(self.frequencies[i]-self.frequencies[j])
                if not 2.5*self.df<=shift<=25:continue
                low=envelopes[j]
                present=np.maximum(high,low)>10
                exclusive=np.abs(high-low)>6
                if np.mean(present&exclusive)<.72:continue
                states=self.clean(np.where(present,np.where(high>low,1,0),-1))
                if min(np.mean(states==0),np.mean(states==1))<.08:continue
                # Without a long inter-word gap the polarities can fit
                # equally well. Prefer conventional high-tone marks, but
                # allow better timing evidence to override that small prior.
                for reverse in (False,True):
                    seq=np.where(states<0,-1,1-states) if reverse else states
                    seq,fit=fit_timing(seq,times)
                    if not fit:continue
                    level=min(float(np.median(high[states==1])),float(np.median(low[states==0])))
                    mark_bin,space_bin=(j,i) if reverse else (i,j)
                    polarity_prior=.04 if self.frequencies[mark_bin]>self.frequencies[space_bin] else 0
                    score=fit['fit']-fit['loss']+min(level,80)/100
                    score+=.15*float(np.mean(present&exclusive))+.15+polarity_prior
                    candidates.append(dict(fit,mode='FSKCW',mark=mark_bin,
                        space=space_bin,states=seq,score=score))
            # On/off keying needs a real low level, not just fluctuations in
            # a continuously transmitting carrier's strength.
            if np.mean(high<6)<.15 or np.mean(high>12)<.08:continue
            threshold=max(9,float(np.percentile(high,85))-6)
            states,fit=fit_timing(self.clean((high>threshold).astype(int)),times)
            if fit:
                level=float(np.median(high[high>12]))
                candidates.append(dict(fit,mode='CW',mark=i,space=None,states=states,
                    score=fit['fit']-fit['loss']+min(level,80)/100))
        # Ignore stale candidates before ranking, so a disappeared strong
        # station cannot prevent acquisition of a new, weaker station.
        fresh=[]
        for row in candidates:
            edges=np.flatnonzero(np.diff(row['states'])!=0)
            limit=max(90,row['dot']*12)
            if not len(edges) or times[-1]-times[edges[-1]]>limit:continue
            tail=times>=times[-1]-limit
            active=envelopes[row['mark']]>10
            if row['space'] is not None:active|=envelopes[row['space']]>10
            if np.any(active&tail):fresh.append(row)
        for row in fresh:
            row['times']=times
            row['window_seconds']=float(times[-1]-times[0])
            # Prefer more timing evidence when otherwise equally convincing.
            row['score']+=.025*np.log1p(row['runs'])
        return fresh

    def analyze(self):
        times=np.array(self.times);data=np.stack(self.history)
        candidates=[];starts=set()
        # Revisited every ten seconds: adjacent windows overlap, allowing a
        # recent readable burst to acquire despite older interference. Keep
        # the complete history for QRSS30/60/90, which needs longer evidence.
        for seconds in (120,240,480,1200):
            start=int(np.searchsorted(times,times[-1]-seconds))
            if start in starts:continue
            starts.add(start)
            candidates.extend(self.candidates(times[start:],data[start:]))
        # If the same station fits a longer interval, use its greater timing
        # evidence. A short fragment can fit both FSK polarities perfectly;
        # it must not override the word gaps seen in the longer interval.
        supported=[]
        for row in sorted(candidates,key=lambda r:r['window_seconds'],reverse=True):
            pair=tuple(sorted([row['mark'],row['space'] if row['space'] is not None else row['mark']]))
            if any(key==pair and duration>row['window_seconds'] for key,duration in supported):continue
            supported.append((pair,row['window_seconds']))
            row['supported']=True
        candidates=[r for r in candidates if r.get('supported')]
        # Prefer existing tracks slightly, without binding one station to
        # another station's cadence or keeping a stale signal selected.
        previous=[r for r in self.tracks if r['active']]
        for row in candidates:
            if any(self.matches(row,track) for track in previous):row['score']+=.08
        selected=[];occupied=[]
        for row in sorted(candidates,key=lambda r:r['score'],reverse=True):
            bins=[row['mark']]+([] if row['space'] is None else [row['space']])
            # A complementary FSK pair owns BOTH tones. Never emit it again
            # as reverse polarity, two CW tracks, or a nearby spectral peak.
            if any(abs(i-j)<=2 for i in bins for j in occupied):continue
            selected.append(row);occupied.extend(bins)
            if len(selected)>=self.MAX_TRACKS:break
        for track in self.tracks:track['active']=False
        used=set();active=[]
        for row in selected:
            matches=[r for r in self.tracks if r['id'] not in used and self.matches(row,r)]
            track=min(matches,key=lambda r:abs(r['tone_hz']-self.frequencies[row['mark']]),default=None)
            tone=float(self.frequencies[row['mark']])
            space=tone if row['space'] is None else float(self.frequencies[row['space']])
            same=track is not None and abs(tone-track['tone_hz'])<3
            if track is None:
                track=dict(id=f"T{self.next_track_id}",events=deque(maxlen=2000))
                self.next_track_id+=1;self.tracks.append(track)
            decoder=self.factory(row['dot'])
            window_times=row['times']
            for t,state in zip(window_times,row['states']):decoder.feed(None if state<0 else bool(state),float(t))
            boundary=window_times[0]
            if boundary>2:
                # A window may begin inside a letter. Stitch only after its
                # first character gap, preserving older text before that seam.
                # A fixed 20-dot margin could swallow an entire short window.
                edges=np.r_[0,np.flatnonzero(np.diff(row['states'])!=0)+1,len(window_times)]
                boundary=float(window_times[-1])+1
                for a,b in zip(edges[:-1],edges[1:]):
                    end=window_times[min(b,len(window_times)-1)]
                    if row['states'][a]==0 and end-window_times[a]>=2.5*row['dot']:
                        boundary=float(end)
                        break
            older=[e for e in track['events'] if e[0]<boundary] if same else []
            replay=[e for e in decoder.events if not older or e[0]>=boundary]
            track.update(mode=row['mode'],tone_hz=tone,space_hz=space,
                shift_hz=abs(tone-space),dot=row['dot'],timing_fit=round(row['fit'],2),
                reverse=bool(tone<space),active=True,last_seen=float(times[-1]),
                acquisition_seconds=round(row['window_seconds'],1),
                partial_morse=decoder.partial().strip(),partial_when=float(times[-1]),
                events=deque(older+replay,maxlen=2000))
            used.add(track['id']);active.append(track)
        # Retain recent text after a signal fades. Both history and bookkeeping
        # remain bounded even if stations repeatedly enter and leave the span.
        for r in self.tracks:
            if not r['active'] and any(min(abs(f-r['tone_hz']),abs(f-r['space_hz']))<=2*self.df for f in self.frequencies[occupied]):
                self.superseded.append(r['id'])
        recent=sorted((r for r in self.tracks if not r['active'] and r['id'] not in self.superseded and
            times[-1]-r['last_seen']<1200),key=lambda r:r['last_seen'],reverse=True)
        self.tracks=active+recent[:self.MAX_RECENT-len(active)]
        if not active:
            self.lock=None
            self.status=dict(state='searching',track_count=0,detail='Searching: waiting for consistent Morse transitions')
            return
        # Single-track fields stay compatible with saved captures and manual
        # callers. Multi-signal text is ALWAYS stored separately, never mixed.
        best=active[0]
        self.events=best['events']
        self.lock={k:best[k] for k in ('mode','tone_hz','space_hz','shift_hz','dot')}
        self.status=self.track_status(best)
        self.status.update(state='locked',track_count=len(active),
            detail='Auto · '+str(len(active))+' signal'+('s' if len(active)!=1 else '')+' · '+
            ' / '.join(f"{r['id']} {r['tone_hz']:.1f} Hz {r['dot']:.2f} s/dot" for r in active))

    def matches(self,row,track):
        if row['mode']!=track['mode']:return False
        tone=float(self.frequencies[row['mark']])
        space=tone if row['space'] is None else float(self.frequencies[row['space']])
        # Pair identity survives a polarity correction; its provisional text
        # does not (the replay above then replaces it).
        old=sorted([track['tone_hz'],track['space_hz']]);new=sorted([tone,space])
        return max(abs(a-b) for a,b in zip(old,new))<3

    @staticmethod
    def track_status(track):
        return dict(id=track['id'],mode=track['mode'],tone_hz=round(track['tone_hz'],2),
            shift_hz=round(track['shift_hz'],2),dot_seconds=round(track['dot'],2),
            timing_fit=track['timing_fit'],reverse=track['reverse'],active=track['active'],
            acquisition_seconds=track.get('acquisition_seconds'))

    def snapshot(self,start,end):
        """Independent text for a capture interval; times are stream seconds."""
        result=[]
        for track in sorted(self.tracks,key=lambda r:r['tone_hz'],reverse=True):
            events=[(t,c) for t,c in track['events'] if start<=t<=end]
            text=''.join(c for t,c in events).strip()
            if not text and not track['active']:continue
            row=self.track_status(track)
            row.update(tentative_text=text[-500:],partial_morse=track.get('partial_morse','')
                if start<=track.get('partial_when',-1)<=end else '')
            result.append(row)
        return result
