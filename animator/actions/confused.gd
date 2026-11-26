extends "res://core/action.gd"
# Confusión: ladea la cabeza y se rasca la coronilla.

func pose(lt: float, dur: float, _params: Dictionary, _rig: Node2D) -> Dictionary:
	var e: float = envelope(lt, dur)
	var scratch: float = sin(lt * 14.0) * 0.1
	return {
		"head_rot": e * 0.2,
		"arm_r": 0.12 + e * 2.55, "elbow_r": 0.1 + e * (1.5 + scratch),
		"lean": -e * 0.04,
		"brow": 0.3 * e, "brow_tilt": 0.7 * e, "mouth_curve": 0.25 - 0.6 * e,
	}
