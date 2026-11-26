"""The asset library as the backend sees it: what animator/library/manifest.json registers
(actions, emotions, cameras, effects, sets, objects) and the character definitions next to it.

It is the single list both sides read. The backend validates storyboards against it and offers it
to Claude as the only vocabulary; the Godot director loads the same file. Adding an action, a set
or an object is a script in animator/ plus its entry in the manifest: no code here changes.
"""
import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ANIMATOR = Path(__file__).resolve().parents[2] / "animator"


class LibraryError(Exception):
    pass


@dataclass(frozen=True)
class Library:
    root: Path
    version: int
    actions: dict
    emotions: tuple
    cameras: dict
    effects: dict
    sets: dict
    props: dict
    characters: dict
    fps: int
    # Changes whenever a script or the manifest changes: part of every scene's render key, so a
    # scene drawn by an older engine is drawn again.
    fingerprint: str

    def missing_files(self) -> list[str]:
        """Scripts the manifest names that are not on disk."""
        named = [e["script"] for table in (self.actions, self.sets, self.props) for e in table.values()]
        return sorted({s for s in named if not (self.root / s.removeprefix("res://")).is_file()})

    def catalog(self, cast: list[str]) -> str:
        """The library as text, for the prompt that writes a storyboard."""
        lines = ["PERSONAJES:"]
        for cid in cast:
            c = self.characters[cid]
            lines.append(f"- {cid}: {c['name']}, {c['role']}. {c['personality']} Restricciones: {' '.join(c.get('restrictions', []))}")
        lines.append("ACCIONES (campo action): " + "; ".join(f"{k} = {v['desc']}" for k, v in self.actions.items()))
        lines.append("EMOCIONES: " + ", ".join(self.emotions))
        lines.append("CÁMARAS: " + "; ".join(f"{k} = {v['desc']}" for k, v in self.cameras.items()))
        lines.append("EFECTOS: " + "; ".join(f"{k} = {v['desc']}" for k, v in self.effects.items()))
        lines.append("ESCENARIOS:")
        for sid, s in self.sets.items():
            lines.append(f"- {sid}: {s['desc']}. Sitios para personajes: {', '.join(s['anchors']) or 'ninguno'}. "
                         f"Sitios para objetos: {', '.join(s['prop_anchors'])}.")
        lines.append("OBJETOS:")
        for pid, p in self.props.items():
            extra = f" Parámetros: {', '.join(p['params'])}." if p.get("params") else ""
            extra += " (Se suelta con gravity_off.)" if p.get("loose") else ""
            extra += f" Necesita la simulación «{p['simulation']}»." if p.get("simulation") else ""
            lines.append(f"- {pid}: {p['desc']}.{extra}")
        return "\n".join(lines)


def load_library(root: Path | None = None) -> Library:
    root = Path(root or ANIMATOR)
    manifest_path = root / "library" / "manifest.json"
    if not manifest_path.is_file():
        raise LibraryError(f"no existe el manifiesto de la biblioteca: {manifest_path}")
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    characters = {}
    for cid in m["characters"]:
        path = root / "library" / "characters" / f"{cid}.json"
        if not path.is_file():
            raise LibraryError(f"falta la definición del personaje '{cid}': {path}")
        definition = json.loads(path.read_text(encoding="utf-8"))
        unknown = [a for a in definition.get("actions", []) if a not in m["actions"]]
        if definition.get("id") != cid or unknown:
            raise LibraryError(f"definición inválida de '{cid}' (acciones sin registrar: {unknown})")
        characters[cid] = definition
    digest = hashlib.sha1()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in (".gd", ".json", ".godot", ".tscn") and ".godot" not in path.parts:
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return Library(root=root, version=int(m["version"]), actions=m["actions"], emotions=tuple(m["emotions"]),
                   cameras=m["cameras"], effects=m["effects"], sets=m["sets"], props=m["props"],
                   characters=characters, fps=int(m["world"]["fps"]), fingerprint=digest.hexdigest()[:12])


@lru_cache(maxsize=1)
def default_library() -> Library:
    return load_library()
