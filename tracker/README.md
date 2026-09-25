# Tracker de progreso hacia C1

Dos herramientas que leen y escriben **el mismo formato de datos** (CSV). Usa la que te resulte más cómoda, o las dos.

```
tracker/
├── index.html           # Web app: registrar, dashboard con gráficas, exportar/importar (funciona sin internet)
├── progress.py          # Script: registrar desde la terminal y generar un reporte en Markdown
├── test_progress.py     # Tests del script (python -m unittest discover -s tracker)
├── rubricas.md          # Protocolos y rúbricas para medir cada destreza
├── vendor/              # Chart.js 4.4.1 (licencia MIT) incluido para que las gráficas funcionen offline
├── data/
│   ├── sesiones.csv     # Tus sesiones de estudio (vacío al inicio)
│   └── evaluaciones.csv # Tus pruebas y niveles MCER (vacío al inicio)
└── ejemplo/             # 12 semanas simuladas + su reporte, para ver cómo se ve
```

## Formato de datos

**`sesiones.csv`**: `fecha,habilidad,actividad,minutos,modo,cantidad,unidad,notas`
- `habilidad`: `speaking`, `writing`, `listening`, `reading`, `grammar` o `vocabulary`.
- `modo`: `activo` (por defecto) o `pasivo`. El modo pasivo es la escucha en tiempo muerto: suma exposición, pero no cuenta para la meta, la racha ni la proyección.
- `cantidad` + `unidad` (opcionales): p. ej. `3500,palabras` (lectura), `120,tarjetas` (Anki), `25,minutos-audio`.

**`evaluaciones.csv`**: `fecha,prueba,habilidad,puntaje,cefr,notas`
- `habilidad`: `general` o una de las anteriores.
- `cefr`: `A1`…`C2`, con `+` opcional (`B1+`). En **EF SET** se deduce del puntaje si lo dejas vacío. En **vocabulario**, déjalo vacío.
- `prueba`: usa estos nombres para que funcionen las tendencias y los recordatorios: `EF SET 50`, `EF SET 4-skill`, `Vocabulary Size Test`, `Write & Improve`, `Speaking grabado`, `Autoevaluación MCER`, `Simulacro C1 Advanced`.

Ambas herramientas aceptan CSV separados por **coma o punto y coma** (el formato de Excel en español), con **coma decimal** y con o sin BOM. Si una fila tiene una fecha inválida, la ignoran y avisan.

## Opción 1: web app (`index.html`)

1. **Abrir:** doble clic en `tracker/index.html`. No hace falta servidor, instalación ni internet.
2. **Registrar:** botones rápidos con las actividades de los 4 hilos del plan (incluida la *escucha pasiva*) → ajusta los minutos → guardar.
3. **Dashboard:**
   - horas activas por semana y por habilidad;
   - reparto del tiempo frente al plan;
   - evolución del nivel MCER (eje de tiempo real);
   - tamaño de vocabulario con referencias de cobertura;
   - proyección hacia C1, alertas y próximas evaluaciones.
4. **Datos:** exporta `sesiones.csv` y `evaluaciones.csv` y guárdalos en `tracker/data/`. Así quedan versionados en git y el script de Python los lee. También hay respaldo en JSON.

> Los datos viven en el `localStorage` de tu navegador. Si borras los datos del sitio o cambias de navegador o de equipo, se pierden: **exporta cada semana**.

**Para ver el ejemplo:** pestaña *Datos* → *Importar CSV* → selecciona los dos archivos de `tracker/ejemplo/`.

## Opción 2: terminal (`progress.py`)

Requiere Python 3.9 o superior; solo usa la biblioteca estándar.

```bash
# Registrar una sesión (fecha = hoy por defecto; usa --fecha AAAA-MM-DD para otra)
python tracker/progress.py add reading 30 "Graded reader nivel 3" --cantidad 3500 --unidad palabras
python tracker/progress.py add speaking 15 "4/3/2"
python tracker/progress.py add listening 40 "Podcast en el bus" --pasivo

# Registrar una evaluación (en EF SET el MCER se deduce del puntaje)
python tracker/progress.py test "EF SET 50" general --puntaje 52
python tracker/progress.py test "Vocabulary Size Test" vocabulary --puntaje 4200
python tracker/progress.py test "Speaking grabado" speaking --puntaje 92 --cefr B1+ --notas "L1=160 ppm; evaluador=tutor"

# Generar el reporte (se imprime y se guarda en tracker/reporte.md)
python tracker/progress.py
python tracker/progress.py --meta 120                                  # meta de 120 min/día
python tracker/progress.py --datos tracker/ejemplo --hoy 2026-09-25    # ver el ejemplo

# Ejecutar los tests
python -m unittest discover -s tracker
```

Ejemplo de salida: [`ejemplo/reporte.md`](ejemplo/reporte.md).

## Qué mide y cómo interpretarlo

| Métrica | Para qué sirve |
|---|---|
| Minutos activos por día y semana, racha, días activos | **Constancia**: el principal predictor práctico del progreso |
| Reparto del tiempo frente al plan (37,5 / 37,5 / 15 / 10) | Detectar desequilibrios entre los 4 hilos: poco input, poco output o demasiado Anki |
| Escucha pasiva | Exposición extra, fuera de la meta |
| Palabras leídas por mes | Volumen de lectura extensiva (meta: 100.000+ en B1–B2 y 150.000+ en B2–C1) |
| MCER por habilidad | Nivel medido con pruebas externas y rúbricas; las autoevaluaciones no cuentan |
| Tamaño de vocabulario | Cobertura léxica (95 % / 98 %); no es un nivel MCER |
| **Modelo de horas** | Fecha estimada para C1 desde tu habilidad más débil (las evaluaciones de más de 120 días solo se usan si no hay otras más recientes) y tu ritmo de los últimos 28 días |
| **Tendencia EF SET** | Regresión de tus puntajes (≥ 3 mediciones en ≥ 8 semanas): tu ritmo real en comprensión |

Las dos proyecciones son **orientativas**. El modelo de horas usa las horas guiadas de Cambridge × un factor de autoestudio de 1,2–1,8, que es un supuesto. La tendencia es lineal y suele ser optimista, porque el avance se frena en niveles altos. Lo que manda son tus evaluaciones mensuales.
