extends Node2D
# Un personaje 2D: se construye desde su definición (library/characters/<id>.json) y se dibuja por
# capas a partir de una pose. La apariencia es fija por personaje; lo que cambia cuadro a cuadro es
# la pose, que sale de mezclar: reposo + acción en curso + emoción + mirada + parpadeo + boca.
#
# ARTE PROVISIONAL: las piezas son formas vectoriales dibujadas por código. Cuando haya diseño
# final, cada pieza se sustituye por su sprite sobre los mismos puntos de articulación; los canales
# de la pose (el contrato con las acciones) no cambian.

const CHANNELS := {
	"y": 0.0, "rot": 0.0, "lean": 0.0, "bob": 0.0,
	"head_rot": 0.0, "head_x": 0.0, "head_y": 0.0,
	"arm_l": 0.12, "arm_r": 0.12, "elbow_l": 0.1, "elbow_r": 0.1,
	"leg_l": 0.0, "leg_r": 0.0,
	"look_x": 0.0, "look_y": 0.0, "brow": 0.0, "brow_tilt": 0.0, "eye_open": 1.0,
	"mouth_curve": 0.25, "mouth_open": 0.0,
}
# La cara de cada emoción. Una acción puede imponer la suya encima.
const EMOTIONS := {
	"neutral": {},
	"happy": {"brow": 0.4, "mouth_curve": 1.0, "eye_open": 0.9},
	"surprised": {"brow": 1.0, "eye_open": 1.3, "mouth_curve": 0.0, "mouth_open": 4.0},
	"confused": {"brow": 0.3, "brow_tilt": 0.6, "mouth_curve": -0.35, "head_rot": 0.12},
	"thinking": {"brow": 0.25, "brow_tilt": -0.35, "look_x": 0.5, "look_y": -0.7, "mouth_curve": 0.0},
	"worried": {"brow": -0.2, "brow_tilt": -0.7, "mouth_curve": -0.7, "eye_open": 1.12},
}
const BLEND_SECONDS := 0.22
const OUTLINE := Color("#15161c")

var def: Dictionary = {}
var H: float = 540.0
var facing: float = 1.0
var emotion: String = "neutral"
var action_id: String = "idle"
var pose: Dictionary = CHANNELS.duplicate()
var look_target: Node2D = null

var _idle: RefCounted
# Capa de fondo bajo la acción en curso: null en el suelo; "float" mientras no hay gravedad, para
# que el personaje siga flotando aunque hable o señale.
var _base: RefCounted = null
var _base_t0: float = 0.0
var _action: RefCounted = null
var _action_t0: float = 0.0
var _action_dur: float = 0.0
var _action_params: Dictionary = {}
var _from: Dictionary = CHANNELS.duplicate()
var _blend_t0: float = -10.0
var _mouth: Array = []
var _mouth_t0: float = 0.0
var _fps: float = 30.0
var _phase: float = 0.0
var _col: Dictionary = {}


func setup(definition: Dictionary, idle_action: RefCounted, fps: float, index: int) -> void:
	def = definition
	_idle = idle_action
	_fps = fps
	# Cada personaje respira y parpadea a su propio compás.
	_phase = 1.7 * index
	var look: Dictionary = def.get("appearance", {})
	H = float(look.get("height", 540))
	for key in ["skin", "hair", "coat", "shirt", "pants", "shoes", "accent"]:
		var value: String = str(look.get(key, ""))
		_col[key] = Color(value) if value != "" else Color(0, 0, 0, 0)


func play(id: String, action: RefCounted, t: float, duration: float, params: Dictionary) -> void:
	_begin_blend(t)
	action_id = id
	_action = action
	_action_t0 = t
	_action_dur = duration
	_action_params = params.duplicate()
	action.start(self, _action_params)


func set_base(action: RefCounted, t: float) -> void:
	_begin_blend(t)
	_base = action
	_base_t0 = t


func speak(frames: Array, t: float) -> void:
	_mouth = frames
	_mouth_t0 = t


func set_emotion(id: String, t: float) -> void:
	if id != emotion:
		_begin_blend(t)
		emotion = id


func head_point() -> Vector2:
	return global_position + Vector2(0.0, float(pose["y"]) - 0.77 * H)


func _begin_blend(t: float) -> void:
	_from = pose.duplicate()
	_blend_t0 = t


func update(t: float) -> void:
	var target: Dictionary = CHANNELS.duplicate()
	var set_by_action: Dictionary = {}
	_merge(target, _idle.pose(t + _phase, 0.0, {}, self))
	if _base != null:
		_merge(target, _base.pose(t - _base_t0, 0.0, {}, self))
	_merge(target, EMOTIONS.get(emotion, {}))
	if _action != null:
		var lt: float = t - _action_t0
		if _action_dur > 0.0 and lt > _action_dur:
			_begin_blend(t)
			_action = null
			action_id = "idle"
		else:
			set_by_action = _action.pose(lt, _action_dur, _action_params, self)
			_merge(target, set_by_action)
	if set_by_action.has("_x"):
		position.x = float(set_by_action["_x"])
	if look_target != null and not set_by_action.has("look_x") and emotion != "thinking":
		var dx: float = (look_target.global_position.x - global_position.x) * facing
		target["look_x"] = clampf(dx / 300.0, -1.0, 1.0)
	var w: float = smoothstep(0.0, 1.0, clampf((t - _blend_t0) / BLEND_SECONDS, 0.0, 1.0))
	for key in CHANNELS:
		pose[key] = lerpf(float(_from[key]), float(target[key]), w)
	# El parpadeo y la boca no se suavizan: tienen que caer en su cuadro.
	var beat: float = fmod(t + _phase * 1.3, 3.4)
	if beat < 0.13:
		pose["eye_open"] = float(pose["eye_open"]) * (0.08 + 0.92 * absf(beat - 0.065) / 0.065)
	var i: int = int(round((t - _mouth_t0) * _fps))
	if i >= 0 and i < _mouth.size():
		var m: float = float(_mouth[i])
		pose["mouth_open"] = m
		pose["head_y"] = float(pose["head_y"]) - m * 0.004 * H
	scale.x = facing
	queue_redraw()


func _merge(into: Dictionary, values: Dictionary) -> void:
	for key in values:
		if CHANNELS.has(key):
			into[key] = values[key]


# ---------------------------------------------------------------- dibujo

func _limb(a: Vector2, b: Vector2, width: float, color: Color) -> void:
	draw_line(a, b, OUTLINE, width + 7.0, true)
	draw_circle(a, (width + 7.0) * 0.5, OUTLINE)
	draw_circle(b, (width + 7.0) * 0.5, OUTLINE)
	draw_line(a, b, color, width, true)
	draw_circle(a, width * 0.5, color)
	draw_circle(b, width * 0.5, color)


func _ellipse(center: Vector2, rx: float, ry: float, color: Color, outline: float = 0.0) -> void:
	if rx < 1.0 or ry < 1.0:
		return
	var pts := PackedVector2Array()
	for k in 28:
		var a: float = TAU * k / 28.0
		pts.append(center + Vector2(cos(a) * rx, sin(a) * ry))
	draw_colored_polygon(pts, color)
	if outline > 0.0:
		pts.append(pts[0])
		draw_polyline(pts, OUTLINE, outline, true)


func _arm(shoulder: Vector2, side: float, angle: float, elbow: float, sleeve: Color) -> void:
	var upper: float = 0.15 * H
	var d1 := Vector2(side * sin(angle), cos(angle))
	var mid: Vector2 = shoulder + d1 * upper
	var d2 := Vector2(side * sin(angle + elbow), cos(angle + elbow))
	var hand: Vector2 = mid + d2 * upper
	_limb(shoulder, mid, 0.058 * H, sleeve)
	_limb(mid, hand, 0.052 * H, sleeve)
	var palm: Vector2 = hand + d2 * 0.016 * H
	_ellipse(palm + d2.orthogonal() * side * -0.03 * H, 0.016 * H, 0.016 * H, _col["skin"], 3.0)
	_ellipse(palm, 0.041 * H, 0.041 * H, _col["skin"], 3.5)


func _draw() -> void:
	var p: Dictionary = pose
	var lift: float = float(p["y"])
	# Sombra en el suelo: se encoge cuando el personaje se eleva.
	var shade: float = clampf(1.0 + lift / (0.6 * H), 0.35, 1.0)
	draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)
	_ellipse(Vector2(0, 6), 0.2 * H * shade, 0.035 * H * shade, Color(0, 0, 0, 0.22 * shade))

	draw_set_transform(Vector2(0, lift), float(p["rot"]), Vector2.ONE)
	var leg: float = 0.26 * H
	var hip_y: float = -leg
	var bob: float = float(p["bob"])
	# Piernas y zapatos.
	for side in [-1.0, 1.0]:
		var a: float = float(p["leg_l"] if side < 0.0 else p["leg_r"])
		var hip := Vector2(side * 0.07 * H, hip_y + bob)
		var foot: Vector2 = hip + Vector2(sin(a), cos(a)) * (leg - 0.03 * H - bob * 0.5)
		_limb(hip, foot, 0.075 * H, _col["pants"])
		_ellipse(foot + Vector2(0.03 * H, 0.012 * H), 0.07 * H, 0.036 * H, _col["shoes"], 3.5)
		draw_line(foot + Vector2(-0.03 * H, 0.04 * H), foot + Vector2(0.09 * H, 0.04 * H), OUTLINE, 5.0, true)

	# Torso: gira (lean) alrededor de la cadera.
	var torso := Transform2D(float(p["lean"]), Vector2(0, hip_y + bob))
	var th: float = 0.34 * H
	var has_coat: bool = _col["coat"].a > 0.0
	var body_col: Color = _col["coat"] if has_coat else _col["shirt"]
	var hem: float = 0.07 * H if has_coat else 0.02 * H
	var body := PackedVector2Array([
		torso * Vector2(-0.155 * H, hem), torso * Vector2(0.155 * H, hem),
		torso * Vector2(0.14 * H, -th + 0.05 * H), torso * Vector2(0.09 * H, -th),
		torso * Vector2(-0.09 * H, -th), torso * Vector2(-0.14 * H, -th + 0.05 * H)])
	draw_colored_polygon(body, body_col)
	if has_coat:
		draw_colored_polygon(PackedVector2Array([
			torso * Vector2(-0.05 * H, -th), torso * Vector2(0.05 * H, -th), torso * Vector2(0, -th + 0.17 * H)]), _col["shirt"])
		draw_line(torso * Vector2(0, -th + 0.17 * H), torso * Vector2(0, hem), OUTLINE, 3.0, true)
		_ellipse(torso * Vector2(0.085 * H, -0.2 * H), 0.012 * H, 0.012 * H, _col["accent"])
	# Volumen: una franja de sombra en el lado contrario a la luz de la ventana.
	draw_colored_polygon(PackedVector2Array([
		torso * Vector2(0.07 * H, hem), torso * Vector2(0.155 * H, hem),
		torso * Vector2(0.14 * H, -th + 0.05 * H), torso * Vector2(0.09 * H, -th)]), Color(0, 0, 0, 0.09))
	if has_coat:
		for k in 2:
			_ellipse(torso * Vector2(-0.022 * H, -0.02 * H - 0.07 * H * k), 0.009 * H, 0.009 * H, OUTLINE)
		draw_line(torso * Vector2(-0.12 * H, -0.05 * H), torso * Vector2(-0.06 * H, -0.05 * H), OUTLINE, 3.0, true)
	else:
		# Cuello y bajo de la sudadera.
		draw_arc(torso * Vector2(0, -th), 0.055 * H, 0.15, PI - 0.15, 12, _col["shirt"].darkened(0.3), 5.0, true)
		draw_line(torso * Vector2(-0.15 * H, -0.01 * H), torso * Vector2(0.15 * H, -0.01 * H), _col["shirt"].darkened(0.25), 6.0, true)
	body.append(body[0])
	draw_polyline(body, OUTLINE, 4.0, true)

	# Cabeza.
	var R: float = 0.19 * H
	var neck: Vector2 = torso * Vector2(0, -th)
	var head: Vector2 = neck + Vector2(float(p["head_x"]), float(p["head_y"]) - R * 0.86)
	draw_line(neck + Vector2(0, 0.01 * H), head, _col["skin"].darkened(0.12), 0.07 * H, true)
	draw_set_transform_matrix(Transform2D(float(p["rot"]), Vector2(0, lift)) * Transform2D(float(p["head_rot"]), head))
	var style: String = str(def.get("appearance", {}).get("hair_style", "short"))
	if style == "bun":
		_ellipse(Vector2(0, -R * 1.12), R * 0.42, R * 0.4, _col["hair"], 4.0)
	_ellipse(Vector2.ZERO, R, R * 1.04, _col["skin"], 4.0)
	_ellipse(Vector2(-R * 0.98, R * 0.06), R * 0.12, R * 0.17, _col["skin"], 3.0)
	_ellipse(Vector2(R * 0.99, R * 0.06), R * 0.09, R * 0.15, _col["skin"].darkened(0.08), 3.0)
	# Pelo: casquete sobre la mitad superior de la cabeza.
	var cap := PackedVector2Array()
	for k in 17:
		var a: float = PI + PI * k / 16.0
		cap.append(Vector2(cos(a) * R * 1.05, sin(a) * R * 1.1 - R * 0.02))
	if style == "bun":
		cap.append(Vector2(R * 1.02, R * 0.18))
		cap.append(Vector2(R * 0.55, -R * 0.56))
		cap.append(Vector2(-R * 0.1, -R * 0.7))
		cap.append(Vector2(-R * 0.75, -R * 0.52))
	else:
		cap.append(Vector2(R * 0.6, -R * 0.6))
		cap.append(Vector2(R * 0.1, -R * 0.76))
		cap.append(Vector2(-R * 0.45, -R * 0.58))
		cap.append(Vector2(-R * 0.84, -R * 0.46))
	draw_colored_polygon(cap, _col["hair"])
	cap.append(cap[0])
	draw_polyline(cap, OUTLINE, 3.5, true)
	draw_arc(Vector2(-R * 0.1, -R * 0.2), R * 0.72, PI + 0.5, PI + 1.25, 10, _col["hair"].lightened(0.3), 7.0, true)
	_face(R, p)

	# Brazos, por delante del torso para que una mano pueda llegar a la cara.
	draw_set_transform(Vector2(0, lift), float(p["rot"]), Vector2.ONE)
	_arm(torso * Vector2(-0.14 * H, -th + 0.045 * H), -1.0, float(p["arm_l"]), float(p["elbow_l"]), body_col)
	_arm(torso * Vector2(0.14 * H, -th + 0.045 * H), 1.0, float(p["arm_r"]), float(p["elbow_r"]), body_col)


func _face(R: float, p: Dictionary) -> void:
	var lx: float = float(p["look_x"])
	var ly: float = float(p["look_y"])
	# Los rasgos se corren un poco hacia donde mira: da volumen a una cabeza plana.
	var shift := Vector2(R * 0.16 + lx * R * 0.07, ly * R * 0.05)
	var open: float = float(p["eye_open"])
	var brow: float = float(p["brow"])
	var tilt: float = float(p["brow_tilt"])
	for side in [-1.0, 1.0]:
		var c: Vector2 = shift + Vector2(side * R * 0.4, -R * 0.06)
		if open < 0.22:
			draw_line(c - Vector2(R * 0.2, 0), c + Vector2(R * 0.2, 0), OUTLINE, 5.0, true)
		else:
			_ellipse(c, R * 0.22, R * 0.26 * open, Color.WHITE, 3.5)
			_ellipse(c + Vector2(lx * R * 0.09, ly * R * 0.1), R * 0.11, minf(R * 0.11, R * 0.24 * open), OUTLINE)
			_ellipse(c + Vector2(lx * R * 0.09 + R * 0.035, ly * R * 0.1 - R * 0.04), R * 0.03, R * 0.03, Color.WHITE)
		# Ceja: sube con "brow"; "brow_tilt" inclina una hacia dentro y la otra hacia fuera.
		var by: float = -R * 0.42 - brow * R * 0.13
		var slope: float = (tilt * side) * R * 0.1
		draw_line(c + Vector2(-R * 0.2, by + R * 0.06 + slope), c + Vector2(R * 0.2, by + R * 0.06 - slope), OUTLINE, 7.0, true)
	draw_arc(shift + Vector2(R * 0.02, R * 0.2), R * 0.08, 0.2, PI - 0.6, 8, _col["skin"].darkened(0.35), 4.0, true)
	if bool(def.get("appearance", {}).get("glasses", false)):
		for side in [-1.0, 1.0]:
			var g: Vector2 = shift + Vector2(side * R * 0.4, -R * 0.06)
			draw_arc(g, R * 0.31, 0.0, TAU, 28, OUTLINE, 4.5, true)
		draw_line(shift + Vector2(-R * 0.09, -R * 0.08), shift + Vector2(R * 0.09, -R * 0.08), OUTLINE, 4.5, true)
	# Boca. 0 cerrada (curva según el ánimo) · 1 entreabierta (consonantes) · 2 «e» · 3 «a» ·
	# 4 «o/u» (redonda) · 5 «i» (ancha y baja). Las formas llegan de la pista de voz (lipsync.py).
	var m: int = clampi(int(round(float(p["mouth_open"]))), 0, 5)
	var mc: Vector2 = shift * 0.8 + Vector2(0, R * 0.5)
	var curve: float = float(p["mouth_curve"])
	if m <= 0:
		var line := PackedVector2Array()
		for k in 9:
			var u: float = -1.0 + 2.0 * k / 8.0
			line.append(mc + Vector2(u * R * 0.3, -curve * R * 0.13 * (u * u - 0.5)))
		draw_polyline(line, OUTLINE, 5.5, true)
	else:
		var rx: float = R * [0.0, 0.17, 0.27, 0.25, 0.14, 0.3][m]
		var ry: float = R * [0.0, 0.07, 0.14, 0.25, 0.18, 0.085][m]
		var at: Vector2 = mc + Vector2(0, ry * 0.3)
		_ellipse(at, rx, ry, Color("#5b1a24"), 3.5)
		if m == 2 or m == 5:
			# Dientes de arriba: lo que distingue una «e» o una «i» de una boca simplemente abierta.
			draw_rect(Rect2(at.x - rx * 0.62, at.y - ry * 0.86, rx * 1.24, ry * 0.55), Color("#fbfbf5"))
		if m == 3 or m == 4:
			_ellipse(at + Vector2(0, ry * 0.55), rx * 0.6, ry * 0.38, Color("#e8707c"))
	# Mejillas.
	for side in [-1.0, 1.0]:
		_ellipse(shift * 0.6 + Vector2(side * R * 0.62, R * 0.3), R * 0.13, R * 0.085, Color(1.0, 0.45, 0.45, 0.28))
