extends "res://core/action.gd"
# Señalar: el brazo del lado hacia el que mira sube recto, con un pequeño rebote al llegar.

func pose(lt: float, dur: float, _params: Dictionary, _rig: Node2D) -> Dictionary:
	var e: float = envelope(lt, dur, 0.2, 0.3)
	var settle: float = sin(minf(lt, 0.6) / 0.6 * PI) * 0.12
	return {
		"arm_r": 0.12 + e * (1.95 + settle),
		"elbow_r": 0.1 - e * 0.05,
		"lean": e * 0.07,
		"look_x": e * 0.9, "look_y": -e * 0.5,
		"brow": 0.5 * e,
	}
