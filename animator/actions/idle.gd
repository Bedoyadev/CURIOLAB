extends "res://core/action.gd"
# Reposo: respira y se balancea apenas. El rig la aplica siempre, debajo de cualquier otra acción.

func pose(lt: float, _dur: float, _params: Dictionary, rig: Node2D) -> Dictionary:
	var breath: float = sin(lt * 2.1)
	return {
		"bob": breath * 0.006 * rig.H,
		"lean": sin(lt * 0.9) * 0.012,
		"arm_l": 0.12 + breath * 0.02,
		"arm_r": 0.12 + breath * 0.02,
		"head_rot": sin(lt * 0.7) * 0.015,
	}
