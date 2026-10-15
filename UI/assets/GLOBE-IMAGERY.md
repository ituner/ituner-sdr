# Globe imagery

The bundled `nasa-blue-marble-2048.jpg` and `nasa-blue-marble-4096.jpg`
backgrounds use NASA GIBS **BlueMarble_NextGeneration**, the same imagery
product as the regional HD tiles in `globe_tiles.py`:

https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/BlueMarble_NextGeneration/default/500m/{level}/{row}/{col}.jpeg

The backgrounds are assembled from the complete level 3 world (10 × 5 tiles,
5120 × 2560 pixels) and reduced to their runtime sizes. No color adjustment
is applied. This keeps ocean colors consistent when detailed tiles give way
to the background while panning, before tiles are available, or offline.
Natural differences in fine detail between image resolutions remain.

To rebuild with Python and Pillow installed:

```sh
python3 scripts/build-globe-background.py --cache-dir /tmp/ituner-globe-assets
```

Source: NASA Earth Observatory / NASA GIBS, Blue Marble Next Generation.
The existing GPU lighting, touch throttling, and deferred tile uploads do not
change; the generated files replace the previously different base imagery.
