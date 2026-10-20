#!/usr/bin/env python3
"""Build the station dataset embedded in LondonTubePlanner.html.

Downloads the London Underground and Elizabeth line route relations from OpenStreetMap
(Overpass API) for each line's platform positions, then combines them with the service
patterns, fare zones and interchanges defined below. Those were checked against TfL's
timetables, route sequences and station data in October 2026.

    python3 tools/build_stations.py                    # download, rewrite the data block in place
    python3 tools/build_stations.py --osm saved.json   # reuse a saved Overpass download
    python3 tools/build_stations.py --save saved.json  # keep a copy of the download
"""
import json, math, os, re, subprocess, sys, time, urllib.parse, urllib.request

QUERY = """[out:json][timeout:240];
(
  relation["route"="subway"]["network"="London Underground"](51.25,-0.75,51.80,0.35);
  relation["route"="train"]["name"~"^Elizabeth line"](51.25,-1.1,51.80,0.4);
)->.r;
.r out body; node(r.r); out body;
node["railway"="station"]["station"="subway"](51.25,-0.75,51.80,0.35); out body;"""
ENDPOINTS = ['https://overpass-api.de/api/interpreter', 'https://overpass.private.coffee/api/interpreter',
             'https://overpass.kumi.systems/api/interpreter']

# id, name, TfL web colour, badge text colour, official route km (None: don't calibrate),
# the OSM relation name prefix, and TfL's direction name for the forward order of its routes.
LINES = [
  ('B', 'Bakerloo', '#B36305', '#fff', 23.2, 'Bakerloo line', 'N'),
  ('C', 'Central', '#E32017', '#fff', 74.0, 'Central line', 'E'),
  ('Ci', 'Circle', '#FFD300', '#17140F', 27.2, 'Circle line', None),
  ('D', 'District', '#00782A', '#fff', 64.0, 'District line', 'W'),
  ('H', 'Hammersmith & City', '#F3A9BB', '#17140F', 25.5, 'Hammersmith & City line', 'E'),
  ('J', 'Jubilee', '#A0A5A9', '#17140F', 36.2, 'Jubilee line', 'S'),
  ('M', 'Metropolitan', '#9B0056', '#fff', 67.0, 'Metropolitan line', 'N'),
  ('N', 'Northern', '#000000', '#fff', 61.2, 'Northern line', 'N'),
  ('P', 'Piccadilly', '#003688', '#fff', 71.0, 'Piccadilly line', 'W'),
  ('V', 'Victoria', '#0098D4', '#fff', 21.0, 'Victoria line', 'N'),
  ('W', 'Waterloo & City', '#95CDBA', '#17140F', 2.37, 'Waterloo & City line', 'E'),
  ('E', 'Elizabeth', '#6950A1', '#fff', None, 'Elizabeth line', 'E'),
]

# ── Branches, in station order ─────────────────────────────────────────────
BAKERLOO = ['Elephant & Castle', 'Lambeth North', 'Waterloo', 'Embankment', 'Charing Cross', 'Piccadilly Circus',
  'Oxford Circus', "Regent's Park", 'Baker Street', 'Marylebone', 'Edgware Road (Bakerloo)', 'Paddington',
  'Warwick Avenue', 'Maida Vale', 'Kilburn Park', "Queen's Park", 'Kensal Green', 'Willesden Junction', 'Harlesden',
  'Stonebridge Park', 'Wembley Central', 'North Wembley', 'South Kenton', 'Kenton', 'Harrow & Wealdstone']

C_WR = ['West Ruislip', 'Ruislip Gardens', 'South Ruislip', 'Northolt', 'Greenford', 'Perivale', 'Hanger Lane', 'North Acton']
C_EB = ['Ealing Broadway', 'West Acton', 'North Acton']
C_TRUNK = ['North Acton', 'East Acton', 'White City', "Shepherd's Bush", 'Holland Park', 'Notting Hill Gate', 'Queensway',
  'Lancaster Gate', 'Marble Arch', 'Bond Street', 'Oxford Circus', 'Tottenham Court Road', 'Holborn', 'Chancery Lane',
  "St. Paul's", 'Bank', 'Liverpool Street', 'Bethnal Green', 'Mile End', 'Stratford', 'Leyton', 'Leytonstone']
C_EPP = ['Leytonstone', 'Snaresbrook', 'South Woodford', 'Woodford', 'Buckhurst Hill', 'Loughton', 'Debden', 'Theydon Bois', 'Epping']
C_HNP = ['Leytonstone', 'Wanstead', 'Redbridge', 'Gants Hill', 'Newbury Park', 'Barkingside', 'Fairlop', 'Hainault']
C_SHUTTLE = ['Woodford', 'Roding Valley', 'Chigwell', 'Grange Hill', 'Hainault']

CIRCLE = ['Hammersmith (H&C line)', 'Goldhawk Road', "Shepherd's Bush Market", 'Wood Lane', 'Latimer Road', 'Ladbroke Grove',
  'Westbourne Park', 'Royal Oak', 'Paddington (H&C line)', 'Edgware Road (Circle line)', 'Baker Street', 'Great Portland Street',
  'Euston Square', "King's Cross St. Pancras", 'Farringdon', 'Barbican', 'Moorgate', 'Liverpool Street', 'Aldgate', 'Tower Hill',
  'Monument', 'Cannon Street', 'Mansion House', 'Blackfriars', 'Temple', 'Embankment', 'Westminster', "St. James's Park",
  'Victoria', 'Sloane Square', 'South Kensington', 'Gloucester Road', 'High Street Kensington', 'Notting Hill Gate', 'Bayswater',
  'Paddington', 'Edgware Road (Circle line)']

D_UPM = ['Upminster', 'Upminster Bridge', 'Hornchurch', 'Elm Park', 'Dagenham East', 'Dagenham Heathway', 'Becontree', 'Upney',
  'Barking', 'East Ham', 'Upton Park', 'Plaistow', 'West Ham', 'Bromley-by-Bow', 'Bow Road', 'Mile End', 'Stepney Green',
  'Whitechapel', 'Aldgate East', 'Tower Hill', 'Monument', 'Cannon Street', 'Mansion House', 'Blackfriars', 'Temple', 'Embankment',
  'Westminster', "St. James's Park", 'Victoria', 'Sloane Square', 'South Kensington', 'Gloucester Road', "Earl's Court"]
D_WEST = ["Earl's Court", 'West Kensington', 'Barons Court', 'Hammersmith (District & Piccadilly)', 'Ravenscourt Park',
  'Stamford Brook', 'Turnham Green']
D_RICH = ['Turnham Green', 'Gunnersbury', 'Kew Gardens', 'Richmond']
D_EAL = ['Turnham Green', 'Chiswick Park', 'Acton Town', 'Ealing Common', 'Ealing Broadway']
D_WIM = ["Earl's Court", 'West Brompton', 'Fulham Broadway', 'Parsons Green', 'Putney Bridge', 'East Putney', 'Southfields',
  'Wimbledon Park', 'Wimbledon']
D_EDG = ['Edgware Road (Circle line)', 'Paddington', 'Bayswater', 'Notting Hill Gate', 'High Street Kensington', "Earl's Court"]

HC = CIRCLE[:14] + ['Farringdon', 'Barbican', 'Moorgate', 'Liverpool Street', 'Aldgate East', 'Whitechapel', 'Stepney Green',
  'Mile End', 'Bow Road', 'Bromley-by-Bow', 'West Ham', 'Plaistow', 'Upton Park', 'East Ham', 'Barking']

JUBILEE = ['Stanmore', 'Canons Park', 'Queensbury', 'Kingsbury', 'Wembley Park', 'Neasden', 'Dollis Hill', 'Willesden Green',
  'Kilburn', 'West Hampstead', 'Finchley Road', 'Swiss Cottage', "St. John's Wood", 'Baker Street', 'Bond Street', 'Green Park',
  'Westminster', 'Waterloo', 'Southwark', 'London Bridge', 'Bermondsey', 'Canada Water', 'Canary Wharf', 'North Greenwich',
  'Canning Town', 'West Ham', 'Stratford']

# Metropolitan trains run non-stop between Finchley Road and Wembley Park.
M_CITY = ['Aldgate', 'Liverpool Street', 'Moorgate', 'Barbican', 'Farringdon', "King's Cross St. Pancras", 'Euston Square',
  'Great Portland Street', 'Baker Street', 'Finchley Road', 'Wembley Park', 'Preston Road', 'Northwick Park', 'Harrow-on-the-Hill']
M_UXB = ['Harrow-on-the-Hill', 'West Harrow', 'Rayners Lane', 'Eastcote', 'Ruislip Manor', 'Ruislip', 'Ickenham', 'Hillingdon', 'Uxbridge']
M_MAIN = ['Harrow-on-the-Hill', 'North Harrow', 'Pinner', 'Northwood Hills', 'Northwood', 'Moor Park']
M_WAT = ['Moor Park', 'Croxley', 'Watford']
M_AMS = ['Moor Park', 'Rickmansworth', 'Chorleywood', 'Chalfont & Latimer', 'Amersham']

N_MOR = ['Morden', 'South Wimbledon', 'Colliers Wood', 'Tooting Broadway', 'Tooting Bec', 'Balham', 'Clapham South',
  'Clapham Common', 'Clapham North', 'Stockwell', 'Oval', 'Kennington']
N_BANK = ['Kennington', 'Elephant & Castle', 'Borough', 'London Bridge', 'Bank', 'Moorgate', 'Old Street', 'Angel',
  "King's Cross St. Pancras", 'Euston', 'Camden Town']
N_CX = ['Kennington', 'Waterloo', 'Embankment', 'Charing Cross', 'Leicester Square', 'Tottenham Court Road', 'Goodge Street',
  'Warren Street', 'Euston', 'Mornington Crescent', 'Camden Town']
N_BPS = ['Battersea Power Station', 'Nine Elms', 'Kennington']
N_EDG = ['Camden Town', 'Chalk Farm', 'Belsize Park', 'Hampstead', 'Golders Green', 'Brent Cross', 'Hendon Central',
  'Colindale', 'Burnt Oak', 'Edgware']
N_HB = ['Camden Town', 'Kentish Town', 'Tufnell Park', 'Archway', 'Highgate', 'East Finchley', 'Finchley Central',
  'West Finchley', 'Woodside Park', 'Totteridge & Whetstone', 'High Barnet']
N_MHE = N_HB[:7] + ['Mill Hill East']

# Piccadilly trains run non-stop between Hammersmith and Acton Town (Turnham Green only very early and late).
P_EAST = ['Cockfosters', 'Oakwood', 'Southgate', 'Arnos Grove', 'Bounds Green', 'Wood Green', 'Turnpike Lane', 'Manor House',
  'Finsbury Park', 'Arsenal', 'Holloway Road', 'Caledonian Road', "King's Cross St. Pancras", 'Russell Square', 'Holborn',
  'Covent Garden', 'Leicester Square', 'Piccadilly Circus', 'Green Park', 'Hyde Park Corner', 'Knightsbridge',
  'South Kensington', 'Gloucester Road', "Earl's Court", 'Barons Court', 'Hammersmith (District & Piccadilly)', 'Acton Town']
P_HEATH = ['Acton Town', 'South Ealing', 'Northfields', 'Boston Manor', 'Osterley', 'Hounslow East', 'Hounslow Central',
  'Hounslow West', 'Hatton Cross']
P_UXB = ['Acton Town', 'Ealing Common', 'North Ealing', 'Park Royal', 'Alperton', 'Sudbury Town', 'Sudbury Hill',
  'South Harrow', 'Rayners Lane', 'Eastcote', 'Ruislip Manor', 'Ruislip', 'Ickenham', 'Hillingdon', 'Uxbridge']

VICTORIA = ['Brixton', 'Stockwell', 'Vauxhall', 'Pimlico', 'Victoria', 'Green Park', 'Oxford Circus', 'Warren Street', 'Euston',
  "King's Cross St. Pancras", 'Highbury & Islington', 'Finsbury Park', 'Seven Sisters', 'Tottenham Hale', 'Blackhorse Road',
  'Walthamstow Central']

# Elizabeth line inside London's fare zones: West Drayton and Heathrow to Abbey Wood and Harold Wood.
# Beyond those (Iver–Reading, Brentwood, Shenfield) fares aren't zonal, so they're left out.
E_HX = ['Hayes & Harlington', 'Southall', 'Hanwell', 'West Ealing', 'Ealing Broadway', 'Acton Main Line', 'Paddington']
E_CORE = ['Paddington', 'Bond Street', 'Tottenham Court Road', 'Farringdon', 'Liverpool Street', 'Whitechapel']
E_SE = ['Whitechapel', 'Canary Wharf', 'Custom House', 'Woolwich', 'Abbey Wood']
E_NE = ['Whitechapel', 'Stratford', 'Maryland', 'Forest Gate', 'Manor Park', 'Ilford', 'Seven Kings', 'Goodmayes',
  'Chadwell Heath', 'Romford', 'Gidea Park', 'Harold Wood']

def cat(*parts):
  out = list(parts[0])
  for p in parts[1:]:
    assert out[-1] == p[0], (out[-1], p[0])
    out += p[1:]
  return out
rev = lambda s: list(reversed(s))

# ── Service patterns used for routing ──────────────────────────────────────
# Only through trains that run all day are routes, so the planner never relies on a
# peak-only or occasional working; those appear in SERVICES below for platform advice.
# Checked against TfL timetables (weekday, Saturday and Sunday departures), Oct 2026.
# Each route's stations run in its forward direction; `to` overrides terminus names for
# trains that continue beyond the stations covered here; `night` routes run on the Night
# Tube (Friday and Saturday nights); `wait` is the average wait in minutes where trains are
# infrequent; `oneway` routes only run forwards (the Heathrow Terminal 4 loop).
ROUTES = [
  dict(id='B1', line='B', seq=BAKERLOO),
  dict(id='C1', line='C', seq=cat(C_WR, C_TRUNK, C_EPP)),
  dict(id='C2', line='C', seq=cat(C_WR, C_TRUNK, C_HNP)),
  dict(id='C3', line='C', seq=cat(C_EB, C_TRUNK, C_EPP)),
  dict(id='C4', line='C', seq=cat(C_EB, C_TRUNK, C_HNP), night=1),
  dict(id='C5', line='C', seq=C_SHUTTLE, wait=8),                    # Woodford–Hainault via Grange Hill, ~3 an hour
  dict(id='C6', line='C', seq=cat(C_EB, C_TRUNK, C_EPP[:6]), night=2),  # Night Tube: Ealing Broadway–Loughton
  # Circle: Hammersmith → Edgware Road → round the loop → Edgware Road (and back), every ~10 min.
  dict(id='Ci1', line='Ci', seq=CIRCLE, wait=4),
  dict(id='D1', line='D', seq=cat(D_UPM, D_WEST, D_RICH)),
  dict(id='D2', line='D', seq=cat(D_UPM, D_WEST, D_EAL)),
  dict(id='D3', line='D', seq=cat(D_UPM, D_WIM)),
  dict(id='D4', line='D', seq=cat(D_EDG, D_WIM), wait=4),             # Edgware Road branch trains only go to Wimbledon
  dict(id='H1', line='H', seq=HC, wait=4),
  dict(id='J1', line='J', seq=JUBILEE, night=1),
  dict(id='M1', line='M', seq=cat(M_CITY, M_UXB)),
  dict(id='M2', line='M', seq=cat(M_CITY, M_MAIN, M_AMS), wait=8),
  dict(id='M3', line='M', seq=cat(M_CITY, M_MAIN, M_AMS[:4], ['Chalfont & Latimer', 'Chesham']), wait=12),
  dict(id='M4', line='M', seq=cat(M_CITY[8:], M_MAIN, M_WAT), wait=5),  # Watford trains mostly end at Baker Street
  dict(id='N1', line='N', seq=cat(N_MOR, N_BANK, N_EDG), via='Bank'),
  dict(id='N2', line='N', seq=cat(N_MOR, N_BANK, N_HB), via='Bank'),
  dict(id='N3', line='N', seq=cat(N_MOR, N_BANK, N_MHE), via='Bank', wait=7),
  dict(id='N4', line='N', seq=cat(N_CX, N_EDG), via='Charing Cross'),   # Edgware CX trains mostly turn at Kennington
  dict(id='N5', line='N', seq=cat(N_BPS, N_CX, N_HB), via='Charing Cross'),
  dict(id='N6', line='N', seq=cat(N_BPS, N_CX, N_MHE), via='Charing Cross', wait=7),
  dict(id='N7', line='N', seq=cat(N_MOR, N_CX, N_EDG), via='Charing Cross', night=2),  # Night Tube
  dict(id='N8', line='N', seq=cat(N_MOR, N_CX, N_HB), via='Charing Cross', night=2),
  dict(id='P1', line='P', seq=cat(P_EAST, P_HEATH, ['Hatton Cross', 'Heathrow Terminals 2 & 3', 'Heathrow Terminal 5']), night=1),
  dict(id='P2', line='P', seq=cat(P_EAST, P_HEATH, ['Hatton Cross', 'Heathrow Terminal 4']), oneway=1, wait=5),
  dict(id='P3', line='P', seq=cat(['Heathrow Terminal 4', 'Heathrow Terminals 2 & 3', 'Hatton Cross'], rev(P_HEATH), rev(P_EAST)), oneway=1, wait=5, dir='E'),
  dict(id='P4', line='P', seq=cat(P_EAST, P_UXB), wait=6),
  dict(id='V1', line='V', seq=VICTORIA, night=1),
  dict(id='W1', line='W', seq=['Waterloo', 'Bank'], weekdays=1),
  dict(id='E1', line='E', seq=['Heathrow Terminal 4', 'Heathrow Terminals 2 & 3'] + cat(E_HX, E_CORE, E_SE), wait=6),
  dict(id='E2', line='E', seq=['Heathrow Terminal 5', 'Heathrow Terminals 2 & 3'] + cat(E_HX, E_CORE, E_NE), wait=12, to=['Heathrow Terminal 5', 'Shenfield']),
  dict(id='E3', line='E', seq=['West Drayton'] + cat(E_HX, E_CORE, E_SE), wait=8, to=['Reading/Maidenhead', 'Abbey Wood']),
  dict(id='E4', line='E', seq=cat(E_CORE, E_NE), wait=4, to=['Paddington', 'Shenfield']),
]

# Other regular trains, for platform advice only (routes count too, night-only ones included,
# as they also run at some times of day): short workings such as Bakerloo trains to Queen's
# Park, as (route, first stop, last stop) along that route.
SERVICES = [
  ('B1', 'Elephant & Castle', "Queen's Park"), ('B1', 'Elephant & Castle', 'Stonebridge Park'),
  ('C1', 'West Ruislip', 'Loughton'), ('C2', 'West Ruislip', 'Newbury Park'),
  ('C4', 'Ealing Broadway', 'Newbury Park'), ('C1', 'Epping', 'White City'), ('C2', 'Hainault', 'White City'),
  ('C1', 'Epping', 'North Acton'), ('C2', 'Hainault', 'North Acton'), ('C1', 'Epping', 'Northolt'),
  ('D1', 'Richmond', 'Tower Hill'), ('D2', 'Ealing Broadway', 'Tower Hill'), ('D3', 'Wimbledon', 'Tower Hill'),
  ('D1', 'Richmond', 'Barking'), ('D2', 'Ealing Broadway', 'Barking'), ('D3', 'Wimbledon', 'Barking'),
  ('D2', 'Ealing Broadway', 'Dagenham East'), ('D3', 'Wimbledon', 'Dagenham East'),
  ('J1', 'Stratford', 'Wembley Park'), ('J1', 'Stratford', 'Willesden Green'), ('J1', 'Stratford', 'West Hampstead'),
  ('J1', 'Stanmore', 'North Greenwich'), ('J1', 'Stanmore', 'West Ham'),
  ('M1', 'Uxbridge', 'Baker Street'), ('M2', 'Amersham', 'Baker Street'), ('M3', 'Chesham', 'Baker Street'),
  ('M1', 'Aldgate', 'Harrow-on-the-Hill'), ('M1', 'Uxbridge', 'Harrow-on-the-Hill'),
  ('N1', 'Morden', 'Golders Green'), ('N8', 'Kennington', 'High Barnet'),
  ('P4', 'Cockfosters', 'Rayners Lane'), ('P1', 'Cockfosters', 'Northfields'), ('P1', 'Heathrow Terminal 5', 'Arnos Grove'),
  ('P4', 'Uxbridge', 'Arnos Grove'), ('P1', 'Heathrow Terminal 5', 'Oakwood'),
  ('V1', 'Brixton', 'Seven Sisters'),
  ('E1', 'Abbey Wood', 'Paddington'), ('E2', 'Harold Wood', 'Paddington'),
]
# Through trains outside the all-day pattern, both directions: (line, stations, via).
EXTRA = [
  ('M', cat(M_CITY, M_MAIN, M_WAT), None),            # Watford–Aldgate, weekday peaks
  ('N', cat(N_BPS, N_CX, N_EDG), 'Charing Cross'),     # Battersea–Edgware, mostly weekdays
  ('N', cat(N_MOR, N_CX, N_MHE), 'Charing Cross'),     # Morden–Mill Hill East via Charing Cross, peaks
]

# Different-name stations joined by an official interchange: 'in' = connected inside the
# station, 'osi' = out-of-station interchange (touch out, walk, touch in; still one journey).
# An optional line limits the link to that line's platforms at the first station.
LINKS = [
  ('Bank', 'Monument', 'in'),
  ('Paddington', 'Paddington (H&C line)', 'in'),
  ('Liverpool Street', 'Moorgate', 'in', 'E'),   # Elizabeth line platforms run between the two
  ('Euston', 'Euston Square', 'osi'),
  ('Hammersmith (District & Piccadilly)', 'Hammersmith (H&C line)', 'osi'),
  ('Edgware Road (Bakerloo)', 'Edgware Road (Circle line)', 'osi'),
  ('White City', 'Wood Lane', 'osi'),
  ('Bayswater', 'Queensway', 'osi'),
]

# Labelled on the network map even when zoomed out: hubs far enough apart not to collide
# at the whole-network zoom (the rest appear as you zoom in).
MAJOR = {"King's Cross St. Pancras", 'Waterloo', "Earl's Court", 'Stratford', 'Canary Wharf', 'Heathrow Terminals 2 & 3',
  'Wimbledon', 'Harrow-on-the-Hill', 'Ealing Broadway'}

# Fare zones from TfL's station data (Oct 2026); 'a+b' is a boundary station, charged as
# whichever zone is cheaper.
ZONES = {
  'Abbey Wood':4, 'Acton Main Line':3, 'Acton Town':3, 'Aldgate':1, 'Aldgate East':1, 'Alperton':4, 'Amersham':9,
  'Angel':1, 'Archway':'2+3', 'Arnos Grove':4, 'Arsenal':2, 'Baker Street':1, 'Balham':3, 'Bank':1, 'Barbican':1,
  'Barking':4, 'Barkingside':4, 'Barons Court':2, 'Battersea Power Station':1, 'Bayswater':1, 'Becontree':5,
  'Belsize Park':2, 'Bermondsey':2, 'Bethnal Green':2, 'Blackfriars':1, 'Blackhorse Road':3, 'Bond Street':1,
  'Borough':1, 'Boston Manor':4, 'Bounds Green':'3+4', 'Bow Road':2, 'Brent Cross':3, 'Brentwood':9, 'Brixton':2,
  'Bromley-by-Bow':'2+3', 'Buckhurst Hill':5, 'Burnt Oak':4, 'Caledonian Road':2, 'Camden Town':2, 'Canada Water':2,
  'Canary Wharf':2, 'Canning Town':'2+3', 'Cannon Street':1, 'Canons Park':5, 'Chadwell Heath':5,
  'Chalfont & Latimer':8, 'Chalk Farm':2, 'Chancery Lane':1, 'Charing Cross':1, 'Chesham':9, 'Chigwell':4,
  'Chiswick Park':3, 'Chorleywood':7, 'Clapham Common':2, 'Clapham North':2, 'Clapham South':'2+3', 'Cockfosters':5,
  'Colindale':4, 'Colliers Wood':3, 'Covent Garden':1, 'Croxley':7, 'Custom House':3, 'Dagenham East':5,
  'Dagenham Heathway':5, 'Debden':6, 'Dollis Hill':3, 'Ealing Broadway':3, 'Ealing Common':3, "Earl's Court":'1+2',
  'East Acton':2, 'East Finchley':3, 'East Ham':'3+4', 'East Putney':'2+3', 'Eastcote':5, 'Edgware':5,
  'Edgware Road (Bakerloo)':1, 'Edgware Road (Circle line)':1, 'Elephant & Castle':'1+2', 'Elm Park':6,
  'Embankment':1, 'Epping':6, 'Euston':1, 'Euston Square':1, 'Fairlop':4, 'Farringdon':1, 'Finchley Central':4,
  'Finchley Road':2, 'Finsbury Park':2, 'Forest Gate':3, 'Fulham Broadway':2, 'Gants Hill':4, 'Gidea Park':6,
  'Gloucester Road':1, 'Golders Green':3, 'Goldhawk Road':2, 'Goodge Street':1, 'Goodmayes':4, 'Grange Hill':4,
  'Great Portland Street':1, 'Green Park':1, 'Greenford':4, 'Gunnersbury':3, 'Hainault':4,
  'Hammersmith (District & Piccadilly)':2, 'Hammersmith (H&C line)':2, 'Hampstead':'2+3', 'Hanger Lane':3,
  'Hanwell':4, 'Harlesden':3, 'Harold Wood':6, 'Harrow & Wealdstone':5, 'Harrow-on-the-Hill':5, 'Hatton Cross':'5+6',
  'Hayes & Harlington':5, 'Heathrow Terminal 4':6, 'Heathrow Terminal 5':6, 'Heathrow Terminals 2 & 3':6,
  'Hendon Central':'3+4', 'High Barnet':5, 'High Street Kensington':1, 'Highbury & Islington':2, 'Highgate':3,
  'Hillingdon':6, 'Holborn':1, 'Holland Park':2, 'Holloway Road':2, 'Hornchurch':6, 'Hounslow Central':4,
  'Hounslow East':4, 'Hounslow West':5, 'Hyde Park Corner':1, 'Ickenham':6, 'Ilford':4, 'Kennington':'1+2',
  'Kensal Green':2, 'Kensington (Olympia)':2, 'Kentish Town':2, 'Kenton':4, 'Kew Gardens':'3+4', 'Kilburn':2,
  'Kilburn Park':2, "King's Cross St. Pancras":1, 'Kingsbury':4, 'Knightsbridge':1, 'Ladbroke Grove':2,
  'Lambeth North':1, 'Lancaster Gate':1, 'Latimer Road':2, 'Leicester Square':1, 'Leyton':3, 'Leytonstone':'3+4',
  'Liverpool Street':1, 'London Bridge':1, 'Loughton':6, 'Maida Vale':2, 'Manor House':'2+3', 'Manor Park':'3+4',
  'Mansion House':1, 'Marble Arch':1, 'Maryland':3, 'Marylebone':1, 'Mile End':2, 'Mill Hill East':4, 'Monument':1,
  'Moor Park':'6+7', 'Moorgate':1, 'Morden':4, 'Mornington Crescent':2, 'Neasden':3, 'Newbury Park':4, 'Nine Elms':1,
  'North Acton':'2+3', 'North Ealing':3, 'North Greenwich':'2+3', 'North Harrow':5, 'North Wembley':4,
  'Northfields':3, 'Northolt':5, 'Northwick Park':4, 'Northwood':6, 'Northwood Hills':6, 'Notting Hill Gate':'1+2',
  'Oakwood':5, 'Old Street':1, 'Osterley':4, 'Oval':2, 'Oxford Circus':1, 'Paddington':1, 'Paddington (H&C line)':1,
  'Park Royal':3, 'Parsons Green':2, 'Perivale':4, 'Piccadilly Circus':1, 'Pimlico':1, 'Pinner':5, 'Plaistow':3,
  'Preston Road':4, 'Putney Bridge':2, "Queen's Park":2, 'Queensbury':4, 'Queensway':1, 'Ravenscourt Park':2,
  'Rayners Lane':5, 'Redbridge':4, "Regent's Park":1, 'Richmond':4, 'Rickmansworth':7, 'Roding Valley':4,
  'Romford':6, 'Royal Oak':2, 'Ruislip':6, 'Ruislip Gardens':5, 'Ruislip Manor':6, 'Russell Square':1,
  'Seven Kings':4, 'Seven Sisters':3, "Shepherd's Bush":2, "Shepherd's Bush Market":2, 'Sloane Square':1,
  'Snaresbrook':4, 'South Ealing':3, 'South Harrow':5, 'South Kensington':1, 'South Kenton':4, 'South Ruislip':5,
  'South Wimbledon':'3+4', 'South Woodford':4, 'Southall':4, 'Southfields':3, 'Southgate':4, 'Southwark':1,
  "St. James's Park":1, "St. John's Wood":2, "St. Paul's":1, 'Stamford Brook':2, 'Stanmore':5, 'Stepney Green':2,
  'Stockwell':2, 'Stonebridge Park':3, 'Stratford':'2+3', 'Sudbury Hill':4, 'Sudbury Town':4, 'Swiss Cottage':2,
  'Temple':1, 'Theydon Bois':6, 'Tooting Bec':3, 'Tooting Broadway':3, 'Tottenham Court Road':1, 'Tottenham Hale':3,
  'Totteridge & Whetstone':4, 'Tower Hill':1, 'Tufnell Park':2, 'Turnham Green':'2+3', 'Turnpike Lane':3,
  'Upminster':6, 'Upminster Bridge':6, 'Upney':4, 'Upton Park':3, 'Uxbridge':6, 'Vauxhall':'1+2', 'Victoria':1,
  'Walthamstow Central':3, 'Wanstead':4, 'Warren Street':1, 'Warwick Avenue':2, 'Waterloo':1, 'Watford':7,
  'Wembley Central':4, 'Wembley Park':4, 'West Acton':3, 'West Brompton':2, 'West Drayton':6, 'West Ealing':3,
  'West Finchley':4, 'West Ham':'2+3', 'West Hampstead':2, 'West Harrow':5, 'West Kensington':2, 'West Ruislip':6,
  'Westbourne Park':2, 'Westminster':1, 'White City':2, 'Whitechapel':2, 'Willesden Green':'2+3',
  'Willesden Junction':'2+3', 'Wimbledon':3, 'Wimbledon Park':3, 'Wood Green':3, 'Wood Lane':2, 'Woodford':4,
  'Woodside Park':4, 'Woolwich':4
}

# OSM spells some names differently; positions help where two stations share a name.
OSM_NAME = {
  'Edgware Road (Bakerloo)': 'Edgware Road', 'Edgware Road (Circle line)': 'Edgware Road',
  'Hammersmith (H&C line)': 'Hammersmith', 'Hammersmith (District & Piccadilly)': 'Hammersmith',
  'Paddington (H&C line)': 'Paddington',
}
NEAR = {
  'Edgware Road (Bakerloo)': (51.5203, -0.1702), 'Edgware Road (Circle line)': (51.5199, -0.1679),
  'Hammersmith (H&C line)': (51.4935, -0.2252), 'Hammersmith (District & Piccadilly)': (51.4925, -0.2235),
  'Paddington (H&C line)': (51.5188, -0.1794), 'Paddington': (51.5157, -0.1755),
}

# ── Platform directions, as TfL names them ──────────────────────────────────
# Codes: N/S/E/W = Northbound/Southbound/Eastbound/Westbound, I/O = Inner/Outer Rail.
# Checked against the platform names in TfL's live arrivals feed.
OPP = {'N': 'S', 'S': 'N', 'E': 'W', 'W': 'E', 'I': 'O', 'O': 'I'}
HAINAULT_LOOP = ['Leytonstone', 'Wanstead', 'Redbridge', 'Gants Hill', 'Newbury Park', 'Barkingside', 'Fairlop', 'Hainault',
  'Grange Hill', 'Chigwell', 'Roding Valley', 'Woodford']
JUBILEE_EAST = set(JUBILEE[16:])          # Westminster … Stratford are Eastbound/Westbound
MET_EW = set(M_CITY[:8]) | set(M_UXB[2:])  # Aldgate … Great Portland Street, Rayners Lane … Uxbridge

def direction(line, a, b, base):
  """TfL's direction name for the hop a → b, given the line's plain direction for it."""
  if line == 'C' and a in HAINAULT_LOOP and b in HAINAULT_LOOP and a != 'Leytonstone':
    return 'I' if HAINAULT_LOOP.index(b) > HAINAULT_LOOP.index(a) else 'O'
  if line == 'D' and a in D_EDG[:4] and b in D_EDG[:5]:   # Circle tracks west of Edgware Road
    return 'I' if D_EDG.index(b) > D_EDG.index(a) else 'O'
  if line == 'J' and a in JUBILEE_EAST: return {'S': 'E', 'N': 'W'}[base]
  if line == 'M' and a in MET_EW: return {'N': 'W', 'S': 'E'}[base]
  return base

def circle(i, cw):
  """Circle line direction leaving CIRCLE[i]: clockwise (towards Baker Street from Edgware Road) or not."""
  south, west = range(19, 32), range(33, 36)   # Tower Hill … Gloucester Road; Notting Hill Gate … Paddington
  if cw: return 'W' if i in south else 'O' if i in west else 'E'
  return 'I' if i in west or i == 36 else 'W' if i == 32 else 'E' if i in south else 'W'

def norm(n):
  n = n.lower().replace('&', 'and').replace('’', "'")
  n = re.sub(r'\b(underground|rail|tube|elizabeth line)\b station', '', n)
  n = re.sub(r'\s*\(.*?\)', '', n).replace(' station', '')
  n = re.sub(r'^london ', '', n)
  n = n.replace('st. ', 'st ').replace("'", '').replace('-', ' ')
  return re.sub(r'\s+', ' ', n).strip()

def hav(a, b):
  R = 6371; la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
  x = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
  return 2 * R * math.asin(math.sqrt(x))

def slug(n):
  return re.sub(r'[^a-z0-9]+', '_', n.lower().replace('&', 'and').replace("'", '')).strip('_')

def download():
  body = urllib.parse.urlencode({'data': QUERY}).encode()
  last = None
  for attempt in range(4):
    for ep in ENDPOINTS:
      try:
        req = urllib.request.Request(ep, data=body, headers={'User-Agent': 'london-tube-planner'})
        return json.load(urllib.request.urlopen(req, timeout=300))
      except Exception as e:
        last = e
        if 'CERTIFICATE_VERIFY_FAILED' in str(e):
          # Some Python installs lack CA certificates; curl uses the system store.
          r = subprocess.run(['curl', '-s', '-m', '300', '-A', 'london-tube-planner', '--data-binary', '@-', ep],
                             input=body, capture_output=True)
          try: return json.loads(r.stdout)
          except ValueError: last = r.stdout[:120]
        print(f'// {ep}: {str(last)[:100]}', file=sys.stderr)
    time.sleep(20 * (attempt + 1))
  sys.exit(f'Overpass download failed: {last}')

def main():
  if '--osm' in sys.argv:
    data = json.load(open(sys.argv[sys.argv.index('--osm') + 1]))
  else:
    data = download()
    if '--save' in sys.argv: json.dump(data, open(sys.argv[sys.argv.index('--save') + 1], 'w'))
  nodes = {e['id']: e for e in data['elements'] if e['type'] == 'node'}
  rels = [e for e in data['elements'] if e['type'] == 'relation']

  # Every stop position each line's relations use, by normalised name; station nodes are
  # the fallback where a relation lacks a stop.
  stops = {l[0]: {} for l in LINES}
  station_nodes = {}
  for n in nodes.values():
    t = n.get('tags', {})
    if t.get('railway') == 'station' and t.get('station') == 'subway' and 'name' in t:
      station_nodes.setdefault(norm(t['name']), []).append((n['lat'], n['lon']))
  for r in rels:
    name = r['tags'].get('name', '')
    lid = next((l[0] for l in LINES if name.startswith(l[5])), None)
    if not lid: continue
    members = [m for m in r['members'] if m['type'] == 'node' and m['role'].startswith('stop')]
    if not members: members = [m for m in r['members'] if m['type'] == 'node' and m['role'].startswith('platform')]
    for m in members:
      n = nodes.get(m['ref'])
      if not n or 'name' not in n.get('tags', {}): continue
      stops[lid].setdefault(norm(n['tags']['name']), []).append((n['lat'], n['lon']))

  def position(lid, st):
    cands = stops[lid].get(norm(OSM_NAME.get(st, st))) or station_nodes.get(norm(OSM_NAME.get(st, st)), [])
    # Two different stations share the name on this line (the Circle's two Paddingtons).
    if st in NEAR and max((hav(p, q) for p in cands for q in cands), default=0) > 0.3:
      cands = [p for p in cands if hav(p, NEAR[st]) < 0.25]
    assert cands, f'{lid}: no OSM stop for {st}'
    # Ignore stray points far from the rest (mis-tagged stops).
    mid = sorted(cands)[len(cands) // 2]
    near = [p for p in cands if hav(p, mid) < 0.4] or cands
    return [round(sum(p[0] for p in near) / len(near), 5), round(sum(p[1] for p in near) / len(near), 5)]

  # Stations, with each line's own platform position.
  stations = {}
  def station(name):
    if name not in stations:
      assert name in ZONES, f'no zone for {name}'
      stations[name] = {'id': slug(name), 'name': name, 'p': {}}
    return stations[name]
  for r in ROUTES:
    for st in r['seq']:
      s = station(st)
      if r['line'] not in s['p']: s['p'][r['line']] = position(r['line'], st)

  # Calibrate each line's straight-line distances to its official length.
  lines_out = []
  for lid, name, colour, tc, km, *_ in LINES:
    pairs = {}
    for r in ROUTES:
      if r['line'] != lid: continue
      for a, b in zip(r['seq'], r['seq'][1:]): pairs[frozenset((a, b))] = (a, b)
    raw = sum(hav(stations[a]['p'][lid], stations[b]['p'][lid]) for a, b in pairs.values())
    k = round(km / raw, 3) if km else 1.06
    print(f'// {lid}: {len(pairs)} segments, {raw:.1f} km straight-line vs {km} km official, k={k}', file=sys.stderr)
    lines_out.append({'id': lid, 'name': name, 'color': colour, 'tc': tc, 'k': k})

  base = {l[0]: l[6] for l in LINES}
  def dirs(r):
    seq, lid = r['seq'], r['line']
    if lid == 'Ci':
      return ''.join(circle(i, True) for i in range(len(seq) - 1)), ''.join(circle(i + 1, False) for i in range(len(seq) - 1))
    d = r.get('dir', base[lid])
    f = ''.join(direction(lid, a, b, d) for a, b in zip(seq, seq[1:]))
    b = ''.join(direction(lid, seq[i + 1], seq[i], OPP[d]) for i in range(len(seq) - 1))
    return f, b

  routes_out = []
  for r in ROUTES:
    f, b = dirs(r)
    rec = {'id': r['id'], 'line': r['line'], 'seq': [stations[s]['id'] for s in r['seq']], 'df': f}
    if not r.get('oneway'): rec['db'] = b
    for key in ('via', 'wait', 'night', 'weekdays', 'to', 'oneway'):
      if key in r: rec[key] = r[key]
    routes_out.append(rec)

  # Platform-advice services: each as [line, via, stop ids…] in travel order.
  by_id = {r['id']: r for r in ROUTES}
  svc = []
  for spec in SERVICES:
    rid, a, b = spec[:3]
    seq = by_id[rid]['seq']
    i, j = seq.index(a), seq.index(b)
    part = seq[i:j + 1] if i < j else rev(seq[j:i + 1])
    svc.append({'line': by_id[rid]['line'], 'via': spec[3] if len(spec) > 3 else by_id[rid].get('via'),
                'stops': [stations[s]['id'] for s in part]})
  for lid, seq, via in EXTRA:
    for part in (seq, rev(seq)):
      svc.append({'line': lid, 'via': via, 'stops': [stations[s]['id'] for s in part]})

  for a, b, kind, *only in LINKS: assert a in stations and b in stations, (a, b)
  ends = {r['seq'][0] for r in ROUTES if not r.get('night')} | {r['seq'][-1] for r in ROUTES if not r.get('night')}

  out = ['  lines:[']
  for l in lines_out: out.append('    ' + json.dumps(l, separators=(',', ':')) + ',')
  out.append('  ],')
  out.append('  // Service patterns. df/db: TfL direction code for each stop-to-stop hop, forwards and backwards.')
  out.append('  routes:[')
  for r in routes_out: out.append('    ' + json.dumps(r, separators=(',', ':')) + ',')
  out.append('  ],')
  out.append('  // Other regular trains (short workings, part-time through trains), for platform advice.')
  out.append('  services:[')
  for s in svc: out.append('    ' + json.dumps([s['line'], s['via'] or ''] + s['stops'], separators=(',', ':')) + ',')
  out.append('  ],')
  out.append("  // Official interchanges between differently named stations: 'in' = inside, 'osi' = out of station.")
  out.append('  links:' + json.dumps([[stations[a]['id'], stations[b]['id'], kind] + list(only) for a, b, kind, *only in LINKS],
                                      separators=(',', ':')) + ',')
  out.append('  stations:[')
  for s in sorted(stations.values(), key=lambda s: s['name']):
    pts = list(s['p'].values())
    lat = round(sum(p[0] for p in pts) / len(pts), 5); lng = round(sum(p[1] for p in pts) / len(pts), 5)
    spread = max(hav(a, b) for a in pts for b in pts)
    if spread > 0.3: print(f'// wide station {s["name"]}: {spread * 1000:.0f} m across lines', file=sys.stderr)
    z = ZONES[s['name']]
    rec = {'id': s['id'], 'name': s['name'], 'lat': lat, 'lng': lng,
           'z': [int(x) for x in z.split('+')] if isinstance(z, str) else z, 'p': s['p']}
    if s['name'] in MAJOR: rec['major'] = 1
    if s['name'] in ends: rec['terminal'] = 1
    out.append('    ' + json.dumps(rec, ensure_ascii=False, separators=(',', ':')) + ',')
  out.append('  ]')
  html = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'LondonTubePlanner.html')
  src = open(html, encoding='utf-8').read()
  begin, end = '  // BEGIN GENERATED by tools/build_stations.py\n', '  // END GENERATED\n'
  a, b = src.index(begin) + len(begin), src.index(end)
  open(html, 'w', encoding='utf-8').write(src[:a] + '\n'.join(out) + '\n' + src[b:])
  print(f'// {len(stations)} stations, {len(routes_out)} routes written to {html}', file=sys.stderr)

main()
