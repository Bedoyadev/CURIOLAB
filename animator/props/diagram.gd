extends "res://core/prop.gd"
# Elementos explicativos: se dibujan progresivamente desde que entran en escena (age()). El origen
# es su centro. Los números que muestran llegan en params desde el backend, que los calcula con
# fórmulas explícitas (backend/animation/simulations.py): aquí no se inventa ninguna cifra.
# ARTE PROVISIONAL.

const LINE := Color("#e8f1ff")
const HOT := Color("#ff6b6b")
const COOL := Color("#4cc9f0")
const WARM := Color("#ffd23f")


func _draw() -> void:
	match kind:
		"atomo":
			oval(Vector2.ZERO, 34, 34, HOT, 4.0)
			oval(Vector2(-10, -10), 12, 12, Color(1, 1, 1, 0.35))
			for k in 3:
				var tilt: float = k * PI / 3.0
				draw_set_transform(Vector2.ZERO, tilt, Vector2(1.0, 0.36))
				draw_arc(Vector2.ZERO, 150, 0, TAU, 48, LINE, 5.0, true)
				draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)
				var a: float = t * (2.4 + 0.5 * k) + k * 2.0
				var e: Vector2 = Vector2(cos(a) * 150.0, sin(a) * 54.0).rotated(tilt)
				oval(e, 14, 14, COOL, 3.0)
		"molecula_agua":
			var wob: float = 0.06 * sin(t * 5.0)
			var o := Vector2(0, -20)
			for side in [-1.0, 1.0]:
				var h: Vector2 = o + Vector2(side * sin(0.91 + wob), cos(0.91 + wob)) * 120.0
				draw_line(o, h, LINE, 12.0, true)
				oval(h, 40, 40, Color("#f4f6fb"), 4.0)
				label(h + Vector2(0, 14), "H", 38, INK)
			oval(o, 62, 62, HOT, 4.0)
			label(o + Vector2(0, 18), "O", 50, Color.WHITE)
		"flecha_fuerza":
			var grow: float = smoothstep(0.0, 1.0, age() / 0.5)
			var angle: float = deg_to_rad(float(params.get("angle", -90.0)))
			var tip: Vector2 = Vector2(cos(angle), sin(angle)) * float(params.get("length", 200.0)) * grow
			var side: Vector2 = tip.normalized().orthogonal() * 22.0
			draw_line(Vector2.ZERO, tip, HOT, 16.0, true)
			if grow > 0.2:
				draw_colored_polygon(PackedVector2Array([tip + tip.normalized() * 38.0, tip + side, tip - side]), HOT)
			label(tip * 0.5 + side * 2.6 + Vector2(0, 14), str(params.get("label", "")), 40, LINE)
		"particulas":
			for k in 26:
				var p := Vector2(150.0 * sin(t * (0.7 + 0.13 * k) + k * 1.9), 150.0 * cos(t * (0.9 + 0.11 * k) + k * 2.7))
				oval(p, 10, 10, COOL if k % 3 else WARM, 2.5)
		"regla":
			var w: float = 360.0 * smoothstep(0.0, 1.0, age() / 0.6)
			draw_line(Vector2(-w * 0.5, 0), Vector2(w * 0.5, 0), LINE, 6.0, true)
			for k in 9:
				var x: float = -w * 0.5 + w * k / 8.0
				draw_line(Vector2(x, -22 if k % 4 == 0 else -12), Vector2(x, 0), LINE, 4.0, true)
			label(Vector2(0, 62), str(params.get("label", "")), 44, WARM)
		"linea_tiempo":
			var marks: Array = params.get("marks", [])
			var w: float = 760.0
			draw_line(Vector2(-w * 0.5, 0), Vector2(-w * 0.5 + w * smoothstep(0.0, 1.0, age() / 1.2), 0), LINE, 6.0, true)
			for k in marks.size():
				if age() > 0.4 + 0.5 * k:
					var x: float = -w * 0.5 + w * (k + 0.5) / marks.size()
					oval(Vector2(x, 0), 14, 14, WARM, 3.0)
					label(Vector2(x, -34 if k % 2 == 0 else 70), str(marks[k]), 34, LINE)
		"grafico":
			var values: Array = params.get("values", [0, 1, 4, 9, 16])
			var w: float = 520.0
			var h: float = 340.0
			var origin := Vector2(-w * 0.5, h * 0.5)
			draw_line(origin, origin + Vector2(w, 0), LINE, 5.0, true)
			draw_line(origin, origin - Vector2(0, h), LINE, 5.0, true)
			var top: float = 0.0001
			for v in values:
				top = maxf(top, absf(float(v)))
			var shown: float = (values.size() - 1) * smoothstep(0.0, 1.0, age() / 1.6)
			var pts := PackedVector2Array()
			for k in values.size():
				if k <= shown + 0.001:
					pts.append(origin + Vector2(w * k / maxf(1.0, values.size() - 1.0), -h * float(values[k]) / top))
			if pts.size() >= 2:
				draw_polyline(pts, HOT, 8.0, true)
			if pts.size() >= 1:
				oval(pts[pts.size() - 1], 12, 12, WARM, 3.0)
			label(Vector2(0, h * 0.5 + 60), str(params.get("label", "")), 38, LINE)
		"sim_tangente":
			_sim_tangente()
		_:
			oval(Vector2.ZERO, 40, 40, Color("#ff00ff"), 4.0)


# Sin gravedad, lo que estaba apoyado en el suelo sigue en línea recta (primera ley de Newton)
# mientras el suelo, que gira con la Tierra, se curva bajo él. params (del backend):
#   seconds: cuánto dura la falta de gravedad · accel: aceleración centrípeta en m/s² ·
#   place: dónde (texto) · play_seconds: en cuánto tiempo de pantalla se cuentan esos segundos
# El dibujo exagera la curva para que se vea; la cifra de separación es la del modelo.
func _sim_tangente() -> void:
	var seconds: float = float(params.get("seconds", 5.0))
	var accel: float = float(params.get("accel", 0.0339))
	var play: float = maxf(1.0, float(params.get("play_seconds", seconds)))
	var run: float = clampf((age() - 0.8) / play, 0.0, 1.0) * seconds   # tiempo simulado sin gravedad
	var after: float = maxf(0.0, age() - 0.8 - play)                    # la gravedad ya volvió
	var radius: float = 620.0
	var center := Vector2(0, radius + 140.0)
	var theta: float = 0.11 * run
	# La Tierra y su giro (marcas sobre la superficie).
	draw_arc(center, radius, -PI * 0.5 - 0.95, -PI * 0.5 + 0.95, 64, COOL, 10.0, true)
	for k in range(-6, 8):
		var a: float = -PI * 0.5 + k * 0.14 + fmod(0.11 * run, 0.14)
		var s: Vector2 = center + Vector2(cos(a), sin(a)) * radius
		draw_line(s, center + Vector2(cos(a), sin(a)) * (radius - 22.0), COOL, 5.0, true)
	var ground: Vector2 = center + Vector2(sin(theta), -cos(theta)) * radius
	var start: Vector2 = center + Vector2(0, -radius)
	var straight: Vector2 = start + Vector2(radius * theta, 0)
	# Al volver la gravedad, el objeto cae de vuelta al suelo.
	var obj: Vector2 = straight.lerp(ground, smoothstep(0.0, 1.0, after / 0.45))
	dashed(start, start + Vector2(radius * 0.11 * seconds + 40.0, 0), WARM, 5.0)
	# La casilla del suelo de la que partió, y el objeto.
	draw_set_transform(ground, theta, Vector2.ONE)
	shape([Vector2(-34, 0), Vector2(34, 0), Vector2(34, -12), Vector2(-34, -12)], Color("#58b368"), 3.0)
	draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)
	oval(obj + Vector2(0, -22), 22, 22, HOT, 4.0)
	if run > 0.3 and after < 0.3:
		draw_line(obj + Vector2(0, 2), ground + Vector2(0, -14), LINE, 4.0, true)
	var gap: float = 0.5 * accel * run * run
	label(Vector2(0, -330), "Sin gravedad: %.1f s" % run if after <= 0.0 else "La gravedad vuelve", 46, LINE)
	label(Vector2(0, -262), "separación del suelo ≈ %.2f m" % gap, 46, WARM)
	label(Vector2(0, 410), str(params.get("place", "")), 34, COOL)
	label(Vector2(0, 460), "Dibujo no a escala", 30, Color(0.91, 0.95, 1.0, 0.6))
