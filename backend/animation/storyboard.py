"""The storyboard: the versioned contract between whoever plans an episode (Claude, or a person)
and the renderer. It is data, never code: scenes made of beats, each beat a line of dialogue or a
silent action, and everything it uses named by an id registered in the asset library.

    Storyboard
      schema_version, episode_id, title, format, target_seconds
      characters[]            ids of the cast
      sources[]               the scientific sources the facts came from
      scenes[]
        id, set, label        label: text shown on screen for the whole scene ("" for none)
        cast[]                who stands where: {character, at (a set anchor), facing}
        props[]               {uid, prop, at (a set prop anchor), params}
        beats[]               in order; time comes from the audio, not from here
          speaker, text       "" + "" for a silent beat, which lasts `seconds`
          emotion, action     of the speaker (or of `actor` in a silent beat)
          walk_to, look_at
          camera, camera_target
          effects[]
          reactions[]         what the others do meanwhile: {character, action, emotion}
          supports[]          the facts ("h3") or simulations ("sim:<id>") the line rests on
          science_event       what is being shown, in a few words ("" for none)

Times are relative: a beat starts when the previous one ends, and a line lasts what its audio
lasts. plan.py turns this into seconds once the voices exist.

validate() is the gate. A storyboard that names anything the library does not have is rejected
with the list of problems; repair() only fixes what cannot change the story (an emotion or a
camera that does not exist becomes the neutral one) and says what it changed.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from animation import llm
from animation.library import Library

SCHEMA_VERSION = 1
SILENT_RANGE = (0.6, 6.0)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRef(Strict):
    id: int
    url: str
    title: str = ""


class CastMember(Strict):
    character: str
    at: str
    facing: Literal["left", "right"] = "right"


class PropParams(Strict):
    label: str | None = None
    scale: float | None = Field(default=None, ge=0.3, le=3.0)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    angle: float | None = Field(default=None, ge=-360, le=360)
    length: float | None = Field(default=None, ge=20, le=600)
    values: list[float] | None = Field(default=None, max_length=24)
    marks: list[str] | None = Field(default=None, max_length=6)


class Prop(Strict):
    uid: str = Field(pattern=r"^[a-z0-9_]{1,24}$")
    prop: str
    at: str
    params: PropParams = Field(default_factory=PropParams)


class Reaction(Strict):
    character: str
    action: str
    emotion: str = "neutral"


class Beat(Strict):
    speaker: str = ""
    text: str = ""
    seconds: float = 0.0
    actor: str = ""
    emotion: str = "neutral"
    action: str = "talk"
    walk_to: str = ""
    look_at: str = ""
    camera: str = "static"
    camera_target: str = ""
    effects: list[str] = Field(default_factory=list)
    reactions: list[Reaction] = Field(default_factory=list)
    supports: list[str] = Field(default_factory=list)
    science_event: str = ""

    @property
    def who(self) -> str:
        return self.speaker or self.actor


class Scene(Strict):
    id: str = Field(pattern=r"^[a-z0-9_]{1,16}$")
    set: str
    label: str = ""
    cast: list[CastMember] = Field(default_factory=list)
    props: list[Prop] = Field(default_factory=list)
    beats: list[Beat] = Field(min_length=1)


class Storyboard(Strict):
    schema_version: Literal[1] = SCHEMA_VERSION
    episode_id: str
    title: str
    format: Literal["short"] = "short"
    target_seconds: int = Field(ge=15, le=180)
    characters: list[str] = Field(min_length=1)
    sources: list[SourceRef] = Field(default_factory=list)
    scenes: list[Scene] = Field(min_length=1)

    def lines(self) -> list[tuple[int, int, Beat]]:
        """Every spoken beat with its scene and beat index, in order."""
        return [(si, bi, b) for si, s in enumerate(self.scenes) for bi, b in enumerate(s.beats) if b.text.strip()]

    def words(self) -> int:
        return sum(len(b.text.split()) for _, _, b in self.lines())


class StoryboardRejected(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems[:12]))
        self.problems = problems


def parse(data: dict) -> Storyboard:
    """The shape. Raises StoryboardRejected with one line per field that is wrong."""
    try:
        return Storyboard(**data)
    except ValidationError as e:
        raise StoryboardRejected([f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()])
    except TypeError as e:
        raise StoryboardRejected([f"el storyboard no es un objeto: {e}"])


def repair(sb: Storyboard, lib: Library) -> list[str]:
    """Harmless fixes, made in place. Returns what was changed."""
    notes = []
    for scene in sb.scenes:
        for i, beat in enumerate(scene.beats):
            where = f"{scene.id}[{i}]"
            if beat.emotion not in lib.emotions:
                notes.append(f"{where}: emoción '{beat.emotion}' no existe → neutral")
                beat.emotion = "neutral"
            if beat.camera not in lib.cameras:
                notes.append(f"{where}: cámara '{beat.camera}' no existe → static")
                beat.camera, beat.camera_target = "static", ""
            if not lib.cameras[beat.camera].get("target"):
                beat.camera_target = ""
            if not beat.text.strip():
                clamped = min(max(beat.seconds, SILENT_RANGE[0]), SILENT_RANGE[1])
                if clamped != beat.seconds:
                    notes.append(f"{where}: pausa de {beat.seconds} s → {clamped} s")
                    beat.seconds = clamped
            for r in beat.reactions:
                if r.emotion not in lib.emotions:
                    notes.append(f"{where}: emoción de reacción '{r.emotion}' no existe → neutral")
                    r.emotion = "neutral"
    return notes


def validate(sb: Storyboard, lib: Library, known_support: set[str] | None = None,
             words: tuple[int, int] | None = None) -> list[str]:
    """Everything the storyboard names must exist and make sense on stage. Returns the problems
    (empty: it can be rendered). known_support: the fact and simulation ids a line may cite."""
    problems: list[str] = []
    for cid in sb.characters:
        if cid not in lib.characters:
            problems.append(f"personaje no registrado: {cid}")
    seen_ids = set()
    # Gravity switched off stays off across the cuts, until a scene switches it back on.
    weightless = False
    for scene in sb.scenes:
        sid = scene.id
        if sid in seen_ids:
            problems.append(f"escena repetida: {sid}")
        seen_ids.add(sid)
        if scene.set not in lib.sets:
            problems.append(f"{sid}: escenario no registrado: {scene.set}")
            continue
        stage = lib.sets[scene.set]
        on_stage, spots = set(), set()
        for member in scene.cast:
            if member.character not in sb.characters:
                problems.append(f"{sid}: {member.character} no está en el reparto del episodio")
            if member.at not in stage["anchors"]:
                problems.append(f"{sid}: '{member.at}' no es un sitio para personajes de {scene.set}")
            if member.at in spots or member.character in on_stage:
                problems.append(f"{sid}: dos personajes en '{member.at}' o {member.character} repetido")
            spots.add(member.at)
            on_stage.add(member.character)
        uids, used = set(), set()
        for prop in scene.props:
            entry = lib.props.get(prop.prop)
            if entry is None:
                problems.append(f"{sid}: objeto no registrado: {prop.prop}")
                continue
            if prop.at not in stage["prop_anchors"]:
                problems.append(f"{sid}: '{prop.at}' no es un sitio para objetos de {scene.set}")
            if prop.uid in uids or prop.uid in lib.characters:
                problems.append(f"{sid}: identificador de objeto repetido o igual a un personaje: {prop.uid}")
            if prop.at in used:
                problems.append(f"{sid}: dos objetos en '{prop.at}'")
            uids.add(prop.uid)
            used.add(prop.at)
            if entry.get("simulation") and known_support is not None and f"sim:{entry['simulation']}" not in known_support:
                problems.append(f"{sid}: {prop.prop} necesita la simulación '{entry['simulation']}', que este episodio no tiene")
            if entry.get("simulation") and not scene.label.strip():
                problems.append(f"{sid}: una escena con simulación lleva rótulo (label) que diga qué tipo de modelo es")
        for i, beat in enumerate(scene.beats):
            where = f"{sid}[{i}]"
            spoken = bool(beat.text.strip())
            if spoken and not beat.speaker:
                problems.append(f"{where}: hay texto sin personaje que lo diga")
            if beat.speaker and not spoken:
                problems.append(f"{where}: {beat.speaker} habla sin texto")
            if beat.speaker and beat.speaker not in sb.characters:
                problems.append(f"{where}: habla {beat.speaker}, que no está en el reparto")
            who = beat.who
            if who and who not in on_stage and (not spoken or beat.walk_to or beat.action not in ("talk", "idle")):
                # A character that is not on stage can only be heard.
                problems.append(f"{where}: {who} actúa pero no está en la escena")
            if beat.action not in lib.actions:
                problems.append(f"{where}: acción no registrada: {beat.action}")
            elif who in lib.characters and beat.action not in lib.characters[who]["actions"]:
                problems.append(f"{where}: {who} no tiene la acción {beat.action}")
            if beat.action == "walk" and beat.walk_to not in stage["anchors"]:
                problems.append(f"{where}: caminar necesita un destino (walk_to) que sea un sitio de {scene.set}")
            if beat.walk_to and beat.action != "walk":
                problems.append(f"{where}: walk_to solo acompaña a la acción walk")
            if beat.look_at and beat.look_at not in on_stage and beat.look_at not in uids:
                problems.append(f"{where}: mira a '{beat.look_at}', que no está en la escena")
            if beat.camera_target and beat.camera_target not in on_stage and beat.camera_target not in uids:
                problems.append(f"{where}: la cámara apunta a '{beat.camera_target}', que no está en la escena")
            if lib.cameras.get(beat.camera, {}).get("target") and not beat.camera_target:
                problems.append(f"{where}: la cámara {beat.camera} necesita a quién o a qué apuntar")
            for effect in beat.effects:
                if effect not in lib.effects:
                    problems.append(f"{where}: efecto no registrado: {effect}")
                weightless = {"gravity_off": True, "gravity_on": False}.get(effect, weightless)
            for r in beat.reactions:
                if r.character not in on_stage:
                    problems.append(f"{where}: reacciona {r.character}, que no está en la escena")
                elif r.character == who:
                    problems.append(f"{where}: {r.character} no puede reaccionar a su propia línea")
                if r.action not in lib.actions:
                    problems.append(f"{where}: acción de reacción no registrada: {r.action}")
                elif r.action == "walk":
                    problems.append(f"{where}: una reacción no puede ser caminar")
            if known_support is not None:
                for ref in beat.supports:
                    if ref not in known_support:
                        problems.append(f"{where}: cita '{ref}', que no está en la ficha de hechos ni en las simulaciones")
    if weightless:
        problems.append("el episodio termina con la gravedad apagada (falta gravity_on)")
    if words is not None and not (words[0] <= sb.words() <= words[1]):
        problems.append(f"el diálogo tiene {sb.words()} palabras; debe tener entre {words[0]} y {words[1]}")
    return problems


def staging_schema(lib: Library, cast: list[str]) -> dict:
    """The JSON schema Claude answers the staging with. Ids are enums of what is registered, so
    the answer cannot name anything else; `line` points at a line of the approved script instead
    of repeating its text."""
    o, a, e = llm.obj, llm.arr, llm.enum
    anchors = sorted({k for s in lib.sets.values() for k in s["anchors"]})
    prop_anchors = sorted({k for s in lib.sets.values() for k in s["prop_anchors"]})
    params = {"type": "object", "additionalProperties": False, "properties": {
        "label": llm.STR, "scale": llm.NUM, "color": llm.STR, "angle": llm.NUM, "length": llm.NUM,
        "values": a(llm.NUM), "marks": a(llm.STR)}}
    beat = o({
        "line": llm.INT, "seconds": llm.NUM, "actor": e(["", *cast]),
        "emotion": e(lib.emotions), "action": e(lib.actions),
        "walk_to": e(["", *anchors]), "look_at": llm.STR,
        "camera": e(lib.cameras), "camera_target": llm.STR,
        "effects": a(e(lib.effects)),
        "reactions": a(o({"character": e(cast), "action": e(lib.actions), "emotion": e(lib.emotions)})),
        "science_event": llm.STR,
    })
    scene = o({
        "id": llm.STR, "set": e(lib.sets), "label": llm.STR,
        "cast": a(o({"character": e(cast), "at": e(anchors), "facing": e(["left", "right"])})),
        "props": a(o({"uid": llm.STR, "prop": e(lib.props), "at": e(prop_anchors), "params": params})),
        "beats": a(beat),
    })
    return o({"scenes": a(scene)})


def assemble(staging: dict, script: dict, episode_id: str, cast: list[str], sources: list[dict],
             target_seconds: int) -> dict:
    """The full storyboard document: the staging Claude wrote, with each line's speaker, text and
    supports copied from the script (so the words on screen are exactly the ones that were checked)."""
    lines = script["lines"]
    scenes = []
    for scene in staging.get("scenes", []):
        beats = []
        for b in scene.get("beats", []):
            b = dict(b)
            index = b.pop("line", -1)
            line = lines[index] if isinstance(index, int) and 0 <= index < len(lines) else None
            if line:
                b.update(speaker=line["speaker"], text=line["text"], supports=list(line.get("supports", [])),
                         seconds=0.0, actor="")
            else:
                b.update(speaker="", text="", supports=[])
            beats.append(b)
        props = [{**p, "params": {k: v for k, v in (p.get("params") or {}).items() if v not in (None, "", [])}}
                 for p in scene.get("props", [])]
        scenes.append({**scene, "props": props, "beats": beats})
    return {"schema_version": SCHEMA_VERSION, "episode_id": episode_id, "title": script["title"], "format": "short",
            "target_seconds": target_seconds, "characters": cast,
            "sources": [{"id": s["id"], "url": s["url"], "title": s.get("title", "")} for s in sources],
            "scenes": scenes}


def lines_in_order(staging: dict, total: int) -> list[str]:
    """Problems with how the staging uses the script's lines: each exactly once, in order."""
    used = [b.get("line") for s in staging.get("scenes", []) for b in s.get("beats", [])
            if isinstance(b.get("line"), int) and b["line"] >= 0]
    if used != list(range(total)):
        return [f"las líneas del guion deben aparecer todas, una vez y en orden (0 a {total - 1}); llegaron {used}"]
    return []
