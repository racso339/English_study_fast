#!/usr/bin/env python3
"""Tracker de progreso hacia C1.

Lee tracker/data/sesiones.csv y tracker/data/evaluaciones.csv (el mismo formato
que exporta la web app tracker/index.html) y genera un reporte en Markdown.

Uso:
    python tracker/progress.py                      # imprime el reporte y lo guarda en tracker/reporte.md
    python tracker/progress.py add reading 30 "Graded reader nivel 3" --cantidad 3500 --unidad palabras
    python tracker/progress.py test "EF SET 50" general --puntaje 58 --cefr B2
    python tracker/progress.py --datos tracker/ejemplo   # usar otra carpeta de datos

Solo usa la biblioteca estándar de Python 3.9+.
"""

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
SESIONES_CAMPOS = ["fecha", "habilidad", "actividad", "minutos", "cantidad", "unidad", "notas"]
EVALUACIONES_CAMPOS = ["fecha", "prueba", "habilidad", "puntaje", "cefr", "notas"]
HABILIDADES = ["speaking", "writing", "listening", "reading", "grammar", "vocabulary"]
HABILIDADES_EVAL = ["general"] + HABILIDADES

# Horas guiadas acumuladas orientativas de Cambridge (punto medio del rango).
# Son horas GUIADAS, no de autoestudio: úsalas solo como referencia.
HORAS_CEFR = {"A1": 95, "A2": 190, "B1": 375, "B2": 550, "C1": 750, "C2": 1100}
CEFR_ORDEN = ["A1", "A2", "B1", "B2", "C1", "C2"]


def cefr_a_num(cefr):
    """'B1' -> 3.0, 'B1+' -> 3.5. Devuelve None si no es válido."""
    if not cefr:
        return None
    c = cefr.strip().upper()
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


def a_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_fecha(s):
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def leer_csv(ruta, campos):
    if not ruta.exists():
        return []
    filas = []
    with ruta.open(newline="", encoding="utf-8") as f:
        for i, fila in enumerate(csv.DictReader(f), start=2):
            try:
                fila["_fecha"] = parse_fecha(fila["fecha"])
            except (KeyError, ValueError, AttributeError):
                print(f"Aviso: {ruta.name} línea {i}: fecha inválida, se ignora.", file=sys.stderr)
                continue
            filas.append({k: (fila.get(k) or "").strip() for k in campos} | {"_fecha": fila["_fecha"]})
    return filas


def agregar_fila(ruta, campos, fila):
    nuevo = not ruta.exists() or ruta.stat().st_size == 0
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        if nuevo:
            w.writeheader()
        w.writerow(fila)


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


def generar_reporte(sesiones, evaluaciones, hoy, meta_min_dia, objetivo):
    L = []
    L.append(f"# Reporte de progreso — {hoy.isoformat()}\n")

    if not sesiones and not evaluaciones:
        L.append("Aún no hay datos. Registra tu primera sesión con la web app o con:\n")
        L.append('`python tracker/progress.py add reading 30 "Graded reader" --cantidad 3000 --unidad palabras`\n')
        return "\n".join(L)

    minutos_por_dia = defaultdict(float)
    min_hab = defaultdict(float)
    min_hab_28 = defaultdict(float)
    palabras_leidas = 0.0
    palabras_mes = 0.0
    inicio_28 = hoy - timedelta(days=27)
    inicio_mes = hoy.replace(day=1)
    for s in sesiones:
        m = a_float(s["minutos"]) or 0.0
        minutos_por_dia[s["_fecha"]] += m
        min_hab[s["habilidad"]] += m
        if s["_fecha"] >= inicio_28:
            min_hab_28[s["habilidad"]] += m
        if s["unidad"].lower().startswith("palabra"):
            c = a_float(s["cantidad"]) or 0.0
            palabras_leidas += c
            if s["_fecha"] >= inicio_mes:
                palabras_mes += c

    total_h = sum(min_hab.values()) / 60
    h_28 = sum(min_hab_28.values()) / 60
    dias_activos_28 = sum(1 for d, m in minutos_por_dia.items() if d >= inicio_28 and m > 0)
    # Si llevas menos de 28 días, el promedio se calcula sobre los días transcurridos.
    primer_dia = min(minutos_por_dia, default=hoy)
    ventana = max(1, min(28, (hoy - primer_dia).days + 1))
    prom_dia_28 = h_28 * 60 / ventana
    dias_estudio = {d for d, m in minutos_por_dia.items() if m > 0}

    # --- Resumen
    L.append("## Resumen\n")
    L.append("| Métrica | Valor |")
    L.append("|---|---|")
    L.append(f"| Horas totales registradas | **{total_h:.1f} h** |")
    L.append(f"| Horas últimos 28 días | {h_28:.1f} h ({dias_activos_28}/{ventana} días activos) |")
    L.append(f"| Promedio diario (28 días) | {prom_dia_28:.0f} min (meta: {meta_min_dia:.0f} min) |")
    L.append(f"| Cumplimiento de la meta (28 días) | {min(100, 100 * prom_dia_28 / meta_min_dia):.0f} % |")
    L.append(f"| Racha actual | {racha(dias_estudio, hoy)} días |")
    L.append(f"| Palabras leídas (total / este mes) | {palabras_leidas:,.0f} / {palabras_mes:,.0f} |")
    L.append("")

    # --- Distribución por habilidad
    L.append("## Tiempo por habilidad (últimos 28 días)\n")
    L.append("Referencia del plan: input (reading + listening) ≈ 50 %, output (speaking + writing) ≈ 25 %, vocabulary ≈ 15 %, grammar ≈ 10 %.\n")
    L.append("```")
    total_28 = sum(min_hab_28.values()) or 1
    maximo = max(min_hab_28.values(), default=0)
    for h in HABILIDADES:
        m = min_hab_28.get(h, 0.0)
        L.append(f"{h:<11} {barra(m, maximo)} {m / 60:5.1f} h  {100 * m / total_28:4.0f} %")
    otros = {k: v for k, v in min_hab_28.items() if k not in HABILIDADES}
    for h, m in otros.items():
        L.append(f"{h:<11} {barra(m, maximo)} {m / 60:5.1f} h  {100 * m / total_28:4.0f} %")
    L.append("```\n")
    inp = min_hab_28.get("reading", 0) + min_hab_28.get("listening", 0)
    out = min_hab_28.get("speaking", 0) + min_hab_28.get("writing", 0)
    alertas = []
    if sum(min_hab_28.values()) > 0:
        if inp / total_28 < 0.40:
            alertas.append("Input (reading + listening) por debajo del 40 %: sube la lectura o la escucha extensiva.")
        if out / total_28 < 0.15:
            alertas.append("Output (speaking + writing) por debajo del 15 %: sin producción se fosilizan errores.")
        if min_hab_28.get("vocabulary", 0) / total_28 > 0.30:
            alertas.append("Más del 30 % del tiempo en vocabulario: baja las tarjetas nuevas y lee más.")
    if sesiones and dias_activos_28 < 0.7 * ventana:
        alertas.append(f"Solo {dias_activos_28} días activos de {ventana}: prioriza la constancia (usa la rutina de 60 min).")

    # --- Semanas
    L.append("## Horas por semana (últimas 8)\n")
    L.append("```")
    lunes_actual = hoy - timedelta(days=hoy.weekday())
    semanas = []
    for i in range(7, -1, -1):
        ini = lunes_actual - timedelta(weeks=i)
        m = sum(v for d, v in minutos_por_dia.items() if ini <= d < ini + timedelta(days=7))
        semanas.append((ini, m))
    max_sem = max((m for _, m in semanas), default=0)
    for ini, m in semanas:
        L.append(f"{ini.isoformat()} {barra(m, max_sem)} {m / 60:5.1f} h")
    L.append(f"(meta semanal: {meta_min_dia * 7 / 60:.1f} h)")
    L.append("```\n")

    # --- Evaluaciones
    L.append("## Nivel por habilidad (última evaluación)\n")
    ultimas = {}
    for e in sorted(evaluaciones, key=lambda x: x["_fecha"]):
        if cefr_a_num(e["cefr"]) is not None:
            ultimas[e["habilidad"]] = e
    if ultimas:
        L.append("| Habilidad | MCER | Prueba | Puntaje | Fecha |")
        L.append("|---|---|---|---|---|")
        for h in HABILIDADES_EVAL:
            if h in ultimas:
                e = ultimas[h]
                L.append(f"| {h} | **{e['cefr'].upper()}** | {e['prueba']} | {e['puntaje'] or '—'} | {e['fecha']} |")
        L.append("")
    else:
        L.append("Sin evaluaciones con nivel MCER. Haz el diagnóstico de la Fase 0 del plan.\n")

    # Tendencias por prueba (primer vs. último puntaje)
    por_prueba = defaultdict(list)
    for e in evaluaciones:
        p = a_float(e["puntaje"])
        if p is not None:
            por_prueba[(e["prueba"], e["habilidad"])].append((e["_fecha"], p, e["cefr"]))
    if por_prueba:
        L.append("### Evolución de puntajes\n")
        L.append("| Prueba | Habilidad | Primero | Último | Cambio | N |")
        L.append("|---|---|---|---|---|---|")
        for (prueba, hab), vals in sorted(por_prueba.items()):
            vals.sort()
            f0, p0, c0 = vals[0]
            f1, p1, c1 = vals[-1]
            L.append(f"| {prueba} | {hab} | {p0:g} {c0} ({f0}) | {p1:g} {c1} ({f1}) | {p1 - p0:+g} | {len(vals)} |")
        L.append("")

    # --- Proyección
    L.append(f"## Proyección hacia {objetivo}\n")
    niveles = [cefr_a_num(e["cefr"]) for e in ultimas.values() if e["habilidad"] in ("general",) + tuple(HABILIDADES)]
    niveles = [n for n in niveles if n is not None]
    if niveles and prom_dia_28 > 0:
        # Se toma la habilidad más débil: el C1 real exige todas.
        nivel_min = min(niveles)
        base_cefr = num_a_cefr(nivel_min).rstrip("+")
        horas_base = HORAS_CEFR[base_cefr]
        if nivel_min - int(nivel_min) >= 0.5:
            siguiente = CEFR_ORDEN[min(CEFR_ORDEN.index(base_cefr) + 1, 5)]
            horas_base = (horas_base + HORAS_CEFR[siguiente]) / 2
        fecha_ref = max(e["_fecha"] for e in ultimas.values())
        horas_desde = sum(a_float(s["minutos"]) or 0 for s in sesiones if s["_fecha"] > fecha_ref) / 60
        restantes = max(0.0, HORAS_CEFR[objetivo] - horas_base - horas_desde)
        # Factor de autoestudio 1.2–1.8 (horas propias vs. horas guiadas; ver investigación §9)
        dias_min = restantes * 1.2 * 60 / prom_dia_28
        dias_max = restantes * 1.8 * 60 / prom_dia_28
        L.append(f"- Habilidad más débil: **{num_a_cefr(nivel_min)}** → referencia Cambridge ≈ {horas_base:.0f} h guiadas acumuladas.")
        L.append(f"- Horas registradas desde la última evaluación: {horas_desde:.1f} h.")
        L.append(f"- Horas guiadas equivalentes que faltan para {objetivo} (≈ {HORAS_CEFR[objetivo]} h): **{restantes:.0f} h**.")
        L.append(f"- A tu ritmo actual ({prom_dia_28:.0f} min/día): **{(hoy + timedelta(days=dias_min)).strftime('%Y-%m')} – "
                 f"{(hoy + timedelta(days=dias_max)).strftime('%Y-%m')}** ({dias_min / 30:.0f}–{dias_max / 30:.0f} meses).")
        L.append("- *Estimación orientativa*: las horas de Cambridge son guiadas; el rango aplica un factor de autoestudio de 1.2–1.8. "
                 "La escucha pasiva extra y la constancia pueden adelantarla. Re-evalúa cada 4 semanas.")
    else:
        L.append("Necesitas al menos una evaluación con nivel MCER y sesiones en los últimos 28 días.")
    L.append("")

    # --- Próximas evaluaciones
    L.append("## Próximas evaluaciones sugeridas\n")
    reglas = [("EF SET 50", 28), ("Write & Improve", 28), ("Speaking grabado", 28), ("Vocabulary Size Test", 56)]
    for prueba, cada in reglas:
        fechas = [e["_fecha"] for e in evaluaciones if e["prueba"].lower().startswith(prueba.lower().split()[0])]
        if fechas:
            prox = max(fechas) + timedelta(days=cada)
            estado = "⚠️ VENCIDA" if prox <= hoy else f"en {(prox - hoy).days} días"
            L.append(f"- {prueba}: {prox.isoformat()} ({estado})")
        else:
            L.append(f"- {prueba}: ⚠️ pendiente (línea base)")
    L.append("")

    if alertas:
        L.append("## Alertas\n")
        for a in alertas:
            L.append(f"- {a}")
        L.append("")

    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Tracker de progreso hacia C1")
    ap.add_argument("--datos", default=str(BASE / "data"), help="Carpeta con sesiones.csv y evaluaciones.csv")
    ap.add_argument("--meta", type=float, default=90, help="Meta de minutos por día (por defecto: 90)")
    ap.add_argument("--objetivo", default="C1", choices=CEFR_ORDEN[1:], help="Nivel objetivo")
    ap.add_argument("--hoy", help="Fecha de referencia YYYY-MM-DD (por defecto: hoy)")
    ap.add_argument("--salida", help="Archivo del reporte (por defecto: <datos>/../reporte.md)")
    sub = ap.add_subparsers(dest="cmd")

    a = sub.add_parser("add", help="Registrar una sesión de estudio")
    a.add_argument("habilidad", choices=HABILIDADES)
    a.add_argument("minutos", type=float)
    a.add_argument("actividad")
    a.add_argument("--cantidad", default="")
    a.add_argument("--unidad", default="", help="palabras, tarjetas, minutos-audio…")
    a.add_argument("--notas", default="")
    a.add_argument("--fecha", default=None)

    t = sub.add_parser("test", help="Registrar una evaluación")
    t.add_argument("prueba", help='Ej.: "EF SET 50", "Vocabulary Size Test", "Write & Improve", "Speaking grabado"')
    t.add_argument("habilidad", choices=HABILIDADES_EVAL)
    t.add_argument("--puntaje", default="")
    t.add_argument("--cefr", default="")
    t.add_argument("--notas", default="")
    t.add_argument("--fecha", default=None)

    args = ap.parse_args(argv)
    datos = Path(args.datos)
    ruta_s = datos / "sesiones.csv"
    ruta_e = datos / "evaluaciones.csv"
    hoy = parse_fecha(args.hoy) if args.hoy else date.today()

    if args.cmd == "add":
        fecha = args.fecha or hoy.isoformat()
        parse_fecha(fecha)
        agregar_fila(ruta_s, SESIONES_CAMPOS, {
            "fecha": fecha, "habilidad": args.habilidad, "actividad": args.actividad,
            "minutos": f"{args.minutos:g}", "cantidad": args.cantidad, "unidad": args.unidad, "notas": args.notas})
        print(f"Sesión registrada: {fecha} · {args.habilidad} · {args.minutos:g} min")
        return 0
    if args.cmd == "test":
        fecha = args.fecha or hoy.isoformat()
        parse_fecha(fecha)
        if args.cefr and cefr_a_num(args.cefr) is None:
            ap.error("--cefr debe ser A1, A2, B1, B2, C1 o C2 (opcionalmente con +)")
        agregar_fila(ruta_e, EVALUACIONES_CAMPOS, {
            "fecha": fecha, "prueba": args.prueba, "habilidad": args.habilidad,
            "puntaje": args.puntaje, "cefr": args.cefr.upper(), "notas": args.notas})
        print(f"Evaluación registrada: {fecha} · {args.prueba} · {args.habilidad} · {args.cefr.upper() or '—'}")
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
