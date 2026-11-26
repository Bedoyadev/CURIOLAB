extends Node2D
# Laboratorio. Los puntos donde se colocan personajes y objetos están en library/manifest.json
# (anchors / prop_anchors) y tienen que coincidir con lo que aquí se dibuja: la mesa (tablero en
# y=1040), el estante (y=560) y el suelo (y=1290). ARTE PROVISIONAL.

const INK := Color("#15161c")
var t: float = 0.0
var font: Font


func step(_dt: float, now: float) -> void:
	t = now
	queue_redraw()


func _box(x: float, y: float, w: float, h: float, color: Color, outline: float = 4.0) -> void:
	draw_rect(Rect2(x, y, w, h), color)
	if outline > 0.0:
		draw_rect(Rect2(x, y, w, h), INK, false, outline)


func _draw() -> void:
	# Pared (degradado) y suelo. Se dibuja más ancho que el cuadro por si la cámara tiembla.
	draw_polygon(PackedVector2Array([Vector2(-200, -200), Vector2(1280, -200), Vector2(1280, 1180), Vector2(-200, 1180)]),
				 PackedColorArray([Color("#9fd3e6"), Color("#9fd3e6"), Color("#d9eef5"), Color("#d9eef5")]))
	draw_rect(Rect2(-200, 1180, 1480, 940), Color("#c4a784"))
	for k in 9:
		draw_line(Vector2(-200, 1230 + 86 * k), Vector2(1280, 1230 + 86 * k), Color("#b3956f"), 4.0)
	draw_rect(Rect2(-200, 1140, 1480, 40), Color("#6b8fa3"))
	draw_line(Vector2(-200, 1180), Vector2(1280, 1180), INK, 4.0)
	# El suelo se oscurece hacia la pared: da fondo a la habitación.
	draw_polygon(PackedVector2Array([Vector2(-200, 1180), Vector2(1280, 1180), Vector2(1280, 1330), Vector2(-200, 1330)]),
				 PackedColorArray([Color(0, 0, 0, 0.18), Color(0, 0, 0, 0.18), Color(0, 0, 0, 0.0), Color(0, 0, 0, 0.0)]))
	# Luz de la ventana cayendo sobre la pared y el suelo.
	draw_colored_polygon(PackedVector2Array([Vector2(70, 480), Vector2(400, 480), Vector2(720, 1180), Vector2(250, 1180)]), Color(1, 1, 0.9, 0.1))
	draw_colored_polygon(PackedVector2Array([Vector2(250, 1180), Vector2(720, 1180), Vector2(900, 1500), Vector2(330, 1500)]), Color(1, 1, 0.9, 0.08))

	# Ventana con cielo.
	_box(70, 230, 330, 250, Color("#bfe9ff"))
	draw_circle(Vector2(140 + 14.0 * sin(t * 0.3), 300), 26, Color(1, 1, 1, 0.9))
	draw_circle(Vector2(176 + 14.0 * sin(t * 0.3), 310), 20, Color(1, 1, 1, 0.9))
	draw_line(Vector2(235, 230), Vector2(235, 480), INK, 5.0)
	draw_line(Vector2(70, 355), Vector2(400, 355), INK, 5.0)

	# Estante (los objetos se apoyan en y=560).
	_box(60, 560, 360, 20, Color("#8a6a4a"))
	draw_line(Vector2(90, 580), Vector2(90, 620), INK, 6.0)
	draw_line(Vector2(390, 580), Vector2(390, 620), INK, 6.0)

	# Pizarra.
	_box(540, 250, 470, 350, Color("#2f5d50"), 10.0)
	draw_rect(Rect2(540, 250, 470, 350), Color("#8a6a4a"), false, 10.0)
	if font != null:
		draw_string(font, Vector2(574, 330), "F = G·m₁·m₂ / r²", HORIZONTAL_ALIGNMENT_LEFT, -1, 40, Color(1, 1, 1, 0.85))
		draw_string(font, Vector2(574, 400), "g ≈ 9,8 m/s²", HORIZONTAL_ALIGNMENT_LEFT, -1, 40, Color(1, 1, 1, 0.85))
	draw_arc(Vector2(860, 500), 54, 0, TAU, 32, Color(1, 1, 1, 0.8), 4.0, true)
	draw_line(Vector2(860, 500), Vector2(860, 570), Color(1, 0.82, 0.25, 0.9), 5.0, true)
	draw_colored_polygon(PackedVector2Array([Vector2(860, 588), Vector2(848, 566), Vector2(872, 566)]), Color(1, 0.82, 0.25, 0.9))
	_box(700, 606, 150, 16, Color("#8a6a4a"), 3.0)

	# Reloj de pared: lo único del fondo que marca que el tiempo corre.
	draw_circle(Vector2(470, 300), 44, Color.WHITE)
	draw_arc(Vector2(470, 300), 44, 0, TAU, 32, INK, 5.0, true)
	draw_line(Vector2(470, 300), Vector2(470, 300) + Vector2.UP.rotated(t * TAU / 60.0 * 6.0) * 34.0, Color("#e63946"), 3.0, true)
	draw_line(Vector2(470, 300), Vector2(470, 300) + Vector2.UP.rotated(0.9) * 24.0, INK, 5.0, true)

	# Mesa (tablero en y=1040) y su sombra en el suelo.
	var shadow := PackedVector2Array()
	for k in 24:
		shadow.append(Vector2(540 + cos(TAU * k / 24.0) * 250.0, 1246 + sin(TAU * k / 24.0) * 22.0))
	draw_colored_polygon(shadow, Color(0, 0, 0, 0.16))
	_box(350, 1066, 26, 170, Color("#5c6378"))
	_box(704, 1066, 26, 170, Color("#5c6378"))
	_box(322, 1040, 436, 28, Color("#e9edf5"))
	draw_rect(Rect2(322, 1068, 436, 12), Color(0, 0, 0, 0.12))
