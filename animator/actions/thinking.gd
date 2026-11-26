extends "res://core/action.gd"
# Pensar: una mano a la barbilla, la otra sujeta el codo, la mirada se va arriba.

func pose(lt: float, dur: float, _params: Dictionary, _rig: Node2D) -> Dictionary:
	var e: float = envelope(lt, dur)
	return {
		"arm_r": 0.12 + e * 0.5, "elbow_r": 0.1 + e * (2.25 + 0.05 * sin(lt * 2.5)),
		"arm_l": 0.12 + e * 0.35, "elbow_l": 0.1 + e * 1.3,
		"head_rot": -e * 0.08, "lean": e * 0.03,
		"look_x": 0.5 * e, "look_y": -0.75 * e,
		"brow": 0.25 * e, "brow_tilt": -0.35 * e, "mouth_curve": 0.25 * (1.0 - e),
	}
