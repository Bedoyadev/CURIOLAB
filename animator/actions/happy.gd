extends "res://core/action.gd"
# Alegría: dos saltitos con los brazos en alto.

func pose(lt: float, dur: float, _params: Dictionary, rig: Node2D) -> Dictionary:
	var e: float = envelope(lt, dur, 0.15, 0.3)
	var hop: float = absf(sin(lt * 6.5)) * maxf(0.0, 1.0 - lt / 1.1)
	return {
		"y": -hop * 0.09 * rig.H,
		"arm_l": 0.12 + e * (2.5 + 0.2 * sin(lt * 13.0)), "arm_r": 0.12 + e * (2.5 - 0.2 * sin(lt * 13.0)),
		"elbow_l": 0.1 + e * 0.3, "elbow_r": 0.1 + e * 0.3,
		"leg_l": -hop * 0.2, "leg_r": hop * 0.2,
		"brow": 0.5 * e, "mouth_curve": 1.0, "eye_open": 1.0 - 0.15 * e,
	}
