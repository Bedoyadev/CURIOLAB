extends Node2D
# Lo que va por encima de la escena: motas que suben (el aire moviéndose) y el destello.

var t: float = 0.0
var dust_from: float = -100.0
var dust_until: float = -100.0
var flash_at: float = -100.0
var _motes: Array = []


func _ready() -> void:
	z_index = 60
	var rng := RandomNumberGenerator.new()
	rng.seed = 11
	for k in 46:
		_motes.append([rng.randf_range(40, 1040), rng.randf_range(0, 1500), rng.randf_range(40, 110), rng.randf_range(3, 7), rng.randf_range(0, TAU)])


func step(_dt: float, now: float) -> void:
	t = now
	queue_redraw()


func _draw() -> void:
	if t >= dust_from and t < dust_until + 0.6:
		var fade: float = minf(clampf((t - dust_from) / 0.8, 0.0, 1.0), clampf((dust_until + 0.6 - t) / 0.6, 0.0, 1.0))
		for m in _motes:
			var y: float = 1500.0 - fposmod(float(m[1]) + (t - dust_from) * float(m[2]), 1400.0)
			var x: float = float(m[0]) + 16.0 * sin(t * 1.3 + float(m[4]))
			draw_circle(Vector2(x, y), float(m[3]), Color(1, 1, 1, 0.5 * fade))
	var f: float = t - flash_at
	if f >= 0.0 and f < 0.45:
		draw_rect(Rect2(-400, -400, 1880, 2720), Color(1, 1, 1, 0.85 * (1.0 - f / 0.45)))
