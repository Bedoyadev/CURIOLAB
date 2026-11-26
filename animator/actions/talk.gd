extends "res://core/action.gd"
# Hablar: las manos acompañan a la voz con dos ritmos distintos, para que no se vea un bucle.
# La boca no es de esta acción: la mueve la pista de sincronía labial.

func pose(lt: float, dur: float, _params: Dictionary, rig: Node2D) -> Dictionary:
	var e: float = envelope(lt, dur)
	var a: float = sin(lt * 5.3)
	var b: float = sin(lt * 3.1 + 1.0)
	return {
		"arm_r": 0.12 + e * (0.75 + 0.22 * a),
		"elbow_r": 0.1 + e * (1.25 + 0.3 * b),
		"arm_l": 0.12 + e * (0.3 + 0.12 * b),
		"elbow_l": 0.1 + e * (0.8 + 0.2 * a),
		"lean": e * 0.035 * b,
		"head_rot": e * 0.05 * a,
		"bob": e * 0.006 * rig.H * a,
	}
