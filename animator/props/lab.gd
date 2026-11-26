extends "res://core/prop.gd"
# Objetos de laboratorio. El origen es el punto de apoyo (abajo, al centro). ARTE PROVISIONAL.

const GLASS := Color(0.82, 0.93, 0.97, 0.75)


func _draw() -> void:
	match kind:
		"matraz":
			shape([Vector2(-14, -112), Vector2(14, -112), Vector2(14, -70), Vector2(48, -6), Vector2(40, 0),
				   Vector2(-40, 0), Vector2(-48, -6), Vector2(-14, -70)], GLASS)
			shape([Vector2(-27, -44), Vector2(27, -44), Vector2(46, -7), Vector2(40, -2), Vector2(-40, -2), Vector2(-46, -7)],
				  Color("#34d1bf"), 0.0)
			oval(Vector2(-8, -24 - 6.0 * sin(t * 3.0)), 5, 5, Color(1, 1, 1, 0.7))
			oval(Vector2(12, -34 - 5.0 * sin(t * 2.3 + 1.0)), 4, 4, Color(1, 1, 1, 0.7))
			draw_line(Vector2(-18, -112), Vector2(18, -112), INK, 6.0, true)
		"tubo_ensayo":
			shape([Vector2(-11, -104), Vector2(11, -104), Vector2(11, -12), Vector2(6, -2), Vector2(-6, -2), Vector2(-11, -12)], GLASS)
			shape([Vector2(-9, -56), Vector2(9, -56), Vector2(9, -13), Vector2(5, -4), Vector2(-5, -4), Vector2(-9, -13)],
				  Color("#ff6b6b"), 0.0)
			draw_line(Vector2(-15, -104), Vector2(15, -104), INK, 5.0, true)
		"vaso":
			shape([Vector2(-34, -84), Vector2(34, -84), Vector2(30, 0), Vector2(-30, 0)], GLASS)
			shape([Vector2(-32, -46), Vector2(32, -46), Vector2(29, -2), Vector2(-29, -2)], Color("#ffd23f"), 0.0)
			for k in 3:
				draw_line(Vector2(-33, -70 + 18 * k), Vector2(-20, -70 + 18 * k), INK, 2.5, true)
		"microscopio":
			shape([Vector2(-46, 0), Vector2(46, 0), Vector2(40, -16), Vector2(-40, -16)], Color("#3d4252"))
			draw_line(Vector2(24, -16), Vector2(24, -110), INK, 20.0, true)
			draw_line(Vector2(24, -16), Vector2(24, -110), Color("#5c6378"), 12.0, true)
			draw_line(Vector2(26, -108), Vector2(-14, -64), INK, 26.0, true)
			draw_line(Vector2(26, -108), Vector2(-14, -64), Color("#e9edf5"), 18.0, true)
			shape([Vector2(-34, -40), Vector2(10, -40), Vector2(10, -32), Vector2(-34, -32)], Color("#8891a8"), 3.0)
		"taza":
			draw_arc(Vector2(30, -34), 18, -PI * 0.5, PI * 0.5, 14, INK, 13.0, true)
			draw_arc(Vector2(30, -34), 18, -PI * 0.5, PI * 0.5, 14, Color("#ff8a3d"), 6.0, true)
			shape([Vector2(-30, -66), Vector2(30, -66), Vector2(25, 0), Vector2(-25, 0)], Color("#ff8a3d"))
			if mode == "rest":
				for k in 2:
					var sx: float = -9.0 + 18.0 * k
					var steam := PackedVector2Array()
					for j in 8:
						steam.append(Vector2(sx + 5.0 * sin(t * 2.0 + j * 0.9 + k), -74.0 - 7.0 * j))
					draw_polyline(steam, Color(1, 1, 1, 0.45), 4.0, true)
		"libro":
			shape([Vector2(-60, -30), Vector2(60, -30), Vector2(60, 0), Vector2(-60, 0)], Color("#3d5a80"))
			shape([Vector2(-52, -25), Vector2(57, -25), Vector2(57, -5), Vector2(-52, -5)], Color("#f4f1e8"), 2.0)
			draw_line(Vector2(-60, -30), Vector2(-60, 0), Color("#22344d"), 8.0)
		"lapiz":
			shape([Vector2(-52, -12), Vector2(34, -12), Vector2(34, 0), Vector2(-52, 0)], Color("#ffd23f"), 3.0)
			shape([Vector2(34, -12), Vector2(56, -6), Vector2(34, 0)], Color("#f0c39a"), 3.0)
			shape([Vector2(-62, -12), Vector2(-52, -12), Vector2(-52, 0), Vector2(-62, 0)], Color("#ff6b6b"), 3.0)
		"manzana":
			oval(Vector2(0, -32), 34, 32, Color("#e63946"), 4.0)
			oval(Vector2(-11, -44), 8, 11, Color(1, 1, 1, 0.3))
			draw_line(Vector2(0, -60), Vector2(6, -78), Color("#5a3a1e"), 6.0, true)
			oval(Vector2(20, -76), 14, 7, Color("#57a639"), 3.0)
		"planta":
			for k in 5:
				var a: float = -PI * 0.5 + (k - 2) * 0.42 + 0.04 * sin(t * 1.4 + k)
				var tip: Vector2 = Vector2(0, -52) + Vector2(cos(a), sin(a)) * 74.0
				draw_line(Vector2(0, -52), tip, INK, 21.0, true)
				draw_line(Vector2(0, -52), tip, Color("#57a639"), 14.0, true)
			shape([Vector2(-36, -56), Vector2(36, -56), Vector2(27, 0), Vector2(-27, 0)], Color("#c8703f"))
		_:
			oval(Vector2(0, -30), 30, 30, Color("#ff00ff"), 4.0)
