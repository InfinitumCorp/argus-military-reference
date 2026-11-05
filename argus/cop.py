# Common Operating Picture — clean white Infinitum product aesthetic
from typing import Dict, Any
from pathlib import Path

def generate_cop_html(picture: Dict[str, Any], output_path: str = "cop.html") -> str:
    tracks = picture.get("tracks", [])
    alerts = picture.get("defense_alerts", [])
    spectrum = picture.get("spectrum", {})
    forecasts = picture.get("forecasts", [])
    if tracks:
        center_lat = sum(t["position"]["lat"] for t in tracks) / len(tracks)
        center_lon = sum(t["position"]["lon"] for t in tracks) / len(tracks)
    else:
        center_lat, center_lon = 38.9072, -77.0369
    track_markers = []
    for t in tracks:
        color = "#c53030" if t["classification"] == "uas" else "#2b6cb0"
        track_markers.append({"lat": t["position"]["lat"], "lon": t["position"]["lon"], "id": t["track_id"], "class": t["classification"], "speed": round(t["velocity_mps"],1), "color": color, "explanation": t["explanation"]})
    html = f'''<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>>_ARGUS™ COP</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>body{{margin:0;font-family:Arial,sans-serif;background:#fff;color:#1a202c}}#header{{padding:16px 28px;border-bottom:1px solid #e2e8f0;display:flex;justify-content:space-between}}#map{{height:calc(100vh-64px)}}#sidebar{{position:absolute;top:80px;right:16px;width:320px;background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:16px;box-shadow:0 4px 12px rgba(0,0,0,.06)}}</style>
</head><body>
<div id="header"><div><h1 style="margin:0;font-size:18px">>_ARGUS™</h1><div style="font-size:12px;color:#718096">Common Operating Picture · Military Edition</div></div>
<div>Tracks <strong>{len(tracks)}</strong> · Alerts <strong>{len(alerts)}</strong></div></div>
<div id="map"></div>
<div id="sidebar"><h3 style="margin:0 0 8px;font-size:12px;color:#718096">DEFENSE ALERTS</h3>
{''.join(f'<div style="background:#fff5f5;border:1px solid #fed7d7;padding:8px;margin:6px 0;border-radius:6px">{a["threat_type"]} · {a["priority"]:.2f}<br>{a["explanation"][:100]}</div>' for a in alerts[:4]) or '<p>No alerts</p>'}
<p style="font-size:11px;color:#718096;margin-top:12px">Human-commanded. Recommendations are advisory.<br>Military edition · Private Firmament</p></div>
<script>
const map = L.map('map').setView([{center_lat},{center_lon}],14);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png',{{attribution:'&copy; OpenStreetMap &copy; CARTO'}}).addTo(map);
const tracks = {track_markers};
tracks.forEach(t => L.circleMarker([t.lat,t.lon],{{radius:7,fillColor:t.color,color:'#fff',weight:2,fillOpacity:.9}}).addTo(map).bindPopup(`<b>${{t.id}}</b><br>${{t.class}} · ${{t.speed}} m/s`));
</script></body></html>'''
    Path(output_path).write_text(html, encoding="utf-8")
    return output_path
