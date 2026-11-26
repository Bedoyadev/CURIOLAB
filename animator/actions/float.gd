extends "res://core/action.gd"
# Flotar sin peso: los pies se despegan, el cuerpo se mece y gira despacio, brazos y piernas quedan
# sueltos. params: {"lift": fracción de la altura del personaje que se eleva (por defecto 0.22)}.
# Es una dramatización: cuánto se separaría de verdad del suelo lo dice la simulación del episodio.

func pose(lt: float, dur: float, params: Dictionary, rig: Node2D) -> Dictionary:
	var e: float = envelope(lt, dur, 1.2, 0.25)
	var lift: float = float(params.get("lift", 0.22))
	return {
		"y": -e * (lift + 0.03 * sin(lt * 1.7)) * rig.H,
		"rot": e * 0.16 * sin(lt * 0.9),
		"arm_l": 0.12 + e * (1.25 + 0.25 * sin(lt * 1.9)), "arm_r": 0.12 + e * (1.15 + 0.25 * sin(lt * 2.3 + 1.0)),
		"elbow_l": 0.1 + e * 0.5, "elbow_r": 0.1 + e * 0.45,
		"leg_l": e * (-0.3 + 0.2 * sin(lt * 2.1)), "leg_r": e * (0.28 + 0.2 * sin(lt * 1.6 + 2.0)),
		"lean": e * 0.05 * sin(lt * 1.2),
	}
