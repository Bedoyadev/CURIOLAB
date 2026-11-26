extends Node2D
# Espacio: fondo de estrellas que titilan. ARTE PROVISIONAL.

var t: float = 0.0
var font: Font
var _stars: Array = []


func _ready() -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = 7
	for k in 150:
		_stars.append([rng.randf_range(-150, 1230), rng.randf_range(-150, 2070), rng.randf_range(1.5, 4.5), rng.randf_range(0.0, TAU)])


func step(_dt: float, now: float) -> void:
	t = now
	queue_redraw()


func _draw() -> void:
	draw_polygon(PackedVector2Array([Vector2(-200, -200), Vector2(1280, -200), Vector2(1280, 2120), Vector2(-200, 2120)]),
				 PackedColorArray([Color("#070a1a"), Color("#0b1030"), Color("#1a1440"), Color("#120c2e")]))
	draw_circle(Vector2(860, 420), 330, Color(0.35, 0.2, 0.6, 0.1))
	draw_circle(Vector2(220, 1300), 380, Color(0.1, 0.35, 0.6, 0.1))
	for s in _stars:
		var glow: float = 0.55 + 0.45 * sin(t * 2.0 + float(s[3]))
		draw_circle(Vector2(s[0], s[1]), float(s[2]), Color(1, 1, 1, glow))
