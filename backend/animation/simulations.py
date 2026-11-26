"""Numbers the episodes are allowed to say that do not come from a source: results of explicit
models, computed here. Claude chooses which model fits a question and with which inputs; it never
produces the result.

Every model states its formula, its inputs, its assumptions and how exact it is:
  "exacto"        the formula is the accepted one and the result holds under the stated assumptions;
  "simplificado"  a deliberately reduced model that leaves real effects out (they are listed). An
                  episode that shows one carries the label "Simulación simplificada" on screen.

Constants: IAU 2015 nominal values and CODATA / standard gravity.
"""
import math

G0 = 9.80665                    # standard gravity, m/s²
EARTH_RADIUS = 6_378_137.0      # equatorial radius, m
EARTH_OMEGA = 7.2921159e-5      # rotation rate, rad/s (one turn per sidereal day)
SURFACE_GRAVITY = {"tierra": 9.80665, "luna": 1.62, "marte": 3.71, "jupiter": 24.79}   # m/s²


class SimulationError(ValueError):
    pass


def _number(value, low: float, high: float, name: str) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise SimulationError(f"{name} no es un número")
    if not (low <= value <= high) or math.isnan(value):
        raise SimulationError(f"{name} fuera de rango ({low}–{high})")
    return value


def _es(x: float, digits: int = 2) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


def separacion_sin_gravedad(seconds=5.0, latitude=0.0) -> dict:
    """If gravity vanished, a body resting on the ground would keep the velocity the Earth's spin
    gives it and move in a straight line while the ground curves away beneath it."""
    t = _number(seconds, 0.1, 60, "seconds")
    lat = _number(latitude, -89, 89, "latitude")
    cos = math.cos(math.radians(lat))
    speed = EARTH_OMEGA * EARTH_RADIUS * cos              # ground speed from rotation, m/s
    # Component, along the local vertical, of the centripetal acceleration the ground has.
    accel = EARTH_OMEGA ** 2 * EARTH_RADIUS * cos ** 2
    gap = 0.5 * accel * t ** 2
    secs = _es(t, 0) if t == int(t) else _es(t, 1)
    kmh = f"{round(speed * 3.6):,}".replace(",", ".")
    where = "en el ecuador" if abs(lat) < 0.5 else f"a {abs(lat):.0f}° de latitud"
    return {
        "id": "separacion_sin_gravedad", "exactness": "simplificado",
        "formula": "d ≈ ½·ω²·R·cos²(lat)·t²   (ω: giro de la Tierra, R: su radio)",
        "inputs": {"seconds": t, "latitude": lat},
        "assumptions": [
            "Solo desaparece la gravedad; todo lo demás sigue igual durante esos segundos.",
            "El cuerpo estaba quieto sobre el suelo y nada lo sujeta.",
            "No se cuenta el aire (que también se expandiría hacia arriba) ni el rebote del suelo y de los cuerpos al dejar de estar comprimidos por su peso.",
            "Válida para tiempos cortos frente a un día.",
        ],
        "results": {"gap_m": round(gap, 3), "ground_speed_kmh": round(speed * 3.6), "accel_ms2": round(accel, 4)},
        "statement": (f"Sin gravedad durante {secs} segundos, un objeto suelto {where} se separaría del suelo unos "
                      f"{_es(gap * 100, 0)} centímetros: sigue recto a {kmh} km/h mientras el suelo se curva bajo él. "
                      "Es un modelo simplificado: no cuenta el aire ni el rebote del suelo."),
        "prop_params": {"seconds": t, "accel": round(accel, 5), "place": f"Objeto suelto {where} · modelo simplificado"},
    }


def caida_libre(height=1.0, world="tierra") -> dict:
    """Time and speed of a fall from rest, without air."""
    h = _number(height, 0.05, 1000, "height")
    if world not in SURFACE_GRAVITY:
        raise SimulationError(f"mundo desconocido: {world}")
    g = SURFACE_GRAVITY[world]
    t = math.sqrt(2 * h / g)
    v = g * t
    return {
        "id": "caida_libre", "exactness": "exacto",
        "formula": "t = √(2h/g),  v = g·t",
        "inputs": {"height": h, "world": world},
        "assumptions": ["Parte del reposo.", "Sin resistencia del aire.", f"g = {_es(g)} m/s² ({world})."],
        "results": {"seconds": round(t, 2), "speed_ms": round(v, 2), "speed_kmh": round(v * 3.6, 1)},
        "statement": (f"Sin aire, algo que cae desde {_es(h, 1)} metros en {world.capitalize()} tarda "
                      f"{_es(t)} segundos y llega al suelo a {_es(v * 3.6, 0)} km/h."),
        "prop_params": {},
    }


def peso_en_otro_mundo(mass=70.0, world="luna") -> dict:
    """What a bathroom scale calibrated on Earth would show on another world."""
    m = _number(mass, 0.1, 1000, "mass")
    if world not in SURFACE_GRAVITY:
        raise SimulationError(f"mundo desconocido: {world}")
    shown = m * SURFACE_GRAVITY[world] / G0
    return {
        "id": "peso_en_otro_mundo", "exactness": "exacto",
        "formula": "lectura = m · g_mundo / g_Tierra",
        "inputs": {"mass": m, "world": world},
        "assumptions": ["La masa no cambia; cambia el peso.", f"g en la superficie de {world}: {_es(SURFACE_GRAVITY[world])} m/s²."],
        "results": {"scale_kg": round(shown, 1), "ratio": round(SURFACE_GRAVITY[world] / G0, 3)},
        "statement": (f"Una báscula de baño marcaría {_es(shown, 1)} kg para alguien de {_es(m, 0)} kg en "
                      f"{world.capitalize()}: su masa es la misma, pesa distinto."),
        "prop_params": {},
    }


REGISTRY = {"separacion_sin_gravedad": separacion_sin_gravedad, "caida_libre": caida_libre,
            "peso_en_otro_mundo": peso_en_otro_mundo}

# What each model is for, offered to Claude when it plans the research.
CATALOG = {
    "separacion_sin_gravedad": "cuánto se separaría del suelo un objeto si la gravedad desapareciera unos segundos (entradas: seconds, latitude)",
    "caida_libre": "tiempo y velocidad de una caída sin aire (entradas: height en metros, world: tierra|luna|marte|jupiter)",
    "peso_en_otro_mundo": "qué marcaría una báscula en otro mundo (entradas: mass en kg, world)",
}


def run(sim_id: str, inputs: dict | None = None) -> dict:
    if sim_id not in REGISTRY:
        raise SimulationError(f"simulación no registrada: {sim_id}")
    known = {k: v for k, v in (inputs or {}).items() if v not in (None, "")}
    try:
        return REGISTRY[sim_id](**known)
    except TypeError as e:
        raise SimulationError(f"entradas no válidas para {sim_id}: {e}")
