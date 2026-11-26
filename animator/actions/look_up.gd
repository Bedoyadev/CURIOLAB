extends "res://core/action.gd"
# Mirar arriba: la cabeza se echa atrás y los ojos siguen lo que hay encima.

func pose(lt: float, dur: float, _params: Dictionary, rig: Node2D) -> Dictionary:
	var e: float = envelope(lt, dur)
	return {
		"head_rot": -e * 0.22, "head_y": -e * 0.012 * rig.H,
		"look_y": -e, "look_x": 0.15 * e * sin(lt * 1.3),
		"lean": -e * 0.05, "brow": 0.6 * e,
	}
