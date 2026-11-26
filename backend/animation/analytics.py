"""Analytics Engine: how the published episodes did, and what that says for the next ones.

- collect: reads each published episode's numbers from the channel's own YouTube account (the
  public counters, and the analytics report when YouTube has it: it lags a day or two) and keeps a
  dated row per reading.
- summary: each episode's latest reading next to what the episode was (length, scenes, sets,
  whether it showed a simulation, its hook).
- lessons: what the channel's own data says, in words, for whoever chooses the next question. It
  only compares the channel with itself, needs a minimum of episodes before saying anything, and
  never mentions other channels' figures.

Nothing here decides anything: the lessons are shown in the panel and offered to the topic
chooser as observed demand, next to its editorial criteria.
"""
import json
import logging
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from animation.db import Episode, Metric, Publication

logger = logging.getLogger("animation.analytics")
# Fewer published episodes with data than this say nothing about what works.
MIN_EPISODES = 3
MIN_VIEWS = 100


async def collect(db: Session, client) -> int:
    """One reading per published episode. Returns how many were read. client: the channel's
    YouTube client (shared/youtube.py); the caller checks that it is connected."""
    rows = db.execute(select(Publication).where(Publication.external_id.is_not(None))).scalars().all()
    ids = [p.external_id for p in rows]
    if not ids:
        return 0
    public = await client.public_stats(ids)
    try:
        deep = await client.video_stats(ids)
    except Exception as e:   # the analytics scope may be missing, or the report not ready yet
        logger.warning("Analytics report not read: %s", e)
        deep = {}
    read = 0
    for p in rows:
        counters = public.get(p.external_id)
        if counters is None:
            continue
        report = deep.get(p.external_id, {})
        db.add(Metric(publication_id=p.id, views=counters["views"], likes=counters["likes"], comments=counters["comments"],
                      avg_view_percentage=report.get("averageViewPercentage"), avg_view_seconds=report.get("averageViewDuration"),
                      subscribers_gained=report.get("subscribersGained"), shares=report.get("shares")))
        read += 1
    db.commit()
    return read


def summary(db: Session) -> list[dict]:
    """Published episodes, newest first, each with its latest reading (None: not read yet)."""
    out = []
    for p in db.execute(select(Publication).where(Publication.external_id.is_not(None)).order_by(Publication.id.desc())).scalars():
        ep = db.get(Episode, p.episode_id)
        m = db.execute(select(Metric).where(Metric.publication_id == p.id).order_by(Metric.id.desc())).scalars().first()
        sb = json.loads(ep.storyboard_json or "{}")
        script = json.loads(ep.script_json or "{}")
        scenes = sb.get("scenes", [])
        hooks = script.get("hooks") or []
        out.append({
            "episode_id": ep.id, "title": ep.title, "video_id": p.external_id, "privacy": p.privacy,
            "published_at": p.published_at.isoformat() if p.published_at else None,
            "seconds": ep.duration, "scenes": len(scenes), "sets": sorted({s["set"] for s in scenes}),
            "simulation": any(pr["prop"].startswith("sim_") for s in scenes for pr in s["props"]),
            "words": (script.get("checks") or {}).get("words"),
            "hook": hooks[script.get("chosen_hook", 0)]["text"] if hooks else "",
            "metrics": None if m is None else {
                "views": m.views, "likes": m.likes, "comments": m.comments, "avg_view_percentage": m.avg_view_percentage,
                "avg_view_seconds": m.avg_view_seconds, "subscribers_gained": m.subscribers_gained, "shares": m.shares,
                "read_at": m.fetched_at.isoformat()},
        })
    return out


def lessons(db: Session) -> dict:
    """{"enough", "text", "episodes"}: what the channel's own numbers say. text is ready to show
    and to hand to the topic chooser; when there is not enough data it says so and nothing else."""
    rows = [r for r in summary(db) if r["metrics"] and r["metrics"]["views"] >= MIN_VIEWS and r["privacy"] == "public"]
    if len(rows) < MIN_EPISODES:
        return {"enough": False, "episodes": len(rows),
                "text": f"Sin datos de demanda observada: el canal tiene {len(rows)} episodio(s) públicos con al menos "
                        f"{MIN_VIEWS} visitas y hacen falta {MIN_EPISODES} para comparar."}
    typical = median(r["metrics"]["views"] for r in rows)
    held = [r for r in rows if r["metrics"]["avg_view_percentage"] is not None]
    lines = [f"Datos propios del canal ({len(rows)} episodios públicos; lo habitual son {typical:,.0f} visitas).".replace(",", ".")]
    for label, pick in (("Más visto", max), ("Menos visto", min)):
        r = pick(rows, key=lambda r: r["metrics"]["views"])
        lines.append(f"{label}: «{r['title']}» ({r['metrics']['views'] / typical:.1f} veces lo habitual).")
    if len(held) >= MIN_EPISODES:
        best = max(held, key=lambda r: r["metrics"]["avg_view_percentage"])
        lines.append(f"Mejor retención: «{best['title']}» ({best['metrics']['avg_view_percentage']:.0f} % visto de media; "
                     f"{best['seconds']:.0f} s, {best['scenes']} escenas{', con simulación' if best['simulation'] else ''}).")
        with_sim = [r["metrics"]["avg_view_percentage"] for r in held if r["simulation"]]
        without = [r["metrics"]["avg_view_percentage"] for r in held if not r["simulation"]]
        if len(with_sim) >= 2 and len(without) >= 2:
            lines.append(f"Retención media con simulación {median(with_sim):.0f} % frente a {median(without):.0f} % sin ella.")
    lines.append("Son pocos episodios: sirven de pista, no de regla.")
    return {"enough": True, "episodes": len(rows), "text": " ".join(lines)}
