extends Node2D
# Base de un objeto de escena. Cada script de props/ extiende este y dibuja, en _draw(), los
# objetos ("kind") que declara en library/manifest.json. Los objetos sueltos ("loose") responden a
# los efectos de gravedad: se separan despacio de su sitio y vuelven a caer.

# Aceleración de caída en pantalla (px/s²): dramatizada, no a escala.
const FALL := 2600.0
const INK := Color("#15161c")

var kind: String = ""
var params: Dictionary = {}
var loose: bool = false
var font: Font
var t: float = 0.0          # segundos de escena
var born: float = 0.0       # cuándo entró: los diagramas se dibujan desde aquí
var home: Vector2 = Vector2.ZERO
var mode: String = "rest"   # rest | float | fall
var vel: Vector2 = Vector2.ZERO
var spin: float = 0.0


func age() -> float:
	return maxf(0.0, t - born)


func release(rng: RandomNumberGenerator) -> void:
	if not loose:
		return
	mode = "float"
	# Sin peso nada sale disparado: una deriva lenta hacia arriba y un giro perezoso.
	vel = Vector2(rng.randf_range(-24.0, 24.0), rng.randf_range(-52.0, -22.0))
	spin = rng.randf_range(-0.8, 0.8)
	z_index = 15


func drop() -> void:
	if mode == "float":
		mode = "fall"


func step(dt: float, now: float) -> void:
	t = now
	if mode == "float":
		position += vel * dt
		rotation += spin * dt
		if position.x < 70.0 or position.x > 1010.0:
			vel.x = -vel.x
			position.x = clampf(position.x, 70.0, 1010.0)
		if position.y < 300.0:
			vel.y = absf(vel.y) * 0.5
	elif mode == "fall":
		vel.y += FALL * dt
		position += vel * dt
		rotation = lerp_angle(rotation, 0.0, minf(1.0, 7.0 * dt))
		if position.y >= home.y:
			position.y = home.y
			if vel.y > 320.0:
				vel = Vector2(vel.x * 0.4, -vel.y * 0.3)
			else:
				mode = "rest"
				vel = Vector2.ZERO
				rotation = 0.0
				z_index = 5
	queue_redraw()


# ---------------------------------------------------------------- utilidades de dibujo

func oval(center: Vector2, rx: float, ry: float, color: Color, outline: float = 0.0, ink: Color = INK) -> void:
	if rx < 1.0 or ry < 1.0:
		return
	var pts := PackedVector2Array()
	for k in 32:
		var a: float = TAU * k / 32.0
		pts.append(center + Vector2(cos(a) * rx, sin(a) * ry))
	draw_colored_polygon(pts, color)
	if outline > 0.0:
		pts.append(pts[0])
		draw_polyline(pts, ink, outline, true)


func shape(points: Array, color: Color, outline: float = 4.0) -> void:
	var pts := PackedVector2Array(points)
	draw_colored_polygon(pts, color)
	if outline > 0.0:
		pts.append(pts[0])
		draw_polyline(pts, INK, outline, true)


func label(pos: Vector2, text: String, size: int, color: Color, centered: bool = true) -> void:
	if font == null or text == "":
		return
	var width: float = font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, size).x
	var at: Vector2 = pos - Vector2(width * 0.5, 0) if centered else pos
	draw_string(font, at, text, HORIZONTAL_ALIGNMENT_LEFT, -1, size, color)


func dashed(a: Vector2, b: Vector2, color: Color, width: float, dash: float = 18.0) -> void:
	var length: float = a.distance_to(b)
	var dir: Vector2 = (b - a).normalized()
	var d: float = 0.0
	while d < length:
		draw_line(a + dir * d, a + dir * minf(d + dash * 0.55, length), color, width, true)
		d += dash
