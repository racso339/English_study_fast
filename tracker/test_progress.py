"""Tests de tracker/progress.py.  Ejecutar:  python -m unittest discover -s tracker -v"""

import contextlib
import io
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import progress as pg  # noqa: E402

HOY = date(2026, 9, 25)
CAB_S = "fecha,habilidad,actividad,minutos,modo,cantidad,unidad,notas\n"
CAB_E = "fecha,prueba,habilidad,puntaje,cefr,notas\n"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def archivo(self, nombre, contenido):
        ruta = self.dir / nombre
        ruta.write_bytes(contenido.encode("utf-8") if isinstance(contenido, str) else contenido)
        return ruta

    def ejecutar(self, *args):
        salida, errores = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(errores):
            try:
                codigo = pg.main(["--datos", str(self.dir), "--salida", str(self.dir / "reporte.md"), *args])
            except SystemExit as fin:  # argparse termina así ante un error de uso
                codigo = fin.code
        return codigo, salida.getvalue(), errores.getvalue()


class Numeros(unittest.TestCase):
    def test_coma_decimal_miles_y_valores_invalidos(self):
        self.assertEqual(pg.a_float("1,5"), 1.5)
        self.assertEqual(pg.a_float("4.400"), 4400)
        self.assertEqual(pg.a_float("3.5"), 3.5)
        for invalido in ("", "abc", "nan", "inf", None):
            self.assertIsNone(pg.a_float(invalido))

    def test_bandas_ef_set(self):
        self.assertEqual([pg.efset_a_cefr(x) for x in (30, 31, 41, 50, 51, 60, 61, 71)],
                         ["A1", "A2", "B1", "B1", "B2", "B2", "C1", "C2"])


class LecturaCSV(Base):
    def test_bom_de_excel(self):
        ruta = self.archivo("sesiones.csv", b"\xef\xbb\xbf" + (CAB_S + "2026-09-20,reading,x,30,,,,\n").encode())
        filas = pg.leer_csv(ruta, pg.SESIONES_CAMPOS)
        self.assertEqual(len(filas), 1)

    def test_punto_y_coma_y_coma_decimal(self):
        ruta = self.archivo("sesiones.csv", CAB_S.replace(",", ";") + "2026-09-20;Reading;x;1,5;;;;\n")
        filas = pg.leer_csv(ruta, pg.SESIONES_CAMPOS)
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["habilidad"], "reading")
        self.assertEqual(pg.minutos(filas[0]), 1.5)

    def test_csv_antiguo_sin_columna_modo(self):
        ruta = self.archivo("sesiones.csv", "fecha,habilidad,actividad,minutos,cantidad,unidad,notas\n2026-09-20,reading,x,30,,,\n")
        self.assertEqual(pg.leer_csv(ruta, pg.SESIONES_CAMPOS)[0]["modo"], "activo")

    def test_ef_set_sin_mcer_se_deduce(self):
        ruta = self.archivo("evaluaciones.csv", CAB_E + "2026-09-20,EF SET 50,general,53,,\n")
        self.assertEqual(pg.leer_csv(ruta, pg.EVALUACIONES_CAMPOS)[0]["cefr"], "B2")


class EscrituraCSV(Base):
    def test_archivo_sin_salto_final_no_pega_filas(self):
        ruta = self.archivo("sesiones.csv", CAB_S + "2026-09-20,reading,x,30,activo,,,")
        pg.agregar_fila(ruta, pg.SESIONES_CAMPOS, {"fecha": "2026-09-21", "habilidad": "speaking", "minutos": "10"})
        self.assertEqual(len(pg.leer_csv(ruta, pg.SESIONES_CAMPOS)), 2)

    def test_finales_de_linea_lf(self):
        ruta = self.dir / "nuevo.csv"
        pg.agregar_fila(ruta, pg.SESIONES_CAMPOS, {"fecha": "2026-09-21", "habilidad": "speaking", "minutos": "10"})
        pg.agregar_fila(ruta, pg.SESIONES_CAMPOS, {"fecha": "2026-09-22", "habilidad": "reading", "minutos": "20"})
        self.assertNotIn(b"\r", ruta.read_bytes())

    def test_respeta_punto_y_coma(self):
        ruta = self.archivo("sesiones.csv", CAB_S.replace(",", ";") + "2026-09-20;reading;x;30;activo;;;\n")
        pg.agregar_fila(ruta, pg.SESIONES_CAMPOS, {"fecha": "2026-09-21", "habilidad": "speaking", "minutos": "10"})
        self.assertTrue(ruta.read_text().splitlines()[-1].startswith("2026-09-21;speaking"))
        self.assertEqual(len(pg.leer_csv(ruta, pg.SESIONES_CAMPOS)), 2)

    def test_migra_cabecera_antigua_sin_perder_datos(self):
        ruta = self.archivo("sesiones.csv", "fecha,habilidad,actividad,minutos,cantidad,unidad,notas\n2026-09-20,reading,x,30,3000,palabras,hola\n")
        pg.agregar_fila(ruta, pg.SESIONES_CAMPOS, {"fecha": "2026-09-21", "habilidad": "listening", "minutos": "40", "modo": "pasivo"})
        filas = pg.leer_csv(ruta, pg.SESIONES_CAMPOS)
        self.assertEqual(ruta.read_text().splitlines()[0], ",".join(pg.SESIONES_CAMPOS))
        self.assertEqual((filas[0]["cantidad"], filas[0]["notas"]), ("3000", "hola"))
        self.assertEqual(filas[1]["modo"], "pasivo")


def sesion(fecha, habilidad="reading", minutos=60, modo="activo", cantidad="", unidad=""):
    return {"fecha": fecha.isoformat(), "_fecha": fecha, "habilidad": habilidad, "actividad": "x",
            "minutos": str(minutos), "modo": modo, "cantidad": cantidad, "unidad": unidad, "notas": ""}


def evaluacion(fecha, prueba, habilidad, puntaje="", cefr=""):
    return {"fecha": fecha.isoformat(), "_fecha": fecha, "prueba": prueba, "habilidad": habilidad,
            "puntaje": str(puntaje), "cefr": cefr, "notas": ""}


class Metricas(unittest.TestCase):
    def test_sesiones_futuras_no_cuentan(self):
        m = pg.calcular_metricas([sesion(HOY - timedelta(days=1)), sesion(HOY + timedelta(days=60), minutos=600)], HOY)
        self.assertEqual(m["min_ventana"], 60)
        self.assertEqual(m["dias_activos"], 1)
        self.assertEqual(m["futuras"], 1)

    def test_escucha_pasiva_no_cuenta_para_la_meta(self):
        m = pg.calcular_metricas([sesion(HOY), sesion(HOY, "listening", 120, "pasivo")], HOY)
        self.assertEqual(m["prom"], 60)
        self.assertEqual(m["pasivo_ventana_h"], 2)
        self.assertNotIn("listening", m["por_hab"])

    def test_palabras_con_unidad_en_mayusculas(self):
        m = pg.calcular_metricas([sesion(HOY, cantidad="4.000", unidad="Palabras")], HOY)
        self.assertEqual(m["palabras"], 4000)


class Proyeccion(unittest.TestCase):
    def test_horas_desde_la_evaluacion_de_la_habilidad_mas_debil(self):
        inicio = HOY - timedelta(days=30)
        sesiones = [sesion(inicio + timedelta(days=i), minutos=120) for i in range(1, 30)]
        evals = [evaluacion(inicio, "Speaking grabado", "speaking", 80, "B1"),
                 evaluacion(HOY - timedelta(days=1), "EF SET 50", "general", 56, "B2")]
        p = pg.proyeccion_horas(pg.ultimas_por_habilidad(evals, HOY), sesiones, HOY, "C1")
        self.assertEqual(p["habilidad"], "speaking")
        self.assertAlmostEqual(p["horas_desde"], 58)  # 29 días x 2 h desde la evaluación de speaking
        self.assertAlmostEqual(p["restantes"], 750 - 375 - 58)

    def test_vocabulario_no_define_la_habilidad_mas_debil(self):
        evals = [evaluacion(HOY, "Vocabulary Size Test", "vocabulary", 2000, "A2"),
                 evaluacion(HOY, "EF SET 50", "general", 45, "B1")]
        p = pg.proyeccion_horas(pg.ultimas_por_habilidad(evals, HOY), [], HOY, "C1")
        self.assertEqual(p["habilidad"], "general")

    def test_evaluaciones_antiguas_se_ignoran_si_hay_recientes(self):
        evals = [evaluacion(HOY - timedelta(days=200), "Speaking grabado", "speaking", 60, "A2"),
                 evaluacion(HOY - timedelta(days=5), "EF SET 50", "general", 52, "B2")]
        p = pg.proyeccion_horas(pg.ultimas_por_habilidad(evals, HOY), [], HOY, "C1")
        self.assertEqual((p["habilidad"], p["antiguas"]), ("general", ["speaking"]))

    def test_empate_prefiere_una_destreza_concreta(self):
        evals = [evaluacion(HOY, "EF SET 50", "general", 45, "B1"), evaluacion(HOY, "EF SET 50", "listening", 44, "B1")]
        p = pg.proyeccion_horas(pg.ultimas_por_habilidad(evals, HOY), [], HOY, "C1")
        self.assertEqual(p["habilidad"], "listening")

    def test_autoevaluacion_no_pisa_el_nivel_medido(self):
        evals = [evaluacion(HOY - timedelta(days=2), "EF SET 50", "general", 45),
                 evaluacion(HOY, "Autoevaluación MCER", "general", "", "C1")]
        ultimas = pg.ultimas_por_habilidad([dict(e, cefr=e["cefr"] or pg.efset_a_cefr(e["puntaje"])) for e in evals], HOY)
        self.assertEqual(ultimas["general"]["prueba"], "EF SET 50")

    def test_tendencia_ef_set(self):
        evals = [evaluacion(HOY - timedelta(days=d), "EF SET 50", "general", s)
                 for d, s in ((90, 44), (60, 47), (30, 50), (0, 53))]
        t = pg.tendencia_efset(evals, HOY, "C1")
        self.assertAlmostEqual(t["pendiente_mes"], 3.044, places=2)
        self.assertEqual(t["fecha"], HOY + timedelta(days=80))  # 8 puntos a 0,1 puntos/día

    def test_tendencia_requiere_tres_puntos_en_ocho_semanas(self):
        evals = [evaluacion(HOY - timedelta(days=d), "EF SET 50", "general", s) for d, s in ((20, 44), (10, 47), (0, 50))]
        self.assertIsNone(pg.tendencia_efset(evals, HOY, "C1"))


class CLI(Base):
    def test_meta_cero_da_error_claro(self):
        codigo, _, err = self.ejecutar("--meta", "0")
        self.assertEqual(codigo, 2)
        self.assertIn("--meta debe ser mayor que 0", err)

    def test_fecha_invalida_da_error_claro(self):
        codigo, _, err = self.ejecutar("add", "reading", "30", "x", "--fecha", "2026-13-01")
        self.assertEqual(codigo, 2)
        self.assertIn("fecha inválida", err)

    def test_minutos_fuera_de_rango(self):
        for valor in ("-30", "0", "601", "abc"):
            codigo, _, err = self.ejecutar("add", "reading", valor, "x")
            self.assertEqual(codigo, 2, valor)
            self.assertIn("minutos", err)
        self.assertFalse((self.dir / "sesiones.csv").exists())

    def test_add_pasivo_y_test_ef_set(self):
        self.ejecutar("add", "listening", "40", "Podcast", "--pasivo", "--fecha", "2026-09-20")
        self.ejecutar("test", "EF SET 50", "general", "--puntaje", "58", "--fecha", "2026-09-20")
        self.assertIn(",pasivo,", (self.dir / "sesiones.csv").read_text())
        self.assertIn(",58,B2,", (self.dir / "evaluaciones.csv").read_text())

    def test_reporte_sin_datos(self):
        codigo, salida, _ = self.ejecutar("--hoy", "2026-09-25")
        self.assertEqual(codigo, 0)
        self.assertIn("Aún no hay datos", salida)


if __name__ == "__main__":
    unittest.main()
