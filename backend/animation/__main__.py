"""Command line of the animation engine. Run from the backend folder.

    python -m animation --channel curiolab check                 qué hay instalado y registrado
    python -m animation --channel curiolab demo                  episodio de demostración, sin gasto
    python -m animation --channel curiolab produce "¿Pregunta?"  episodio con Claude y ElevenLabs
    python -m animation --channel curiolab produce               el motor elige el tema
    python -m animation --channel curiolab resume 3
    python -m animation --channel curiolab retake 3 s2           vuelve a dibujar una escena
    python -m animation --channel curiolab redo 3 guion          rehace desde una etapa (investigacion|guion|storyboard)
    python -m animation --channel curiolab list
    python -m animation --channel curiolab approve 3             (o: reject 3)

Nothing here publishes: a finished episode waits in LISTO_PARA_REVISIÓN.
"""
import argparse
import asyncio
import logging
import shutil
import sys

from sqlalchemy import func, select

from animation import godot, pipeline
from animation.db import APROBADO, ERROR, LISTO, Cost, Episode, open_db
from animation.godot import Cancelled
from animation.ledger import BudgetExceeded
from animation.library import default_library
from animation.profile import load_profile
from animation.research import NeedsReview
from animation.storyboard import StoryboardRejected


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="animation")
    parser.add_argument("--channel", required=True, help="clave del perfil en backend/channels/")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sub.add_parser("demo")
    sub.add_parser("list")
    p = sub.add_parser("produce")
    p.add_argument("topic", nargs="?", default="")
    for name in ("resume", "approve", "reject"):
        p = sub.add_parser(name)
        p.add_argument("episode", type=int)
    p = sub.add_parser("retake")
    p.add_argument("episode", type=int)
    p.add_argument("scene")
    p = sub.add_parser("redo")
    p.add_argument("episode", type=int)
    p.add_argument("stage", choices=list(pipeline.FIELDS_FROM))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    profile = load_profile(args.channel)
    lib = default_library()

    if args.command == "check":
        binary = godot.find_godot()
        print(f"Canal:      {profile.name} ({profile.key}) · datos en {profile.data_dir}")
        print(f"Godot:      {binary or 'NO ENCONTRADO: define GODOT_BIN en backend/.env'}")
        print(f"FFmpeg:     {shutil.which('ffmpeg') or 'NO ENCONTRADO'}")
        print(f"Remotion:   {shutil.which('npx') or 'NO ENCONTRADO (npx)'}")
        print(f"Biblioteca: v{lib.version} · {len(lib.characters)} personajes, {len(lib.actions)} acciones, {len(lib.sets)} escenarios, "
              f"{len(lib.props)} objetos · huella {lib.fingerprint}")
        missing = lib.missing_files() + [f"voz de {c}" for c in profile.cast if lib.characters[c]["voice"] not in profile.voices]
        print("Faltan:     " + (", ".join(missing) or "nada"))
        return 0 if binary and not missing else 1

    db = open_db(profile.data_dir)
    if args.command == "list":
        for ep in db.execute(select(Episode).order_by(Episode.id)).scalars():
            spent = db.execute(select(func.coalesce(func.sum(Cost.usd), 0.0)).where(Cost.episode_id == ep.id)).scalar_one()
            print(f"{ep.id:4} {ep.status:20} {spent:5.2f} USD  {ep.title or ep.topic}  {ep.error or ''}")
        return 0
    if args.command in ("approve", "reject"):
        ep = db.get(Episode, args.episode)
        if ep is None or ep.status != LISTO:
            print("Solo se decide un episodio que está listo para revisión.")
            return 1
        ep.status = APROBADO if args.command == "approve" else ERROR
        ep.error = None if args.command == "approve" else "Rechazado en la revisión."
        db.commit()
        print(f"Episodio {ep.id}: {ep.status}. (Aprobar no publica: la publicación es un paso aparte.)")
        return 0
    if args.command in ("retake", "redo"):
        ep = db.get(Episode, args.episode)
        if ep is None:
            print("No existe ese episodio.")
            return 1
        if args.command == "retake":
            pipeline.retake_scene(db, ep, args.scene)
        else:
            pipeline.regenerate_from(db, ep, args.stage)
        episode_id = ep.id
    elif args.command == "resume":
        episode_id = args.episode
    else:
        episode_id = pipeline.new_episode(db, profile, topic=getattr(args, "topic", ""), mode="demo" if args.command == "demo" else "ia").id
    try:
        ep = asyncio.run(pipeline.produce(profile, db, episode_id))
    except NeedsReview as e:
        print(f"\nEl episodio necesita revisión humana: {e}")
        return 2
    except BudgetExceeded as e:
        print(f"\nDetenido por el límite de gasto: {e}")
        return 3
    except StoryboardRejected as e:
        print("\nStoryboard rechazado:\n  " + "\n  ".join(e.problems))
        return 4
    except Cancelled:
        print("\nCancelado.")
        return 5
    print(f"\nEpisodio {ep.id} listo para revisión ({ep.duration:.1f} s).\n  Video:   {ep.output_path}\n  Informe: "
          f"{pipeline.episode_dir(profile, ep.id) / 'calidad.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
