# Scene query
from typing import Dict, Any


def _geo_answer(geo: Dict[str, Any]) -> str:
    matches = geo.get("matches") or []
    if not matches:
        return "Cyber geo routing is on. No IP or domain matched."
    parts = []
    for item in matches:
        if item.get("ip"):
            parts.append(f"{item['ip']} -> {item.get('country') or 'unlisted'}")
        if item.get("domain"):
            categories = ", ".join(item.get("categories") or []) or "unlisted"
            parts.append(f"{item['domain']} -> {categories}")
    return "Cyber geo routing: " + "; ".join(parts) + "."


class SceneQuery:
    def ask(self, question: str, picture: Dict[str, Any]) -> Dict[str, Any]:
        q = question.lower()
        tracks = picture.get("tracks", [])
        alerts = picture.get("defense_alerts", [])
        if "uas" in q or "drone" in q:
            matches = [t for t in tracks if t["classification"] == "uas"]
            return {"question": question, "answer": f"Found {len(matches)} UAS track(s)."}
        if "alert" in q or "threat" in q:
            return {"question": question, "answer": f"There are {len(alerts)} active defense alert(s)."}
        geo = picture.get("geo")
        if geo and any(word in q for word in ("country", "domain", "category", "geo")):
            return {"question": question, "answer": _geo_answer(geo)}
        return {"question": question, "answer": f"Picture has {len(tracks)} tracks and {len(alerts)} alerts."}
