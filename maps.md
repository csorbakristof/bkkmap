# Map catalogue

All maps: departure **2026-10-12 09:00** (Monday), 4000 px wide (`--width-px 4000`), heatmap opacity and basemap at the program defaults
(opacity 0.275, drawn OSM basemap with own labels). Output goes to `out/`.

## Place labels
Labels follow the map scale (`config.py`: `LABEL_MAX_MPP`, `PLAIN_SUBURB_MAX_MPP`):
- **Budapest, Budapest + Pomáz and Agglomeration maps (≈8–10 m per pixel):** capital, cities, towns, villages and — new — neighbourhood
  names (OSM `place=suburb`, e.g. Óbuda, Kelenföld, Újlipótváros, Csepel-Belváros): the well-known ones (with a Wikipedia/Wikidata link
  in OSM) and, with extra spacing, the lesser known ones. About 150–250 labels per map, never overlapping each other, the flag or the info box.
- **Hungary map (≈130 m per pixel):** capital, cities and towns above ~10 000 inhabitants only; neighbourhoods and villages are not shown.

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
| Budapest + Pomáz | 47.34 18.93 47.72 19.34 (city limits plus Pomáz; extra room in the north keeps it clear of the info box) | 200 m | 180 min | 15 min |
| Agglomeration | 47.33 18.81 47.62 19.34 (Budapest, Érd, Diósd, Tárnok) | 200 m | 180 min | 15 min |
| Hungary | 45.74 16.11 48.59 22.90 | 250 m | 480 min | 60 min |

## Maps
Maps 1–4 and 7–8 were regenerated with the neighbourhood labels; maps 5–6 are unchanged by them.
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
