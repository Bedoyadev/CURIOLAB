extends "res://core/action.gd"
# Sobresalto: salta hacia atrás un instante, brazos arriba, ojos y boca abiertos.

func pose(lt: float, dur: float, _params: Dictionary, rig: Node2D) -> Dictionary:
	var e: float = envelope(lt, dur, 0.1, 0.35)
	var jump: float = sin(clampf(lt / 0.35, 0.0, 1.0) * PI)
	var shake: float = sin(lt * 30.0) * maxf(0.0, 1.0 - lt / 0.6)
	return {
		"y": -jump * 0.07 * rig.H,
		"arm_l": 0.12 + e * (2.3 + 0.06 * shake), "arm_r": 0.12 + e * (2.3 - 0.06 * shake),
		"elbow_l": 0.1 + e * 0.5, "elbow_r": 0.1 + e * 0.5,
		"lean": -e * 0.1,
		"brow": e, "eye_open": 1.0 + 0.3 * e, "mouth_open": 4.0 if e > 0.5 else 0.0, "mouth_curve": 0.0,
	}
