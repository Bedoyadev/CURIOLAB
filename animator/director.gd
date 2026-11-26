extends Node2D
# El director: lee el plan de UNA escena (JSON compilado y validado por backend/animation), monta
# el escenario, los personajes y los objetos, y reproduce su línea de tiempo cuadro a cuadro.
#
#   godot --path animator --write-movie escena.avi --fixed-fps 30 -- --plan=plan.json --result=r.json
#
# No ejecuta código que venga del plan: el plan solo nombra recursos registrados en
# library/manifest.json (acciones, escenarios, objetos, cámaras, efectos). Un nombre que no esté
# registrado detiene el render con error, sin dibujar nada.
#
# El tiempo es el número de cuadro entre los cuadros por segundo, no el reloj: el mismo plan da
# siempre el mismo video.

const Rig := preload("res://core/character_rig.gd")
const CameraRig := preload("res://core/camera_rig.gd")
const Overlay := preload("res://core/overlay.gd")

var plan: Dictionary = {}
var manifest: Dictionary = {}
var fps: float = 30.0
var frame: int = 0
var total_frames: int = 0
var result_path: String = ""
var errors: Array = []

var _events: Array = []
var _next: int = 0
var _actions: Dictionary = {}
var _chars: Dictionary = {}
var _props: Dictionary = {}
var _set: Node2D
var _cam: Camera2D
var _overlay: Node2D
var _font: Font
var _rng := RandomNumberGenerator.new()


func _ready() -> void:
	var plan_path: String = ""
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--plan="):
			plan_path = arg.substr(7)
		elif arg.begins_with("--result="):
			result_path = arg.substr(9)
	manifest = _read_json("res://library/manifest.json")
	plan = _read_json(plan_path)
	if plan.is_empty() or manifest.is_empty():
		errors.append("no se pudo leer el plan (%s) o el manifiesto" % plan_path)
		_finish(false)
		return
	fps = float(plan.get("fps", 30))
	total_frames = int(round(float(plan.get("duration", 1.0)) * fps))
	_rng.seed = int(plan.get("seed", 1))
	_font = _load_font(str(plan.get("font", "")))
	_build()
	if not errors.is_empty():
		_finish(false)
		return
	# "warmup": segundos que ya han pasado cuando empieza el video (eventos con t negativo). Sirve
	# para abrir una escena con todo flotando, tal como quedó en la anterior.
	frame = -int(round(float(plan.get("warmup", 0.0)) * fps))
	while frame < 0:
		_advance()


func _read_json(path: String) -> Dictionary:
	if path == "" or not FileAccess.file_exists(path):
		return {}
	var data: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	return data if data is Dictionary else {}


func _load_font(path: String) -> Font:
	if path != "" and FileAccess.file_exists(path):
		var file := FontFile.new()
		if file.load_dynamic_font(path) == OK:
			return file
	return ThemeDB.fallback_font


func _script_of(table: String, id: String) -> Script:
	var entry: Variant = manifest.get(table, {}).get(id)
	if entry == null:
		errors.append("%s no registrado: %s" % [table, id])
		return null
	var script: Script = load(str(entry["script"]))
	if script == null:
		errors.append("no se pudo cargar %s" % str(entry["script"]))
	return script


func _action(id: String) -> RefCounted:
	if not _actions.has(id):
		var script: Script = _script_of("actions", id)
		if script == null:
			return null
		_actions[id] = script.new()
	return _actions[id]


func _build() -> void:
	var set_script: Script = _script_of("sets", str(plan.get("set", "")))
	if set_script != null:
		_set = set_script.new()
		_set.font = _font
		add_child(_set)

	for item in plan.get("props", []):
		var kind: String = str(item.get("id", ""))
		var script: Script = _script_of("props", kind)
		if script == null:
			continue
		var prop: Node2D = script.new()
		prop.kind = kind
		prop.params = item.get("params", {})
		prop.loose = bool(manifest["props"][kind].get("loose", false))
		prop.font = _font
		prop.position = Vector2(float(item["x"]), float(item["y"]))
		prop.home = prop.position
		prop.born = float(item.get("at", 0.0))
		prop.visible = prop.born <= 0.0
		prop.z_index = 5
		var s: float = float(prop.params.get("scale", 1.0))
		prop.scale = Vector2(s, s)
		add_child(prop)
		_props[str(item.get("uid", kind))] = prop

	var idle: RefCounted = _action("idle")
	var index: int = 0
	for item in plan.get("characters", []):
		var definition: Dictionary = item.get("def", {})
		if definition.is_empty():
			errors.append("personaje sin definición: %s" % str(item.get("id", "")))
			continue
		if idle == null:
			break
		var rig: Node2D = Rig.new()
		rig.setup(definition, idle, fps, index)
		rig.position = Vector2(float(item["x"]), float(item["y"]))
		rig.facing = float(item.get("facing", 1.0))
		rig.z_index = 10
		add_child(rig)
		_chars[str(item["id"])] = rig
		index += 1

	_overlay = Overlay.new()
	add_child(_overlay)
	_cam = CameraRig.new()
	add_child(_cam)
	_cam.make_current()

	_events = plan.get("events", [])
	_events.sort_custom(func(a, b): return float(a["t"]) < float(b["t"]))
	# Todo lo que el plan nombra se comprueba antes de dibujar el primer cuadro.
	for e in _events:
		match str(e.get("type", "")):
			"action":
				_action(str(e["action"]))
				_need_char(e)
			"emotion":
				if not manifest["emotions"].has(str(e["emotion"])):
					errors.append("emoción no registrada: %s" % str(e["emotion"]))
				_need_char(e)
			"base":
				if str(e.get("action", "")) != "":
					_action(str(e["action"]))
				_need_char(e)
			"mouth", "look", "face":
				_need_char(e)
			"camera":
				if not manifest["cameras"].has(str(e["move"])):
					errors.append("cámara no registrada: %s" % str(e["move"]))
			"effect":
				if not manifest["effects"].has(str(e["effect"])):
					errors.append("efecto no registrado: %s" % str(e["effect"]))
			_:
				errors.append("tipo de evento desconocido: %s" % str(e.get("type", "")))


func _need_char(e: Dictionary) -> void:
	if not _chars.has(str(e.get("character", ""))):
		errors.append("el evento nombra un personaje que no está en la escena: %s" % str(e.get("character", "")))


func _point_of(id: String) -> Variant:
	if _chars.has(id):
		return _chars[id].head_point()
	if _props.has(id):
		return _props[id].global_position
	return null


func _fire(e: Dictionary, t: float) -> void:
	var who: Node2D = _chars.get(str(e.get("character", "")))
	match str(e["type"]):
		"action":
			who.play(str(e["action"]), _action(str(e["action"])), t, float(e.get("duration", 0.0)), e.get("params", {}))
		"base":
			who.set_base(_action(str(e["action"])) if str(e.get("action", "")) != "" else null, t)
		"emotion":
			who.set_emotion(str(e["emotion"]), t)
		"mouth":
			who.speak(e.get("frames", []), t)
		"look":
			var target: String = str(e.get("target", ""))
			who.look_target = _chars.get(target, _props.get(target))
		"face":
			who.facing = float(e.get("dir", 1.0))
		"camera":
			var target: String = str(e.get("target", ""))
			var point: Variant = _point_of(target)
			if e.has("point"):
				point = Vector2(float(e["point"][0]), float(e["point"][1]))
			var getter := Callable()
			if point != null and target != "":
				getter = func(): return _point_of(target)
			_cam.move(str(e["move"]), t, float(e.get("duration", 1.0)), point, getter, e.get("params", {}))
		"effect":
			match str(e["effect"]):
				"gravity_off":
					for prop in _props.values():
						prop.release(_rng)
				"gravity_on":
					for prop in _props.values():
						prop.drop()
				"flash":
					_overlay.flash_at = t
				"dust":
					_overlay.dust_from = t
					_overlay.dust_until = t + float(e.get("duration", 3.0))


func _process(_delta: float) -> void:
	if not errors.is_empty():
		return
	_advance()
	# Un cuadro de margen: el backend recorta al número exacto.
	if frame > total_frames + 1:
		_finish(true)


func _advance() -> void:
	var t: float = frame / fps
	var dt: float = 1.0 / fps
	while _next < _events.size() and float(_events[_next]["t"]) <= t + 0.0001:
		_fire(_events[_next], t)
		_next += 1
	if _set != null and _set.has_method("step"):
		_set.step(dt, t)
	for prop in _props.values():
		if not prop.visible and t >= prop.born:
			prop.visible = true
		prop.step(dt, t)
	for rig in _chars.values():
		rig.update(t)
	_overlay.step(dt, t)
	_cam.update(t)
	frame += 1


func _finish(ok: bool) -> void:
	if result_path != "":
		var file := FileAccess.open(result_path, FileAccess.WRITE)
		if file != null:
			file.store_string(JSON.stringify({"ok": ok, "frames": frame, "expected": total_frames, "errors": errors}))
			file.close()
	for message in errors:
		push_error(message)
	get_tree().quit(0 if ok else 1)
