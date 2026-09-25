#!/usr/bin/env python3
"""Tracker de progreso hacia C1.

Lee tracker/data/sesiones.csv y tracker/data/evaluaciones.csv (el mismo formato
que exporta la web app tracker/index.html) y genera un reporte en Markdown.

Uso:
    python tracker/progress.py                      # imprime el reporte y lo guarda en tracker/reporte.md
    python tracker/progress.py add reading 30 "Graded reader nivel 3" --cantidad 3500 --unidad palabras
    python tracker/progress.py add listening 40 "Podcast en el bus" --pasivo
    python tracker/progress.py test "EF SET 50" general --puntaje 58      # el MCER se deduce del puntaje
    python tracker/progress.py --datos tracker/ejemplo --hoy 2026-09-25   # ver los datos de ejemplo

Acepta CSV separados por coma o por punto y coma (Excel en español), con o sin BOM.
Solo usa la biblioteca estándar de Python 3.9+.
"""

import argparse
import csv
import io
import math
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
SESIONES_CAMPOS = ["fecha", "habilidad", "actividad", "minutos", "modo", "cantidad", "unidad", "notas"]
EVALUACIONES_CAMPOS = ["fecha", "prueba", "habilidad", "puntaje", "cefr", "notas"]
HABILIDADES = ["speaking", "writing", "listening", "reading", "grammar", "vocabulary"]
HABILIDADES_EVAL = ["general"] + HABILIDADES
MODOS = ["activo", "pasivo"]
CEFR_ORDEN = ["A1", "A2", "B1", "B2", "C1", "C2"]
MAX_MINUTOS = 600
DIAS_MES = 30.44

# Horas guiadas acumuladas de referencia de Cambridge (punto medio de cada rango).
# Cambridge no publica A1: 95 h es una extrapolación propia.
HORAS_CEFR = {"A1": 95, "A2": 190, "B1": 375, "B2": 550, "C1": 750, "C2": 1100}
# SUPUESTO, no evidencia: horas de autoestudio que equivalen a una hora guiada.
# Anclaje aproximado: FSI Categoría I (600-750 h de clase + estudio autónomo diario)
# ≈ 1,3-1,6 veces las 750 h guiadas de C1. Ver research/investigacion_profunda.md §9.
FACTOR_AUTOESTUDIO = (1.2, 1.8)

# Distribución objetivo del tiempo ACTIVO (los 4 hilos de Nation, 2007; ver plan).
PLAN = {"input": 0.375, "output": 0.375, "vocabulary": 0.15, "grammar": 0.10}

# Escala oficial de EF SET (0-100) -> MCER, y puntaje mínimo de cada nivel.
EFSET_BANDAS = [(71, "C2"), (61, "C1"), (51, "B2"), (41, "B1"), (31, "A2"), (0, "A1")]
EFSET_MINIMO = {"A2": 31, "B1": 41, "B2": 51, "C1": 61, "C2": 71}

# Recordatorios: (prefijo del nombre de la prueba, cada cuántos días).
RECORDATORIOS = [("EF SET", 28), ("Write & Improve", 28), ("Speaking grabado", 28),
                 ("Vocabulary Size Test", 56), ("Autoevaluación MCER", 91)]

# Una evaluación más antigua que esto no fija la "habilidad más débil" si hay otras recientes.
DIAS_VIGENCIA = 120


# ---------------------------------------------------------------- utilidades

def normalizar(texto):
    """Minúsculas y sin tildes, para comparar nombres de pruebas."""
    t = unicodedata.normalize("NFD", str(texto or "").strip().lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def cefr_a_num(cefr):
    """'B1' -> 3.0, 'B1+' -> 3.5. Devuelve None si no es válido."""
    if not cefr:
        return None
    c = str(cefr).strip().upper()
    extra = 0.5 if c.endswith("+") else 0.0
    c = c.rstrip("+")
    if c not in CEFR_ORDEN:
        return None
    return CEFR_ORDEN.index(c) + 1 + extra


def num_a_cefr(n):
    if n is None:
        return "—"
    base = CEFR_ORDEN[min(int(n), 6) - 1]
    return base + ("+" if n - int(n) >= 0.5 else "")


_MILES = re.compile(r"^\d{1,3}([.,]\d{3})+$")


def a_float(v):
    """Convierte texto a número. Acepta coma decimal ('1,5') y separador de miles ('4.400').

    Devuelve None si está vacío, no es un número o no es finito (nan, inf)."""
    if v is None:
        return None
    s = str(v).strip().replace(" ", "")
    if not s:
        return None
    s = re.sub(r"[.,]", "", s) if _MILES.match(s) else s.replace(",", ".")
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def efset_a_cefr(puntaje):
    p = a_float(puntaje)
    if p is None:
        return ""
    return next(nivel for minimo, nivel in EFSET_BANDAS if p >= minimo)


def es_efset(prueba):
    return normalizar(prueba).startswith("ef set")


def es_autoevaluacion(prueba):
    return normalizar(prueba).startswith("autoevaluacion")


def parse_fecha(s):
    return datetime.strptime(str(s).strip(), "%Y-%m-%d").date()


def fecha_arg(s):
    """Tipo de argparse: fecha YYYY-MM-DD con un mensaje de error claro."""
    try:
        return parse_fecha(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"fecha inválida '{s}': usa el formato AAAA-MM-DD (p. ej. 2026-09-25)")


# ---------------------------------------------------------------- CSV

def detectar_delimitador(primera_linea):
    """Excel en español guarda los CSV con ';'. Se elige el separador más frecuente en la cabecera."""
    return ";" if primera_linea.count(";") > primera_linea.count(",") else ","


def _leer_texto(ruta):
    """Devuelve (delimitador, cabecera normalizada, filas como dicts, texto) o None si no hay contenido."""
    if not ruta.exists():
        return None
    texto = ruta.read_text(encoding="utf-8-sig")  # utf-8-sig quita el BOM que añade Excel
    if not texto.strip():
        return None
    delim = detectar_delimitador(next(l for l in texto.splitlines() if l.strip()))
    lector = csv.reader(io.StringIO(texto, newline=""), delimiter=delim)
    filas_crudas = [f for f in lector if any(c.strip() for c in f)]
    cabecera = [h.strip().lower() for h in filas_crudas[0]]
    filas = [{cabecera[i]: (f[i] if i < len(f) else "") for i in range(len(cabecera))} for f in filas_crudas[1:]]
    return delim, cabecera, filas, texto


def leer_csv(ruta, campos):
    leido = _leer_texto(ruta)
    if leido is None:
        return []
    _, cabecera, crudas, _ = leido
    if "fecha" not in cabecera:
        print(f"Aviso: {ruta.name}: falta la columna 'fecha' en la cabecera; se ignora el archivo.", file=sys.stderr)
        return []
    filas = []
    for i, cruda in enumerate(crudas, start=2):
        fila = {k: (cruda.get(k) or "").strip() for k in campos}
        try:
            fila["_fecha"] = parse_fecha(fila["fecha"])
        except ValueError:
            print(f"Aviso: {ruta.name} fila {i}: fecha inválida '{fila['fecha']}', se ignora.", file=sys.stderr)
            continue
        fila["habilidad"] = fila["habilidad"].lower()
        if "modo" in fila:
            fila["modo"] = "pasivo" if fila["modo"].lower() == "pasivo" else "activo"
        if "cefr" in fila:
            fila["cefr"] = fila["cefr"].upper()
            if not fila["cefr"] and es_efset(fila["prueba"]):
                fila["cefr"] = efset_a_cefr(fila["puntaje"])
        filas.append(fila)
    return filas


def _escribir(ruta, campos, filas, delim=",", eol="\n"):
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, delimiter=delim, lineterminator=eol, extrasaction="ignore")
        w.writeheader()
        for fila in filas:
            w.writerow({c: fila.get(c, "") for c in campos})


def agregar_fila(ruta, campos, fila):
    """Añade una fila respetando el separador y los finales de línea del archivo existente.

    Si al archivo le faltan columnas (p. ej. 'modo' en un CSV antiguo), se reescribe con la
    cabecera nueva conservando todos los datos."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    leido = _leer_texto(ruta)
    if leido is None:
        _escribir(ruta, campos, [fila])
        return
    delim, cabecera, filas, texto = leido
    eol = "\r\n" if "\r\n" in texto else "\n"
    if all(c in cabecera for c in campos):
        with ruta.open("a", newline="", encoding="utf-8") as f:
            if not texto.endswith(("\n", "\r")):
                f.write(eol)  # sin esto, la fila nueva se pegaría a la última
            w = csv.DictWriter(f, fieldnames=cabecera, delimiter=delim, lineterminator=eol, extrasaction="ignore")
            w.writerow({c: fila.get(c, "") for c in cabecera})
    else:
        extra = [c for c in cabecera if c not in campos]
        _escribir(ruta, campos + extra, filas + [fila], delim, eol)


# ---------------------------------------------------------------- cálculos

def fmt(x, dec=0, signo=False):
    """Número en formato español: 1.234,5"""
    s = f"{x:+,.{dec}f}" if signo else f"{x:,.{dec}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def barra(valor, maximo, ancho=24):
    if maximo <= 0:
        return ""
    n = round(ancho * valor / maximo)
    return "█" * n + "░" * (ancho - n)


def racha(dias_con_estudio, hoy):
    """Días consecutivos con estudio terminando hoy (o ayer, si hoy aún no se registró)."""
    d = hoy if hoy in dias_con_estudio else hoy - timedelta(days=1)
    n = 0
    while d in dias_con_estudio:
        n += 1
        d -= timedelta(days=1)
    return n


def minutos(s):
    return a_float(s["minutos"]) or 0.0


def calcular_metricas(sesiones, hoy):
    """Métricas de constancia. Solo cuentan las sesiones activas con fecha <= hoy."""
    activas = [s for s in sesiones if s.get("modo") != "pasivo" and s["_fecha"] <= hoy]
    pasivas = [s for s in sesiones if s.get("modo") == "pasivo" and s["_fecha"] <= hoy]
    por_dia = defaultdict(float)
    for s in activas:
        por_dia[s["_fecha"]] += minutos(s)
    primer_dia = min(por_dia, default=hoy)
    # Con menos de 28 días de historial, el promedio se calcula sobre los días transcurridos.
    ventana = max(1, min(28, (hoy - primer_dia).days + 1))
    inicio = hoy - timedelta(days=ventana - 1)
    por_hab = defaultdict(float)
    for s in activas:
        if s["_fecha"] >= inicio:
            por_hab[s["habilidad"]] += minutos(s)
    min_ventana = sum(por_hab.values())
    palabras = [a_float(s["cantidad"]) or 0.0 for s in activas + pasivas if s["unidad"].lower().startswith("palabra")]
    palabras_mes = sum(a_float(s["cantidad"]) or 0.0 for s in activas + pasivas
                       if s["unidad"].lower().startswith("palabra") and s["_fecha"] >= hoy.replace(day=1))
    return {
        "activas": activas,
        "por_dia": por_dia,
        "por_hab": por_hab,
        "ventana": ventana,
        "inicio": inicio,
        "min_ventana": min_ventana,
        "prom": min_ventana / ventana,
        "dias_activos": sum(1 for d, m in por_dia.items() if d >= inicio and m > 0),
        "racha": racha({d for d, m in por_dia.items() if m > 0}, hoy),
        "total_h": sum(por_dia.values()) / 60,
        "pasivo_ventana_h": sum(minutos(s) for s in pasivas if s["_fecha"] >= inicio) / 60,
        "pasivo_total_h": sum(minutos(s) for s in pasivas) / 60,
        "palabras": sum(palabras),
        "palabras_mes": palabras_mes,
        "futuras": sum(1 for s in sesiones if s["_fecha"] > hoy),
    }


def ultimas_por_habilidad(evaluaciones, hoy):
    """Última evaluación con MCER de cada habilidad. Las autoevaluaciones no cuentan (son menos fiables)."""
    ultimas = {}
    for e in sorted(evaluaciones, key=lambda x: x["_fecha"]):
        if e["_fecha"] <= hoy and cefr_a_num(e["cefr"]) is not None and not es_autoevaluacion(e["prueba"]):
            ultimas[e["habilidad"]] = e
    return ultimas


def horas_de_referencia(nivel):
    base = num_a_cefr(nivel).rstrip("+")
    horas = HORAS_CEFR[base]
    if nivel - int(nivel) >= 0.5:
        siguiente = CEFR_ORDEN[min(CEFR_ORDEN.index(base) + 1, 5)]
        horas = (horas + HORAS_CEFR[siguiente]) / 2
    return horas


def proyeccion_horas(ultimas, activas, hoy, objetivo):
    """Modelo de horas: parte de la habilidad más débil (el C1 real exige todas).

    El vocabulario no cuenta como habilidad MCER: no hay una equivalencia validada entre
    tamaño de vocabulario y nivel. Las evaluaciones de más de DIAS_VIGENCIA días se usan
    solo si no hay otras recientes."""
    candidatas = {h: e for h, e in ultimas.items() if h in HABILIDADES_EVAL and h != "vocabulary"}
    recientes = {h: e for h, e in candidatas.items() if (hoy - e["_fecha"]).days <= DIAS_VIGENCIA}
    usar = recientes or candidatas
    if not usar:
        return None
    # A igual nivel, manda la evaluación más reciente (es la que se sabe vigente) y, si empatan,
    # una destreza concreta antes que "general" (es más útil para decidir qué reforzar).
    hab, ev = min(usar.items(), key=lambda kv: (cefr_a_num(kv[1]["cefr"]), -kv[1]["_fecha"].toordinal(), kv[0] == "general"))
    nivel = cefr_a_num(ev["cefr"])
    horas_base = horas_de_referencia(nivel)
    horas_desde = sum(minutos(s) for s in activas if s["_fecha"] > ev["_fecha"]) / 60
    restantes = max(0.0, HORAS_CEFR[objetivo] - horas_base - horas_desde)
    return {"habilidad": hab, "evaluacion": ev, "nivel": nivel, "horas_base": horas_base,
            "horas_desde": horas_desde, "restantes": restantes, "antiguas": sorted(set(candidatas) - set(recientes))}


def tendencia_efset(evaluaciones, hoy, objetivo):
    """Regresión lineal de los puntajes EF SET 'general'. Requiere >= 3 puntos en >= 8 semanas."""
    puntos = sorted((e["_fecha"], a_float(e["puntaje"])) for e in evaluaciones
                    if es_efset(e["prueba"]) and e["habilidad"] == "general"
                    and a_float(e["puntaje"]) is not None and e["_fecha"] <= hoy)
    if len(puntos) < 3 or (puntos[-1][0] - puntos[0][0]).days < 56:
        return None
    x0 = puntos[0][0]
    xs = [(f - x0).days for f, _ in puntos]
    ys = [p for _, p in puntos]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    pendiente = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    estimado_hoy = my + pendiente * ((hoy - x0).days - mx)
    meta = EFSET_MINIMO[objetivo]
    if estimado_hoy >= meta:
        fecha = hoy
    elif pendiente > 0:
        fecha = hoy + timedelta(days=round((meta - estimado_hoy) / pendiente))
    else:
        fecha = None
    return {"n": len(puntos), "pendiente_mes": pendiente * DIAS_MES, "estimado_hoy": estimado_hoy,
            "meta": meta, "fecha": fecha}


# ---------------------------------------------------------------- reporte

def generar_reporte(sesiones, evaluaciones, hoy, meta_min_dia, objetivo):
    L = [f"# Reporte de progreso — {hoy.isoformat()}\n"]
    if not sesiones and not evaluaciones:
        L.append("Aún no hay datos. Registra tu primera sesión con la web app o con:\n")
        L.append('`python tracker/progress.py add reading 30 "Graded reader" --cantidad 3000 --unidad palabras`\n')
        return "\n".join(L)

    m = calcular_metricas(sesiones, hoy)
    v = m["ventana"]

    # --- Resumen
    L.append("## Resumen\n")
    L.append("| Métrica | Valor |")
    L.append("|---|---|")
    L.append(f"| Horas de estudio activo (total) | **{fmt(m['total_h'], 1)} h** |")
    L.append(f"| Horas de estudio activo (últimos {v} días) | {fmt(m['min_ventana'] / 60, 1)} h ({m['dias_activos']}/{v} días activos) |")
    L.append(f"| Promedio diario (últimos {v} días) | {fmt(m['prom'])} min (meta: {fmt(meta_min_dia)} min) |")
    L.append(f"| Cumplimiento de la meta | {fmt(min(100, 100 * m['prom'] / meta_min_dia))} % |")
    L.append(f"| Racha actual | {m['racha']} días |")
    L.append(f"| Escucha pasiva extra (últimos {v} días / total) | {fmt(m['pasivo_ventana_h'], 1)} h / {fmt(m['pasivo_total_h'], 1)} h |")
    L.append(f"| Palabras leídas (total / este mes) | {fmt(m['palabras'])} / {fmt(m['palabras_mes'])} |")
    L.append("")

    # --- Distribución por habilidad
    L.append(f"## Tiempo activo por habilidad (últimos {v} días)\n")
    L.append("Objetivo del plan (4 hilos de Nation): input (reading + listening) ≈ 37,5 %, "
             "output (speaking + writing) ≈ 37,5 %, vocabulary ≈ 15 %, grammar ≈ 10 %.\n")
    L.append("```")
    por_hab = m["por_hab"]
    total_v = m["min_ventana"] or 1
    maximo = max(por_hab.values(), default=0)
    for h in HABILIDADES + [k for k in por_hab if k not in HABILIDADES]:
        x = por_hab.get(h, 0.0)
        L.append(f"{h:<11} {barra(x, maximo)} {fmt(x / 60, 1):>5} h  {fmt(100 * x / total_v):>3} %")
    L.append("```\n")

    alertas = []
    if m["min_ventana"] > 0:
        inp = (por_hab.get("reading", 0) + por_hab.get("listening", 0)) / total_v
        out = (por_hab.get("speaking", 0) + por_hab.get("writing", 0)) / total_v
        if inp < 0.30:
            alertas.append(f"Input (reading + listening) en {100 * inp:.0f} %: sube la lectura o la escucha extensiva (objetivo ≈ 37,5 %).")
        if out < 0.25:
            alertas.append(f"Output (speaking + writing) en {100 * out:.0f} %: sin producción con feedback se fosilizan errores (objetivo ≈ 37,5 %).")
        if por_hab.get("vocabulary", 0) / total_v > 0.30:
            alertas.append("Más del 30 % del tiempo en vocabulario: baja las tarjetas nuevas de Anki y lee más.")
    if m["activas"] and m["dias_activos"] < 0.7 * v:
        alertas.append(f"Solo {m['dias_activos']} días activos de {v}: prioriza la constancia (usa la rutina de 60 min).")
    if m["futuras"]:
        alertas.append(f"{m['futuras']} sesión(es) con fecha futura no se cuentan: revisa la fecha.")

    # --- Semanas
    L.append("## Horas activas por semana (últimas 8)\n")
    L.append("```")
    lunes_actual = hoy - timedelta(days=hoy.weekday())
    semanas = []
    for i in range(7, -1, -1):
        ini = lunes_actual - timedelta(weeks=i)
        semanas.append((ini, sum(x for d, x in m["por_dia"].items() if ini <= d < ini + timedelta(days=7))))
    max_sem = max((x for _, x in semanas), default=0)
    for ini, x in semanas:
        L.append(f"{ini.isoformat()} {barra(x, max_sem)} {fmt(x / 60, 1):>5} h")
    L.append(f"(meta semanal: {fmt(meta_min_dia * 7 / 60, 1)} h)")
    L.append("```\n")

    # --- Evaluaciones
    L.append("## Nivel por habilidad (última evaluación, sin autoevaluaciones)\n")
    ultimas = ultimas_por_habilidad(evaluaciones, hoy)
    if ultimas:
        L.append("| Habilidad | MCER | Prueba | Puntaje | Fecha |")
        L.append("|---|---|---|---|---|")
        for h in HABILIDADES_EVAL + [k for k in ultimas if k not in HABILIDADES_EVAL]:
            if h in ultimas:
                e = ultimas[h]
                L.append(f"| {h} | **{e['cefr']}** | {e['prueba']} | {e['puntaje'] or '—'} | {e['fecha']} |")
        L.append("")
    else:
        L.append("Sin evaluaciones con nivel MCER. Haz el diagnóstico de la Fase 0 del plan.\n")

    def celda(e):
        return " ".join(x for x in (e["puntaje"], e["cefr"], f"({e['fecha']})") if x)

    por_prueba = defaultdict(list)
    for e in evaluaciones:
        if e["_fecha"] <= hoy and (a_float(e["puntaje"]) is not None or e["cefr"]):
            por_prueba[(e["prueba"], e["habilidad"])].append(e)
    if por_prueba:
        L.append("### Evolución por prueba\n")
        L.append("| Prueba | Habilidad | Primera | Última | Cambio | N |")
        L.append("|---|---|---|---|---|---|")
        for (prueba, hab), evs in sorted(por_prueba.items()):
            evs.sort(key=lambda e: e["_fecha"])
            a, b = evs[0], evs[-1]
            pa, pb = a_float(a["puntaje"]), a_float(b["puntaje"])
            if len(evs) == 1:
                cambio = "—"
            elif pa is not None and pb is not None:
                cambio = fmt(pb - pa, 0 if float(pb - pa).is_integer() else 1, signo=True)
            elif cefr_a_num(a["cefr"]) and cefr_a_num(b["cefr"]):
                cambio = f"{(cefr_a_num(b['cefr']) - cefr_a_num(a['cefr'])) * 2:+.0f} subnivel(es)"
            else:
                cambio = "—"
            L.append(f"| {prueba} | {hab} | {celda(a)} | {celda(b)} | {cambio} | {len(evs)} |")
        L.append("\nCambios pequeños entre dos mediciones pueden ser ruido (error de medida, efecto práctica): "
                 "fíjate en la tendencia de 3 o más.\n")

    # --- Proyección
    L.append(f"## Proyección hacia {objetivo}\n")
    p = proyeccion_horas(ultimas, m["activas"], hoy, objetivo)
    if p and m["prom"] > 0:
        f_min, f_max = FACTOR_AUTOESTUDIO
        d_min = p["restantes"] * f_min * 60 / m["prom"]
        d_max = p["restantes"] * f_max * 60 / m["prom"]
        ev = p["evaluacion"]
        L.append(f"**Modelo de horas.** Habilidad más débil: **{p['habilidad']} {num_a_cefr(p['nivel'])}** "
                 f"({ev['prueba']}, {ev['fecha']}) → referencia Cambridge ≈ {fmt(p['horas_base'])} h guiadas acumuladas.")
        L.append(f"- Horas de estudio activo desde esa evaluación: {fmt(p['horas_desde'], 1)} h.")
        if p["restantes"] > 0:
            L.append(f"- Faltan ≈ **{fmt(p['restantes'])} h guiadas equivalentes** para {objetivo} (≈ {fmt(HORAS_CEFR[objetivo])} h). "
                     f"A tu ritmo ({fmt(m['prom'])} min/día): **{(hoy + timedelta(days=d_min)).strftime('%Y-%m')} – "
                     f"{(hoy + timedelta(days=d_max)).strftime('%Y-%m')}** ({fmt(d_min / DIAS_MES)}–{fmt(d_max / DIAS_MES)} meses).")
        else:
            L.append(f"- Según las horas de referencia ya deberías rondar {objetivo}: confírmalo con un simulacro completo.")
        if p["antiguas"]:
            L.append(f"- Evaluaciones de más de {DIAS_VIGENCIA} días no usadas: {', '.join(p['antiguas'])}. Re-evalúalas.")
    else:
        L.append("**Modelo de horas:** necesitas al menos una evaluación con nivel MCER (sin contar vocabulary) "
                 "y sesiones activas registradas.")
    t = tendencia_efset(evaluaciones, hoy, objetivo)
    if t:
        L.append("")
        texto = (f"**Tendencia EF SET** (solo comprensión: reading + listening; {t['n']} mediciones): "
                 f"{fmt(t['pendiente_mes'], 1, signo=True)} puntos/mes, estimado hoy ≈ {fmt(t['estimado_hoy'])}")
        if t["fecha"] == hoy:
            texto += f" → ya en rango {objetivo} ({t['meta']}+). Confírmalo con EF SET 4-skill o un simulacro."
        elif t["fecha"]:
            texto += f" → {objetivo} ({t['meta']}) hacia **{t['fecha'].strftime('%Y-%m')}**."
        else:
            texto += " → sin tendencia positiva todavía."
        L.append(texto)
    L.append("")
    L.append("> Estimaciones orientativas. El modelo de horas usa las horas guiadas de Cambridge × un factor de "
             "autoestudio de 1,2–1,8 (supuesto). La tendencia es una extrapolación lineal: suele ser optimista "
             "porque el avance se frena en niveles altos. Lo que manda son tus evaluaciones mensuales.\n")

    # --- Próximas evaluaciones
    L.append("## Próximas evaluaciones sugeridas\n")
    for prueba, cada in RECORDATORIOS:
        fechas = [e["_fecha"] for e in evaluaciones if normalizar(e["prueba"]).startswith(normalizar(prueba))]
        if fechas:
            prox = max(fechas) + timedelta(days=cada)
            if prox < hoy:
                estado = "⚠️ vencida"
            elif prox == hoy:
                estado = "hoy"
            else:
                estado = f"en {(prox - hoy).days} días"
            L.append(f"- {prueba}: {prox.isoformat()} ({estado})")
        else:
            L.append(f"- {prueba}: ⚠️ pendiente (línea base)")
    L.append("")

    if alertas:
        L.append("## Alertas\n")
        L.extend(f"- {a}" for a in alertas)
        L.append("")

    return "\n".join(L)


# ---------------------------------------------------------------- CLI

def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # consolas de Windows sin UTF-8
        except AttributeError:
            pass

    ap = argparse.ArgumentParser(description="Tracker de progreso hacia C1")
    ap.add_argument("--datos", default=str(BASE / "data"), help="Carpeta con sesiones.csv y evaluaciones.csv")
    ap.add_argument("--meta", type=float, default=90, help="Meta de minutos de estudio activo por día (por defecto: 90)")
    ap.add_argument("--objetivo", default="C1", choices=CEFR_ORDEN[1:], help="Nivel objetivo")
    ap.add_argument("--hoy", type=fecha_arg, help="Fecha de referencia AAAA-MM-DD (por defecto: hoy)")
    ap.add_argument("--salida", help="Archivo del reporte (por defecto: <datos>/../reporte.md)")
    sub = ap.add_subparsers(dest="cmd")

    a = sub.add_parser("add", help="Registrar una sesión de estudio")
    a.add_argument("habilidad", type=str.lower, choices=HABILIDADES)
    a.add_argument("minutos", type=a_float)
    a.add_argument("actividad")
    a.add_argument("--pasivo", action="store_true", help="Escucha en tiempo muerto: no cuenta para la meta ni la proyección")
    a.add_argument("--cantidad", default="")
    a.add_argument("--unidad", default="", help="palabras, tarjetas, minutos-audio…")
    a.add_argument("--notas", default="")
    a.add_argument("--fecha", type=fecha_arg, default=None)

    t = sub.add_parser("test", help="Registrar una evaluación")
    t.add_argument("prueba", help='Ej.: "EF SET 50", "Vocabulary Size Test", "Write & Improve", "Speaking grabado"')
    t.add_argument("habilidad", type=str.lower, choices=HABILIDADES_EVAL)
    t.add_argument("--puntaje", default="")
    t.add_argument("--cefr", default="", help="A1…C2, con + opcional. En EF SET se deduce del puntaje si lo omites")
    t.add_argument("--notas", default="")
    t.add_argument("--fecha", type=fecha_arg, default=None)

    args = ap.parse_args(argv)
    if args.meta <= 0:
        ap.error("--meta debe ser mayor que 0")
    datos = Path(args.datos)
    ruta_s = datos / "sesiones.csv"
    ruta_e = datos / "evaluaciones.csv"
    hoy = args.hoy or date.today()

    if args.cmd == "add":
        if args.minutos is None or not 0 < args.minutos <= MAX_MINUTOS:
            ap.error(f"los minutos deben ser un número entre 1 y {MAX_MINUTOS}")
        if args.cantidad and a_float(args.cantidad) is None:
            ap.error("--cantidad debe ser un número")
        fecha = (args.fecha or hoy).isoformat()
        modo = "pasivo" if args.pasivo else "activo"
        agregar_fila(ruta_s, SESIONES_CAMPOS, {
            "fecha": fecha, "habilidad": args.habilidad, "actividad": args.actividad, "minutos": f"{args.minutos:g}",
            "modo": modo, "cantidad": args.cantidad, "unidad": args.unidad, "notas": args.notas})
        print(f"Sesión registrada: {fecha} · {args.habilidad} · {args.minutos:g} min · {modo}")
        return 0

    if args.cmd == "test":
        cefr = args.cefr.strip().upper()
        if cefr and cefr_a_num(cefr) is None:
            ap.error("--cefr debe ser A1, A2, B1, B2, C1 o C2 (opcionalmente con +)")
        if args.puntaje and a_float(args.puntaje) is None:
            ap.error("--puntaje debe ser un número")
        if es_efset(args.prueba) and args.puntaje:
            oficial = efset_a_cefr(args.puntaje)
            if not cefr:
                cefr = oficial
            elif cefr.rstrip("+") != oficial:
                print(f"Aviso: en EF SET, {args.puntaje} puntos corresponde a {oficial}, no a {cefr}.", file=sys.stderr)
        fecha = (args.fecha or hoy).isoformat()
        agregar_fila(ruta_e, EVALUACIONES_CAMPOS, {
            "fecha": fecha, "prueba": args.prueba, "habilidad": args.habilidad,
            "puntaje": args.puntaje, "cefr": cefr, "notas": args.notas})
        print(f"Evaluación registrada: {fecha} · {args.prueba} · {args.habilidad} · {cefr or '—'}")
        return 0

    sesiones = leer_csv(ruta_s, SESIONES_CAMPOS)
    evaluaciones = leer_csv(ruta_e, EVALUACIONES_CAMPOS)
    reporte = generar_reporte(sesiones, evaluaciones, hoy, args.meta, args.objetivo)
    print(reporte)
    salida = Path(args.salida) if args.salida else datos.parent / "reporte.md"
    salida.write_text(reporte + "\n", encoding="utf-8")
    print(f"\n(Reporte guardado en {salida})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
