# Tracker de progreso hacia C1

Dos herramientas que leen y escriben **el mismo formato de datos** (CSV). Usa la que te resulte más cómoda, o ambas.

```
tracker/
├── index.html          # Web app: registrar, dashboard con gráficas, exportar/importar
├── progress.py         # Script: registrar desde la terminal y generar un reporte Markdown
├── rubricas.md         # Protocolos y rúbricas para medir cada destreza
├── data/
│   ├── sesiones.csv    # Tus sesiones de estudio (vacío al inicio)
│   └── evaluaciones.csv# Tus pruebas y niveles MCER (vacío al inicio)
└── ejemplo/            # Datos de ejemplo (3 meses simulados) para ver cómo se ve
```

## Formato de datos

**`sesiones.csv`**: `fecha,habilidad,actividad,minutos,cantidad,unidad,notas`
- `habilidad`: `speaking`, `writing`, `listening`, `reading`, `grammar` o `vocabulary`
- `cantidad` + `unidad` (opcionales): p. ej. `3500,palabras` (lectura), `120,tarjetas` (Anki), `25,minutos-audio`

**`evaluaciones.csv`**: `fecha,prueba,habilidad,puntaje,cefr,notas`
- `habilidad`: `general` o una de las anteriores
- `cefr`: `A1`…`C2`, con `+` opcional (`B1+`)
- `prueba`: usa nombres constantes (`EF SET 50`, `Vocabulary Size Test`, `Write & Improve`, `Speaking grabado`, `Simulacro C1 Advanced`) para que las tendencias y los recordatorios funcionen.

## Opción 1: web app (`index.html`)

1. Abre `tracker/index.html` en el navegador (doble clic; no hace falta servidor ni instalar nada).
2. **Registrar**: botones rápidos con las actividades del plan → ajusta los minutos → guardar.
3. **Dashboard**: horas por semana y habilidad, distribución frente al plan (50/25/15/10), evolución del nivel MCER, tamaño del vocabulario, proyección de fecha para C1, alertas y próximas evaluaciones.
4. **Datos**: exporta `sesiones.csv` y `evaluaciones.csv` y guárdalos en `tracker/data/` (así quedan versionados en git y el script de Python los lee). También hay respaldo JSON.

> Los datos viven en el `localStorage` de tu navegador: si borras los datos del sitio o cambias de navegador o de equipo, se pierden. **Exporta cada semana.** Para ver las gráficas hace falta internet (Chart.js se carga desde jsDelivr); sin conexión funciona todo lo demás.

Para ver un ejemplo: pestaña *Datos* → *Importar CSV* → selecciona los dos archivos de `tracker/ejemplo/`.

## Opción 2: terminal (`progress.py`)

Requiere Python 3.9+ (solo la biblioteca estándar).

```bash
# Registrar una sesión (fecha = hoy por defecto; usa --fecha YYYY-MM-DD para otra)
python tracker/progress.py add reading 30 "Graded reader nivel 3" --cantidad 3500 --unidad palabras
python tracker/progress.py add speaking 15 "4/3/2 + shadowing"

# Registrar una evaluación
python tracker/progress.py test "EF SET 50" general --puntaje 52 --cefr B1+
python tracker/progress.py test "Vocabulary Size Test" vocabulary --puntaje 4200 --cefr B1+

# Generar el reporte (se imprime y se guarda en tracker/reporte.md)
python tracker/progress.py
python tracker/progress.py --meta 120          # meta de 120 min/día
python tracker/progress.py --datos tracker/ejemplo --hoy 2026-09-25   # ver el ejemplo
```

Ejemplo de salida: [`ejemplo/reporte.md`](ejemplo/reporte.md).

## Qué mide y cómo interpretarlo

| Métrica | Para qué |
|---|---|
| Horas por día y semana, racha, días activos | **Constancia**: el principal predictor práctico del progreso |
| Distribución por habilidad frente al plan | Detectar desequilibrios (poco input, poco output, demasiado Anki) |
| Palabras leídas por mes | Volumen de lectura extensiva (meta: 100k+ en B1-B2, 150k+ en B2-C1) |
| MCER por habilidad | Nivel real medido con pruebas externas y rúbricas |
| Tamaño del vocabulario | Progreso hacia ~8.000 familias (98 % de cobertura de textos) |
| Proyección | Fecha estimada para C1 según tu ritmo real (referencia: horas guiadas de Cambridge × factor de autoestudio 1.2–1.8) |

La proyección es **orientativa**: se basa en tu habilidad más débil y en tu ritmo de los últimos 28 días. Lo que manda son las evaluaciones mensuales.
