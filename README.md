# London Tube Journey Planner

Unofficial trip planner for the London Underground: all 11 Tube lines plus the Elizabeth line.
It's the London counterpart of the Tokyo Subway and Namma Metro planners, in the same single-file format.

Enter where you're starting (GPS, an address, a postcode, a landmark or a station) and pick a
destination station. The planner:

- Tries the nearest few stations and picks the quickest once walking time is counted
- Gives the line, platform direction and destination for every train, as TfL signs them
  ("Westbound · towards Ealing Broadway"): Northbound/Southbound/Eastbound/Westbound, and Inner/Outer
  Rail on the western side of the Circle line and the Central line's Hainault loop
- Models each service pattern separately, so it never suggests a through train that doesn't run and
  says where to change instead (Kennington for the Northern line's Charing Cross branch, Earl's Court
  for Richmond, Baker Street for Watford trains, Hatton Cross for Heathrow Terminal 4…)
- Warns when trains on the same platform go somewhere else ("Not trains for Queen's Park or
  Stonebridge Park"), and when another line's trains on shared track go to the same stop
- Explains each change, including official out-of-station interchanges (Euston ⇄ Euston Square,
  the two Hammersmith and Edgware Road stations, White City ⇄ Wood Lane, Bayswater ⇄ Queensway) and
  connected stations (Bank ⇄ Monument, Paddington ⇄ Paddington H&C platforms)
- Shows total time, arrival time (London time), and the contactless/Oyster fare for the zones
  travelled, peak or off-peak as it applies right now, with the daily cap
- Knows the hours: the Waterloo & City runs Monday to Friday only, and on Friday and Saturday nights
  it plans on the Night Tube lines only

## What's covered

- **London Underground**: Bakerloo, Central, Circle, District, Hammersmith & City, Jubilee,
  Metropolitan, Northern, Piccadilly, Victoria, Waterloo & City.
- **Elizabeth line** inside London's fare zones: Heathrow and West Drayton to Abbey Wood and Harold
  Wood. Trains continue to Reading, Maidenhead and Shenfield; those stations have their own fares and
  aren't included, but platform advice still names them as destinations.
- Not covered: DLR, London Overground, trams, National Rail, and the District line's
  Kensington (Olympia) shuttle (mostly weekends).

## Run

It's a static page. Serve the folder and open `LondonTubePlanner.html`:

```bash
python3 -m http.server 4620
```

GPS only works on `localhost` or HTTPS.

## Address search

Without a key, place search uses OpenStreetMap (Nominatim). For Google Places results,
copy `config.example.js` to `config.js` and add a Maps Platform key with Places API (New)
and Maps JavaScript API enabled. `config.js` is gitignored.

## Deployment

`netlify.toml` publishes the planner as `index.html` and writes `config.js` from the
`GOOGLE_MAPS_API_KEY` environment variable when it's set; without it the site uses
OpenStreetMap search. Not deployed yet.

## Station data

The data block in the HTML (between `BEGIN GENERATED` and `END GENERATED`) is written by
`tools/build_stations.py`:

```bash
python3 tools/build_stations.py
```

It downloads the London Underground and Elizabeth line route relations from OpenStreetMap
(Overpass API, with mirror fallbacks) for each line's own platform positions, so changing lines at
big stations costs a realistic walk. The rest is defined in the script and was checked against
TfL's open data (October 2026):

- **Service patterns**: one per through service (e.g. Northern line Morden–Edgware via Bank). Only
  trains that run all day are used for routing; short workings and peak-only through trains are
  kept for platform advice. Checked against TfL timetables for weekdays, Saturdays and Sundays.
- **Platform directions**: per section of line, as in TfL's live arrivals feed.
- **Fare zones** from TfL's station data, including boundary stations.
- **Interchanges** between differently named stations.

Distances are straight lines scaled to each line's official length. Journey times come from a model
fitted to about 740 timetabled stop-to-stop times from TfL (1.1 min per stop + 1 min per km, with a
per-line pace factor), plus average waits.

Use `--save file.json` to keep the download and `--osm file.json` to rebuild from it.

## Fares

Fares and caps are in `METRO.fares` at the top of the script: adult pay as you go fares from
1 March 2026 (Zone 1 £3.10 peak / £3.00 off-peak … Zones 1–6 £5.90 / £4.00), the fares for
journeys avoiding Zone 1, Zones 7–9, and the daily caps (frozen for 2026: Zones 1–2 £8.90 …
Zones 1–6 £16.30). They were checked against TfL's 2026 caps sheet and its fare finder. Peak is
Monday to Friday 06:30–09:30 and 16:00–19:00, except travel into Zone 1 in the evening peak.

Special cases handled:

- Tube journeys to or from Heathrow through Zone 1 are charged the peak fare at all times (£5.90).
- Elizabeth line fares to Heathrow are set separately: £15.50 from central London, £14.60 from
  Paddington, otherwise the zonal fare plus £6.50. Travel between the terminals and Hatton Cross is free.

Known limitations:

- TfL charges the Zone 1 fare for some short Zone 1 ⇄ Zone 2 trips (e.g. Euston → Camden Town,
  King's Cross → Caledonian Road). That depends on both stations, so the planner shows the standard
  Zones 1–2 fare, up to 50p more.
- Zones 8–8 and 9–9 single fares aren't published; they're estimated as the Zone 7 fare.
- Public holidays are treated as normal weekdays for peak fares.
- Fares, times and service patterns are estimates. Always follow in-station signs and check TfL for
  engineering works.
