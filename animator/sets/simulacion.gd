extends Node2D
# Pantalla de simulación: cuadrícula oscura sobre la que se dibujan los diagramas. ARTE PROVISIONAL.

var t: float = 0.0
var font: Font


func step(_dt: float, now: float) -> void:
	t = now
	queue_redraw()


func _draw() -> void:
	draw_polygon(PackedVector2Array([Vector2(-200, -200), Vector2(1280, -200), Vector2(1280, 2120), Vector2(-200, 2120)]),
				 PackedColorArray([Color("#0d1b2a"), Color("#0d1b2a"), Color("#16283d"), Color("#16283d")]))
	for k in 18:
		draw_line(Vector2(-180 + 90 * k, -200), Vector2(-180 + 90 * k, 2120), Color(0.3, 0.55, 0.8, 0.13), 2.0)
	for k in 27:
		draw_line(Vector2(-200, -190 + 90 * k), Vector2(1280, -190 + 90 * k), Color(0.3, 0.55, 0.8, 0.13), 2.0)
	# Una línea de barrido lenta: la pantalla está "encendida".
	var y: float = fposmod(t * 160.0, 2300.0) - 200.0
	draw_rect(Rect2(-200, y, 1480, 70), Color(0.3, 0.7, 1.0, 0.04))
