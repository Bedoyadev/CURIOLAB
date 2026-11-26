"""From a validated storyboard and its recorded voices to what the renderer plays: one plan per
scene, in seconds, and the episode's timeline.

The storyboard has no times. Here each beat gets its length from the audio of its line (a silent
beat, from its `seconds`), beats follow one another with a short breath between them, and every
gesture, camera move and effect is placed at the start of its beat. So a scene lasts exactly what
its dialogue needs: no empty frames waiting for a clock, no line cut by a fixed duration.
"""
import hashlib
import json
from pathlib import Path

from animation.library import Library
from animation.storyboard import Scene, Storyboard

LEAD_IN = 0.35          # a scene opens, then someone speaks
BREATH = 0.28           # between beats
TAIL = 0.45             # after the last beat, before the cut
REACTION_SECONDS = 1.6
WALK_SPEED = 300.0      # px/s
FLOAT_DELAY = 0.35      # characters lose their footing just after the objects do
SIMULATION_ZOOM = 1.1
PLAN_VERSION = 1


WARMUP = 4.0            # how long things have been floating when a scene opens weightless


def _events_for_scene(scene: Scene, lib: Library, audio: dict[int, dict], fps: int,
                      weightless: bool = False) -> tuple[list[dict], list[dict], float]:
    """(events, beats' times, duration). audio: {beat index: {"duration", "mouth"}}."""
    stage = lib.sets[scene.set]
    on_stage = {m.character for m in scene.cast}
    position = {m.character: float(stage["anchors"][m.at][0]) for m in scene.cast}
    events: list[dict] = []
    # People in a conversation look at each other unless told otherwise.
    if len(scene.cast) == 2:
        a, b = scene.cast[0].character, scene.cast[1].character
        events += [{"t": 0.0, "type": "look", "character": a, "target": b}, {"t": 0.0, "type": "look", "character": b, "target": a}]
    if weightless:
        # The scene before left everything floating: this one opens the same way.
        events.append({"t": -WARMUP, "type": "effect", "effect": "gravity_off", "duration": 0.0})
        events += [{"t": -WARMUP, "type": "base", "character": cid, "action": "float"} for cid in on_stage]
    times, t = [], LEAD_IN
    for i, beat in enumerate(scene.beats):
        spoken = bool(beat.text.strip())
        length = float(audio[i]["duration"]) if spoken else float(beat.seconds)
        who = beat.who
        if who in on_stage:
            action = {"t": t, "type": "action", "character": who, "action": beat.action, "duration": length, "params": {}}
            if beat.action == "walk":
                to_x = float(stage["anchors"][beat.walk_to][0])
                action["params"] = {"to_x": to_x}
                action["duration"] = min(max(abs(to_x - position[who]) / WALK_SPEED, 0.6), max(length, 0.6))
                position[who] = to_x
            events.append(action)
            events.append({"t": t, "type": "emotion", "character": who, "emotion": beat.emotion})
            if beat.look_at:
                events.append({"t": t, "type": "look", "character": who, "target": beat.look_at})
            if spoken:
                events.append({"t": t, "type": "mouth", "character": who, "frames": audio[i]["mouth"]})
        if beat.camera != "static":
            camera = {"t": t, "type": "camera", "move": beat.camera, "duration": min(max(length, 0.5), 1.8), "params": {}}
            if beat.camera_target:
                camera["target"] = beat.camera_target
                if any(p.uid == beat.camera_target and lib.props[p.prop].get("simulation") for p in scene.props):
                    # A diagram is framed whole: closer than this its labels leave the picture.
                    camera["params"] = {"zoom": SIMULATION_ZOOM}
            if beat.camera == "shake":
                camera["duration"] = 0.5
            events.append(camera)
        for effect in beat.effects:
            events.append({"t": t, "type": "effect", "effect": effect, "duration": max(length, 2.5)})
            if effect in ("gravity_off", "gravity_on"):
                for cid in on_stage:
                    events.append({"t": t + (FLOAT_DELAY if effect == "gravity_off" else 0.0), "type": "base",
                                   "character": cid, "action": "float" if effect == "gravity_off" else ""})
        for r in beat.reactions:
            if r.character in on_stage:
                events.append({"t": t + 0.12, "type": "action", "character": r.character, "action": r.action,
                               "duration": min(REACTION_SECONDS, max(length, 0.8)), "params": {}})
                events.append({"t": t + 0.12, "type": "emotion", "character": r.character, "emotion": r.emotion})
        times.append({"beat": i, "start": round(t, 3), "end": round(t + length, 3), "spoken": spoken})
        t += length + BREATH
    duration = t - BREATH + TAIL
    # Whole frames: the scene's video and its place in the episode agree to the frame.
    duration = round(duration * fps) / fps
    for e in events:
        e["t"] = round(e["t"], 3)
        if "duration" in e:
            e["duration"] = round(e["duration"], 3)
    return events, times, duration


def compile_scene(scene: Scene, lib: Library, audio: dict[int, dict], simulations: dict[str, dict], seed: int,
                  font: Path | None = None, weightless: bool = False) -> tuple[dict, list[dict]]:
    """(plan for the Godot director, beats' times within the scene). weightless: gravity was
    already off when the scene before this one ended."""
    stage = lib.sets[scene.set]
    events, times, duration = _events_for_scene(scene, lib, audio, lib.fps, weightless)
    props = []
    for p in scene.props:
        x, y = stage["prop_anchors"][p.at]
        params = p.params.model_dump(exclude_none=True)
        sim = lib.props[p.prop].get("simulation")
        if sim:
            # A simulation's figures come from the engine's model, never from the storyboard.
            params.update(simulations[sim]["prop_params"])
            # The diagram plays over the whole scene, whatever the dialogue made it last.
            params["play_seconds"] = round(max(3.0, duration - 2.4), 2)
        props.append({"uid": p.uid, "id": p.prop, "x": x, "y": y, "params": params})
    plan = {
        "version": PLAN_VERSION, "fps": lib.fps, "scene": scene.id, "duration": duration, "seed": seed, "set": scene.set,
        "warmup": WARMUP if weightless else 0.0,
        "font": str(font) if font else "",
        "characters": [{"id": m.character, "def": lib.characters[m.character], "x": stage["anchors"][m.at][0],
                        "y": stage["anchors"][m.at][1], "facing": 1 if m.facing == "right" else -1} for m in scene.cast],
        "props": props, "events": events,
    }
    return plan, times


def plan_key(plan: dict, lib: Library) -> str:
    """Identity of a scene's render: same plan and same engine give the same video, so it is not
    drawn again."""
    body = json.dumps(plan, sort_keys=True, ensure_ascii=False) + lib.fingerprint
    return hashlib.sha1(body.encode()).hexdigest()[:16]


def compile_episode(sb: Storyboard, lib: Library, voices: dict[str, dict], simulations: dict[str, dict],
                    retakes: dict[str, int] | None = None, font: Path | None = None) -> dict:
    """Every scene's plan and the episode's timeline.

    voices: {"<scene index>:<beat index>": {"duration", "mouth", "words", "path", "speaker"}}.
    Returns {"scenes": [{"id", "plan", "key", "start", "duration", "label", "set"}],
             "lines": [{"speaker", "start", "path"}], "words": [...], "duration"}.
    """
    scenes, lines, words, at, weightless = [], [], [], 0.0, False
    for si, scene in enumerate(sb.scenes):
        audio = {bi: voices[f"{si}:{bi}"] for bi, beat in enumerate(scene.beats) if beat.text.strip()}
        seed = 1000 * (si + 1) + (retakes or {}).get(scene.id, 0)
        plan, times = compile_scene(scene, lib, audio, simulations, seed, font, weightless)
        for beat in scene.beats:
            for effect in beat.effects:
                weightless = {"gravity_off": True, "gravity_on": False}.get(effect, weightless)
        for beat_time in times:
            if not beat_time["spoken"]:
                continue
            voice = audio[beat_time["beat"]]
            start = at + beat_time["start"]
            lines.append({"speaker": voice["speaker"], "start": round(start, 3), "path": str(voice["path"]),
                          "duration": voice["duration"], "scene": si})
            shown = scene.beats[beat_time["beat"]].text.split()
            timed = voice["words"]
            for wi, w in enumerate(timed):
                # The caption shows the word as written in the script when the counts agree.
                text = shown[wi] if len(shown) == len(timed) else w["word"]
                words.append({"word": text, "start": round(start + w["start"], 3), "end": round(start + w["end"], 3),
                              "speaker": voice["speaker"], "scene": si, "line": len(lines) - 1})
        scenes.append({"id": scene.id, "plan": plan, "key": plan_key(plan, lib), "start": round(at, 3),
                       "duration": plan["duration"], "label": scene.label, "set": scene.set})
        at += plan["duration"]
    return {"scenes": scenes, "lines": lines, "words": words, "duration": round(at, 3)}
