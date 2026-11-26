extends Camera2D
# La cámara de la escena. Cada movimiento registrado (library/manifest.json → cameras) parte de
# donde está la cámara y llega a su destino con arranque y frenada suaves, así que encadenan sin
# saltos. Nunca enseña fuera del mundo (1080×1920): el zoom mínimo es 1.

const WORLD := Vector2(1080, 1920)
const CENTER := Vector2(540, 960)

var _from_pos: Vector2 = CENTER
var _to_pos: Vector2 = CENTER
var _from_zoom: float = 1.0
var _to_zoom: float = 1.0
var _t0: float = 0.0
var _dur: float = 0.001
var _pos: Vector2 = CENTER
var _zoom: float = 1.0
var _follow: Callable = Callable()
var _shake_t0: float = -10.0
var _shake_dur: float = 0.0
var _shake_amp: float = 0.0


# point: destino resuelto por el director (un personaje, un objeto o un punto), o null.
# getter: para "follow", devuelve la posición actual de lo que se sigue.
func move(kind: String, t: float, duration: float, point: Variant, getter: Callable, params: Dictionary) -> bool:
	if kind == "shake":
		_shake_t0 = t
		_shake_dur = maxf(0.2, duration)
		_shake_amp = float(params.get("amount", 18.0))
		return true
	_from_pos = _pos
	_from_zoom = _zoom
	_t0 = t
	_dur = maxf(0.001, duration)
	_follow = Callable()
	_to_pos = _pos
	_to_zoom = _zoom
	match kind:
		"static":
			pass
		"wide":
			_to_pos = CENTER
			_to_zoom = 1.0
		"push_in":
			if point != null:
				_to_pos = point
			_to_zoom = clampf(float(params.get("zoom", 1.5)), 1.0, 2.6)
		"pan":
			if point != null:
				_to_pos = point
			_to_zoom = maxf(_zoom, 1.25)
		"follow":
			_follow = getter
			_to_zoom = clampf(float(params.get("zoom", 1.4)), 1.0, 2.6)
		"drift_up":
			_to_zoom = maxf(_zoom, 1.18)
			_to_pos = _pos + Vector2(0, -150)
		_:
			return false
	return true


func update(t: float) -> void:
	if _follow.is_valid():
		_to_pos = _follow.call()
	var u: float = smoothstep(0.0, 1.0, clampf((t - _t0) / _dur, 0.0, 1.0))
	_zoom = lerpf(_from_zoom, _to_zoom, u)
	var half: Vector2 = WORLD * 0.5 / _zoom
	_pos = _from_pos.lerp(_to_pos, u)
	_pos = Vector2(clampf(_pos.x, half.x, WORLD.x - half.x), clampf(_pos.y, half.y, WORLD.y - half.y))
	var jitter := Vector2.ZERO
	var s: float = t - _shake_t0
	if s >= 0.0 and s < _shake_dur:
		var fade: float = 1.0 - s / _shake_dur
		jitter = Vector2(sin(s * 61.0) + sin(s * 37.0), cos(s * 53.0) + sin(s * 29.0)) * 0.5 * _shake_amp * fade
	position = _pos + jitter
	zoom = Vector2(_zoom, _zoom)
