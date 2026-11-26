extends "res://core/prop.gd"
# Cuerpos celestes. El origen es su centro. params: {"scale": tamaño relativo, "color": "#rrggbb"}.
# Son dibujos esquemáticos: ni los tamaños ni las distancias entre ellos están a escala.
# ARTE PROVISIONAL.


func _draw() -> void:
	match kind:
		"tierra":
			var r: float = 150.0
			oval(Vector2.ZERO, r + 12, r + 12, Color(0.45, 0.75, 1.0, 0.25))
			oval(Vector2.ZERO, r, r, Color("#2a7fd4"), 5.0)
			# Continentes como manchas sobre una esfera que gira: su ancho se estrecha hacia el borde.
			var lands := [[0.0, -0.35, 0.34, 0.22], [1.3, 0.25, 0.3, 0.3], [2.6, -0.1, 0.4, 0.18], [3.9, 0.4, 0.26, 0.2], [5.1, -0.5, 0.3, 0.16]]
			for land in lands:
				var lon: float = float(land[0]) + t * 0.5
				var depth: float = cos(lon)
				if depth > 0.05:
					var lat: float = float(land[1])
					var edge: float = sqrt(maxf(0.0, 1.0 - lat * lat))
					oval(Vector2(sin(lon) * r * edge, lat * r), float(land[2]) * r * depth, float(land[3]) * r, Color("#58b368"))
			draw_arc(Vector2.ZERO, r, 0, TAU, 48, INK, 5.0, true)
		"luna":
			var r: float = 70.0
			oval(Vector2.ZERO, r, r, Color("#c9ccd6"), 4.0)
			for crater in [[-22, -18, 16], [20, 10, 12], [-6, 30, 9], [28, -30, 8]]:
				oval(Vector2(crater[0], crater[1]), crater[2], crater[2], Color("#a4a8b6"))
		"sol":
			var r: float = 120.0
			for k in 12:
				var a: float = TAU * k / 12.0 + t * 0.25
				var grow: float = 1.0 + 0.12 * sin(t * 2.0 + k)
				draw_line(Vector2(cos(a), sin(a)) * (r + 14), Vector2(cos(a), sin(a)) * (r + 62 * grow), Color("#ffb703"), 14.0, true)
			oval(Vector2.ZERO, r + 20, r + 20, Color(1.0, 0.8, 0.2, 0.3))
			oval(Vector2.ZERO, r, r, Color("#ffd23f"), 5.0)
		"planeta":
			var r: float = 90.0
			var color := Color(str(params.get("color", "#e07a5f")))
			draw_arc(Vector2.ZERO, r * 1.7, PI, TAU, 32, Color("#f2cc8f"), 12.0, true)
			oval(Vector2.ZERO, r, r, color, 5.0)
			oval(Vector2(-r * 0.2, -r * 0.3), r * 0.5, r * 0.12, color.lightened(0.2))
			draw_set_transform(Vector2.ZERO, 0.0, Vector2(1.0, 0.28))
			draw_arc(Vector2.ZERO, r * 1.7, 0, PI, 32, Color("#f2cc8f"), 40.0, true)
			draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)
		_:
			oval(Vector2.ZERO, 40, 40, Color("#ff00ff"), 4.0)
