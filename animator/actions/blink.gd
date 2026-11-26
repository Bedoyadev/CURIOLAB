extends "res://core/action.gd"
# Parpadeo marcado, dos veces: el gesto de quien no se cree lo que ve.

func pose(lt: float, _dur: float, _params: Dictionary, _rig: Node2D) -> Dictionary:
	var open: float = 1.0
	for start in [0.1, 0.45]:
		var u: float = (lt - start) / 0.2
		if u > 0.0 and u < 1.0:
			open = absf(u - 0.5) * 2.0
	return {"eye_open": maxf(open, 0.05), "head_x": 0.0, "brow": 0.3}
