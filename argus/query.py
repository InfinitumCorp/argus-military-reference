# Scene query
from typing import Dict, Any

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
        return {"question": question, "answer": f"Picture has {len(tracks)} tracks and {len(alerts)} alerts."}
