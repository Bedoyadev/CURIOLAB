extends "res://core/action.gd"
# Caminar hasta un punto del escenario. params: {"to_x": píxeles del mundo}. Si no se da duración,
# la calcula el plan a partir de la distancia.

func start(rig: Node2D, params: Dictionary) -> void:
	params["_x0"] = rig.position.x
	var to_x: float = float(params.get("to_x", rig.position.x))
	if absf(to_x - rig.position.x) > 4.0:
		rig.facing = 1.0 if to_x > rig.position.x else -1.0

func pose(lt: float, dur: float, params: Dictionary, rig: Node2D) -> Dictionary:
	var x0: float = float(params.get("_x0", rig.position.x))
	var to_x: float = float(params.get("to_x", x0))
	var u: float = 1.0 if dur <= 0.0 else clampf(lt / dur, 0.0, 1.0)
	# Arranca y frena con suavidad; los pasos se apagan al llegar.
	var moving: float = sin(u * PI)
	var step: float = sin(lt * 9.0) * minf(1.0, moving * 3.0)
	return {
		"_x": lerpf(x0, to_x, smoothstep(0.0, 1.0, u)),
		"leg_l": step * 0.5, "leg_r": -step * 0.5,
		"arm_l": 0.12 - step * 0.45, "arm_r": 0.12 + step * 0.45,
		"bob": -absf(cos(lt * 9.0)) * 0.018 * rig.H * minf(1.0, moving * 3.0),
		"lean": 0.06 * minf(1.0, moving * 3.0),
	}
