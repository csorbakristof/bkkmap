# Map catalogue

Departure **2026-11-23 09:00** (Monday) for maps 1–6 and 9–10; maps 7–8 (Hunor) are still the older **2026-10-12 09:00** versions
(15 min contours, English legends). The current BKK feed only covers 2026-11-16 to 2027-01-01, so an October date no longer works
(the program stops with an error if a required feed has no service on the date). All maps: 4000 px wide (`--width-px 4000`), heatmap opacity and basemap at the program defaults
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
| Agglomeration | 47.33 18.81 47.62 19.34 (Budapest, Érd, Diósd, Tárnok) | 200 m (50 m for maps 9–10) | 180 min | 10 min (5 min for maps 9–10) |
| Hungary | 45.74 16.11 48.59 22.90 | 250 m | 480 min | 60 min |

## Maps
Maps 1–4 and 7–8 were regenerated with the neighbourhood labels; maps 5–6 are unchanged by them.
Mode `T` = public transport only, `T+C` = public transport and car.
Which level each origin gets: Morva utca → Agglomeration; Hunor utca → Budapest + Pomáz; Bartók Béla út → Agglomeration (also at 50 m) and Hungary.

| No. | File (out/) | Origin | Level | Mode | Cell | Max time | Contours |
|-----|-------------|--------|-------|------|------|----------|----------|
| 1 | morva-agglo-T.png | M | Agglomeration | T | 200 m | 180 | 10 |
| 2 | morva-agglo-TC.png | M | Agglomeration | T+C | 200 m | 180 | 10 |
| 3 | bartok-agglo-T.png | B | Agglomeration | T | 200 m | 180 | 10 |
| 4 | bartok-agglo-TC.png | B | Agglomeration | T+C | 200 m | 180 | 10 |
| 5 | bartok-hungary-T.png | B | Hungary | T | 250 m | 480 | 60 |
| 6 | bartok-hungary-TC.png | B | Hungary | T+C | 250 m | 480 | 60 |
| 7 | hunor-budapest-pomaz-T.png | H | Budapest + Pomáz | T | 200 m | 180 | 15 |
| 8 | hunor-budapest-pomaz-TC.png | H | Budapest + Pomáz | T+C | 200 m | 180 | 15 |
| 9 | bartok-agglo-50m-T.png | B | Agglomeration | T | 50 m | 180 | 5 |
| 10 | bartok-agglo-50m-TC.png | B | Agglomeration | T+C | 50 m | 180 | 5 |
| 11 | bartok-hungary-T-60x40.png | B | Hungary (60×40 cm print) | T | 250 m | 480 | 60 |

Map 11 is a print version: 4724 × 3150 px (60 × 40 cm at 200 DPI), bbox `45.4333 16.11 48.8791 22.90` (Hungary centred, latitude padded to a 3:2 sheet), `--width-px 4218`.

On country-scale maps (≥ 50 m per pixel, `--foreign`, on by default) the area outside Hungary is filled from Natural Earth (cached in `gtfs_cache/naturalearth/`): rivers, lakes, neighbouring borders and cities above 50 000 inhabitants with Hungarian names. Map 11 was made with it; maps 5–6 were not regenerated.

Country-scale maps also get terrain relief (`--hillshade`, on by default; AWS Terrain Tiles cached in `gtfs_cache/terrain/`), light from the north-west, 4× vertical exaggeration. Map 11 has it.

Maps 9–10 use `--max-walk-time 5` (default 30). The map legends (info box, colour bar, attribution) are in Hungarian.

Command for map 11 (about 1.5 min; `--width-px` = image width / 1.12, because the colour bar adds 12 % to the width):
```
python budapest_transit_heatmap/main.py --start-lat 47.4710194 --start-lon 19.0280001 --datetime 2026-11-23T09:00:00   --bbox 45.4333 16.11 48.8791 22.90 --resolution 250 --max-cutoff 480 --contour-interval 60 --width-px 4218   --output out/bartok-hungary-T-60x40.png
```

## Command template
```
python budapest_transit_heatmap/main.py --start-lat <lat> --start-lon <lon> --datetime 2026-11-23T09:00:00 \
  --bbox <min lat> <min lon> <max lat> <max lon> --resolution <cell> --max-cutoff <max time> \
  --contour-interval <contours> --width-px 4000 [--max-walk-time 5] [--car] --output out/<file>
```
Example, map 6 (Bartók Béla út, Hungary, public transport + car):
```
python budapest_transit_heatmap/main.py --start-lat 47.4710194 --start-lon 19.0280001 --datetime 2026-11-23T09:00:00 \
  --bbox 45.74 16.11 48.59 22.90 --resolution 250 --max-cutoff 480 --contour-interval 60 --width-px 4000 --car \
  --output out/bartok-hungary-TC.png
```
