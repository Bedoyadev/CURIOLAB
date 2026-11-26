extends "res://core/action.gd"
# Mirar atrás: gira la cabeza y los ojos hacia el lado contrario al que está orientado.

func pose(lt: float, dur: float, _params: Dictionary, rig: Node2D) -> Dictionary:
	var e: float = envelope(lt, dur)
	return {
		"head_x": -e * 0.035 * rig.H, "head_rot": -e * 0.06,
		"look_x": -e * 1.6, "lean": -e * 0.04,
	}
