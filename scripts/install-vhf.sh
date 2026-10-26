#!/usr/bin/env bash
# Install receive-only engines and the Signal Observatory. No radio starts here.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
prefix=/opt/ituner-sdr/decoders/vhf
sources=/usr/local/src/ituner-vhf
install -d "$prefix/bin" "$prefix/licenses" "$sources"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  git cmake build-essential pkg-config libusb-1.0-0-dev librtlsdr-dev rtl-sdr \
  soapysdr-tools soapysdr-module-rtlsdr libsoapysdr-dev python3-soapysdr \
  python3-numpy python3-scipy python3-yaml python3-aprslib python3-ephem \
  rtl-433 direwolf gnuradio gr-satellites satdump libfftw3-dev \
  libcurl4-openssl-dev libzstd-dev libsqlite3-dev
fetch() {
    local name=$1 url=$2 revision=$3 target=$sources/$1
    if [[ ! -d $target/.git ]]; then git clone --depth 1 --no-checkout "$url" "$target"; fi
    if [[ $(git -C "$target" rev-parse HEAD) != "$revision" ]]; then git -C "$target" fetch --depth 1 origin "$revision"; fi
    git -C "$target" checkout --detach "$revision"
}
fetch AIS-catcher https://github.com/jvde-github/AIS-catcher.git 5404fd71dda8f39cc73e5fdf7b58e3f1ecb38a4c
cmake -S "$sources/AIS-catcher" -B "$sources/AIS-catcher/build" -DSOAPYSDR=ON -DWEBVIEWER=ON -DPSQL=OFF -DNMEA2000=OFF
cmake --build "$sources/AIS-catcher/build" -j2
install -m 0755 "$sources/AIS-catcher/build/AIS-catcher" "$prefix/bin/"
fetch RS https://github.com/rs1729/RS.git 89b1ea7f3371d99c630f6734c42014d88e667853
(
    cd "$sources/RS/demod/mod"
    gcc -O3 -c demod_mod.c
    gcc -O3 -c bch_ecc_mod.c
    gcc -O3 rs41mod.c demod_mod.o bch_ecc_mod.o -lm -o rs41mod
    gcc -O3 dfm09mod.c demod_mod.o -lm -o dfm09mod
    install -m 0755 rs41mod dfm09mod "$prefix/bin/"
)
for name in rtl_433 direwolf gr_satellites satdump; do ln -sfn "$(command -v "$name")" "$prefix/bin/$name"; done
install -m 0644 "$sources/AIS-catcher/LICENSE" "$prefix/licenses/AIS-catcher-GPL-3.0.txt"
cp -a "$sources/RS/LICENSE" "$prefix/licenses/RS1729-license.txt"
install -d /opt/ituner-sdr/UI
install -m 0644 "$repo"/UI/vhf_*.py "$repo"/UI/vhf_dashboard.{html,css,js} \
  "$repo"/UI/{sdr_broker,soapy_rx,kiwi_gl_display}.py \
  "$repo"/UI/adsb_*.py "$repo"/UI/adsb_*.js "$repo"/UI/adsb_*.css "$repo/UI/adsb_map.html" /opt/ituner-sdr/UI/
install -m 0644 "$repo"/UI/{spectrum_monitor,spectrum_history,spectrum_analysis,spectrum_report,spectrum_workspace,soapy_survey}.py "$repo"/UI/spectrum.{html,css,js} "$repo"/UI/spectrum_tools.js "$repo"/UI/spectrum_allocations.json /opt/ituner-sdr/UI/
dpkg-query -W soapysdr-tools soapysdr-module-rtlsdr rtl-433 direwolf gnuradio gr-satellites satdump > "$prefix/versions.txt"
printf '%s\n' 'AIS-catcher 5404fd71dda8f39cc73e5fdf7b58e3f1ecb38a4c' 'RS1729 89b1ea7f3371d99c630f6734c42014d88e667853' >> "$prefix/versions.txt"
install -m 0644 "$repo"/UI/{rtl_registry,rtl_eeprom_access,dongle_web,dongle_workspace}.py "$repo"/UI/dongles.{html,css,js} /opt/ituner-sdr/UI/
install -m 0644 "$repo"/UI/station*.py "$repo"/UI/station.{html,css,js} /opt/ituner-sdr/UI/
echo 'Installed. Restart ituner-sdr.service to load the decoder menu. Browser: http://cm5.local:8092/'
