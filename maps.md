# Map catalogue

All maps: departure **2026-10-12 09:00** (Monday), 4000 px wide (`--width-px 4000`), heatmap opacity and basemap at the program defaults
(opacity 0.275, drawn OSM basemap with own labels). Output goes to `out/`.

## Locations
| Id | Address | Latitude | Longitude | Note |
|----|---------|----------|----------|------|
| M | 2030 Érd, Morva utca 13. | 47.3846697 | 18.9459664 | OSM only knows the street, not house 13; coordinates are a point on Morva utca |
| B | 1115 Budapest, Bartók Béla út 129/B | 47.4710194 | 19.0280001 | |
| H | 1035 Budapest, Hunor utca 19 | 47.5462201 | 19.0357493 | |

## Levels
| Level | Bounding box (min lat, min lon, max lat, max lon) | Cell size | Max travel time | Contours |
|-------|--------------------------------------------------|-----------|-----------------|----------|
| Budapest | 47.34 18.93 47.62 19.34 (city limits) | 100 m | 120 min | 15 min |
| Budapest + Pomáz | 47.34 18.93 47.67 19.34 (city limits plus Pomáz in the north) | 200 m | 180 min | 15 min |
| Agglomeration | 47.33 18.81 47.62 19.34 (Budapest, Érd, Diósd, Tárnok) | 200 m | 180 min | 15 min |
| Hungary | 45.74 16.11 48.59 22.90 | 250 m | 480 min | 60 min |

## Maps
Mode `T` = public transport only, `T+C` = public transport and car.
Which level each origin gets: Morva utca → Agglomeration; Hunor utca → Budapest + Pomáz; Bartók Béla út → Agglomeration and Hungary.

| No. | File (out/) | Origin | Level | Mode | Cell | Max time | Contours |
|-----|-------------|--------|-------|------|------|----------|----------|
| 1 | morva-agglo-T.png | M | Agglomeration | T | 200 m | 180 | 15 |
| 2 | morva-agglo-TC.png | M | Agglomeration | T+C | 200 m | 180 | 15 |
| 3 | bartok-agglo-T.png | B | Agglomeration | T | 200 m | 180 | 15 |
| 4 | bartok-agglo-TC.png | B | Agglomeration | T+C | 200 m | 180 | 15 |
| 5 | bartok-hungary-T.png | B | Hungary | T | 250 m | 480 | 60 |
| 6 | bartok-hungary-TC.png | B | Hungary | T+C | 250 m | 480 | 60 |
| 7 | hunor-budapest-pomaz-T.png | H | Budapest + Pomáz | T | 200 m | 180 | 15 |
| 8 | hunor-budapest-pomaz-TC.png | H | Budapest + Pomáz | T+C | 200 m | 180 | 15 |

## Command template
```
python budapest_transit_heatmap/main.py --start-lat <lat> --start-lon <lon> --datetime 2026-10-12T09:00:00 \
  --bbox <min lat> <min lon> <max lat> <max lon> --resolution <cell> --max-cutoff <max time> \
  --contour-interval <contours> --width-px 4000 [--car] --output out/<file>
```
Example, map 6 (Bartók Béla út, Hungary, public transport + car):
```
python budapest_transit_heatmap/main.py --start-lat 47.4710194 --start-lon 19.0280001 --datetime 2026-10-12T09:00:00 \
  --bbox 45.74 16.11 48.59 22.90 --resolution 250 --max-cutoff 480 --contour-interval 60 --width-px 4000 --car \
  --output out/bartok-hungary-TC.png
```
