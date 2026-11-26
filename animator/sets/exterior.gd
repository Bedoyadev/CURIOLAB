extends Node2D
# Campo abierto de día: cielo, nubes que pasan, colinas y hierba (el suelo está en y=1290).
# ARTE PROVISIONAL.

const INK := Color("#15161c")
var t: float = 0.0
var font: Font


func step(_dt: float, now: float) -> void:
	t = now
	queue_redraw()


func _cloud(x: float, y: float, s: float) -> void:
	for part in [[0, 0, 60], [55, -22, 48], [105, 0, 54], [52, 14, 50]]:
		draw_circle(Vector2(x + part[0] * s, y + part[1] * s), part[2] * s, Color(1, 1, 1, 0.92))


func _draw() -> void:
	draw_polygon(PackedVector2Array([Vector2(-200, -200), Vector2(1280, -200), Vector2(1280, 1200), Vector2(-200, 1200)]),
				 PackedColorArray([Color("#4aa8e8"), Color("#4aa8e8"), Color("#cdeeff"), Color("#cdeeff")]))
	_cloud(fposmod(120.0 + t * 14.0, 1500.0) - 220.0, 330, 1.0)
	_cloud(fposmod(760.0 + t * 9.0, 1500.0) - 220.0, 560, 0.75)
	var far := PackedVector2Array([Vector2(-200, 1200)])
	var near := PackedVector2Array([Vector2(-200, 1260)])
	for k in 38:
		var x: float = -200.0 + 40.0 * k
		far.append(Vector2(x, 1030.0 + 70.0 * sin(x * 0.006 + 1.0)))
		near.append(Vector2(x, 1150.0 + 40.0 * sin(x * 0.009 + 4.0)))
	far.append(Vector2(1280, 1200))
	near.append(Vector2(1280, 1260))
	draw_colored_polygon(far, Color("#7cc47f"))
	draw_colored_polygon(near, Color("#58b368"))
	draw_rect(Rect2(-200, 1180, 1480, 940), Color("#4c9f5b"))
	for k in 30:
		var gx: float = -180.0 + 50.0 * k
		var sway: float = 5.0 * sin(t * 2.0 + k)
		draw_line(Vector2(gx, 1330 + (k % 4) * 90), Vector2(gx + sway, 1306 + (k % 4) * 90), Color("#3c8549"), 5.0, true)
