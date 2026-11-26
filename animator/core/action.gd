extends RefCounted
# Base de una acción de personaje. Una acción no mueve nodos: devuelve, para cada instante, los
# valores de los canales de la pose (ver CHANNELS en character_rig.gd) que quiere imponer. El rig
# mezcla esa pose con la anterior, así que cualquier acción encadena con cualquier otra sin saltos.
#
# Para añadir una acción: un archivo en actions/ que extienda este, y su entrada en
# library/manifest.json. Nada más del motor cambia.

# Se llama una vez cuando la acción empieza. Puede guardar en params lo que necesite recordar.
func start(_rig: Node2D, _params: Dictionary) -> void:
	pass

# lt: segundos desde que empezó. dur: duración pedida (0 = hasta que la sustituya otra).
func pose(_lt: float, _dur: float, _params: Dictionary, _rig: Node2D) -> Dictionary:
	return {}

# 0→1 al entrar y 1→0 al salir: para que un gesto con duración suba y baje solo.
static func envelope(lt: float, dur: float, attack: float = 0.25, release: float = 0.3) -> float:
	var a: float = clampf(lt / attack, 0.0, 1.0)
	var r: float = 1.0 if dur <= 0.0 else clampf((dur - lt) / release, 0.0, 1.0)
	return smoothstep(0.0, 1.0, minf(a, r))
