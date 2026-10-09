#include "ggmorse/ggmorse.h"
#include <cstring>
#include <vector>
#include <algorithm>
#include <cmath>

struct Decoder {
    GGMorse engine;
    std::vector<unsigned char> pending;
    Decoder(float tone, float wpm) : engine(parameters()) {
        auto p = GGMorse::getDefaultParametersDecode();
        p.frequency_hz = tone;
        p.speed_wpm = wpm;
        p.frequencyRangeMin_hz = 200;
        p.frequencyRangeMax_hz = 1200;
        engine.setParametersDecode(p);
    }
    static GGMorse::Parameters parameters() {
        auto p = GGMorse::getDefaultParameters();
        p.sampleRateInp = 12000;
        p.sampleFormatInp = GGMORSE_SAMPLE_FORMAT_I16;
        return p;
    }
};
extern "C" {
void * cw_create(float tone, float wpm) {
    if (!std::isfinite(tone) || !std::isfinite(wpm) || tone<200 || tone>1200 || (wpm!=0 && (wpm<5 || wpm>55))) return nullptr;
    try { return new Decoder(tone,wpm); } catch (...) { return nullptr; }
}
void cw_destroy(void *ptr) { delete static_cast<Decoder *>(ptr); }
int cw_feed(void *ptr, const void *pcm, int bytes, char *out, int capacity, float *stats) {
    if (!ptr || !pcm || bytes<0 || bytes>24000 || bytes%2 || capacity<1 || !out || !stats) return -1;
    try {
        auto &d = *static_cast<Decoder *>(ptr);
        const auto *p = static_cast<const unsigned char *>(pcm);
        d.pending.insert(d.pending.end(),p,p+bytes);
        size_t used=0;
        d.engine.decode([&](void *dst, uint32_t n) -> uint32_t {
            if (d.pending.size()-used<n) return 0;
            std::memcpy(dst,d.pending.data()+used,n); used+=n; return n;
        });
        d.pending.erase(d.pending.begin(),d.pending.begin()+used);
        if (d.pending.size()>24000) {d.pending.clear();return -1;}
        GGMorse::TxRx text;
        d.engine.takeRxData(text);
        const int n=std::min(int(text.size()),capacity-1);
        std::memcpy(out,text.data(),n);out[n]=0;
        const auto &s=d.engine.getStatistics();
        stats[0]=s.estimatedPitch_Hz; stats[1]=s.estimatedSpeed_wpm;
        stats[2]=s.costFunction; stats[3]=s.signalThreshold;
        return n;
    } catch (...) {return -1;}
}
}
