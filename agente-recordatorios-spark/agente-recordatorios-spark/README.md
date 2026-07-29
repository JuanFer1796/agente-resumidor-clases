# ☀️ Agente de Recordatorios Spark

Cada mañana a las **6:00 AM (hora de Guatemala)** este agente elige una frase al azar
del corpus de la clase **Spark**, la reescribe con **Gemini** conectándola con tu vida
—el banco, correr, programar, el Arsenal, los animes, *Beating Wall Street*— y te la
manda por **Telegram**.

Corre en **GitHub Actions**, así que tu PC puede estar apagada.

---

## 📦 Qué hay adentro

```
agente-recordatorios-spark/
├── .github/workflows/
│   └── recordatorio_diario.yml   # Cron 6 AM + ejecución manual
├── config.py                     # Credenciales, perfil y logging
├── frases_processor.py           # Corpus, selección e historial
├── gemini_personalizador.py      # Personalización creativa con Gemini
├── telegram_sender.py            # Envío por Telegram (HTML + reintentos)
├── orchestrator.py               # Flujo de 4 pasos con manejo de fallos
├── main.py                       # Entrada CLI, no interactiva
├── corpus_frases.json            # 73 frases de Spark
├── historial.json                # Últimas frases enviadas (anti-repetición)
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

**Corpus:** 31 citas de *Don Quijote*, 30 mensajes originales estilo Dr. Seuss,
y 12 del *Discurso Carpe Diem* y presentaciones de clase. **73 frases en total.**

---

## 🔑 Paso 1 — Conseguir las 3 credenciales

### 1. `GEMINI_API_KEY`
1. Entrá a <https://aistudio.google.com/app/apikey>
2. **Create API key** → copiala (empieza con `AIza...`)

### 2. `TELEGRAM_BOT_TOKEN`
1. En Telegram, buscá **@BotFather**
2. Mandale `/newbot`, elegí nombre y username (debe terminar en `bot`)
3. Te devuelve un token tipo `123456789:ABCdefGHI...`

### 3. `TELEGRAM_CHAT_ID`
1. **Escribile `/start` a tu bot recién creado** ← este paso es obligatorio;
   un bot no puede iniciar una conversación con vos.
2. Abrí en el navegador (reemplazando `<TOKEN>`):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. Buscá `"chat":{"id":123456789,...}` → ese número es tu Chat ID.

> Si `getUpdates` devuelve `{"ok":true,"result":[]}`, es porque no le escribiste
> al bot todavía. Mandale cualquier mensaje y recargá.

---

## ⚙️ Paso 2 — Configurar los GitHub Secrets

1. Andá a **Settings → Secrets and variables → Actions** de tu repo:
   <https://github.com/JuanFer1796/agente-recordatorios-spark/settings/secrets/actions>
2. **New repository secret** y agregá los tres, uno por uno:

| Nombre                | Valor                        |
|-----------------------|------------------------------|
| `GEMINI_API_KEY`      | `AIzaSy...`                  |
| `TELEGRAM_BOT_TOKEN`  | `123456789:ABCdef...`        |
| `TELEGRAM_CHAT_ID`    | `123456789`                  |

⚠️ Al pegar, cuidado con espacios invisibles al inicio o al final. Es el error #1.

---

## 🚀 Paso 3 — Subir el proyecto

```bash
git clone https://github.com/JuanFer1796/agente-recordatorios-spark.git
cd agente-recordatorios-spark

# copiá aquí todos los archivos del proyecto

git add .
git commit -m "feat: agente de recordatorios Spark con Gemini + Telegram"
git push origin main
```

### Permiso necesario para el historial
El workflow guarda `historial.json` de vuelta en el repo para no repetir frases.
Activalo una vez en:

**Settings → Actions → General → Workflow permissions →
✅ "Read and write permissions"** → Save

Si preferís no darle ese permiso, borrá el step *"Guardar historial"* del YAML.
El agente sigue funcionando; solo repetirá frases más seguido.

---

## ▶️ Paso 4 — Probarlo ya mismo

1. **Actions → Recordatorio Diario Personalizado → Run workflow**
2. Opcionalmente marcá `dry_run` para ver la vista previa sin enviar nada
3. Esperá 1-2 minutos y revisá Telegram

Deberías ver en los logs:

```
── Paso 1/4: leyendo el corpus ──
Corpus cargado: 73 frases válidas de 73 entradas.
── Paso 2/4: seleccionando la frase del día ──
── Paso 3/4: personalizando con Gemini ──
Personalización generada por Gemini (gemini-2.5-flash): 62 palabras.
── Paso 4/4: enviando por Telegram ──
Mensaje entregado a chat_id=...
Estado           : ÉXITO
```

Después de esto, corre solo todos los días. No hay nada más que hacer.

---

## 💻 Correrlo localmente (opcional)

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env           # Windows: copy .env.example .env
# editá .env con tus 3 credenciales

python main.py --validar       # verifica credenciales, corpus y bot
python main.py --dry-run       # genera el mensaje sin enviarlo
python main.py                 # envío real
```

### Opciones de CLI

| Comando                        | Qué hace                                          |
|--------------------------------|---------------------------------------------------|
| `python main.py`               | Flujo completo: elige, personaliza y envía        |
| `--dry-run`                    | Todo igual pero sin enviar; imprime vista previa  |
| `--id quijote_14`              | Fuerza una frase específica del corpus            |
| `--sin-gemini`                 | Salta Gemini (prueba solo Telegram)               |
| `--validar`                    | Solo chequea credenciales, bot y corpus           |
| `--log-level DEBUG`            | Muestra el prompt completo enviado a Gemini       |
| `--sin-alerta`                 | No avisa por Telegram si la corrida falla         |

Salida: `0` = éxito, `1` = error.

---

## 🎛️ Personalizar el agente

### Cambiar tu perfil
Editá el diccionario `PERFIL` en `config.py`. Todo lo que pongas ahí llega al
prompt de Gemini automáticamente.

### Cambiar la hora
En `.github/workflows/recordatorio_diario.yml`, ajustá el cron. Guatemala es
**UTC-6 todo el año** (no hay horario de verano), así que:

| Hora local | Cron UTC       |
|------------|----------------|
| 5:00 AM    | `0 11 * * *`   |
| 6:00 AM    | `0 12 * * *` ← |
| 7:00 AM    | `0 13 * * *`   |
| 9:00 PM    | `0 3 * * *`    |

> GitHub Actions no garantiza puntualidad exacta: los cron gratuitos suelen
> arrancar con **5 a 30 minutos de retraso** en horas de mucha carga. Es normal.

### Cambiar el estilo de los mensajes
Editá `SYSTEM_INSTRUCTION` en `gemini_personalizador.py`. Ahí están las reglas de
longitud, tono y la prohibición de amontonar referencias.

### Agregar frases
Añadí objetos a `corpus_frases.json` con los campos `id`, `source`, `author`,
`text`, `type`, `license`. El validador ignora entradas incompletas y lo avisa
en los logs.

---

## 🛡️ Cómo maneja los errores

| Falla                       | Qué pasa                                                        |
|-----------------------------|-----------------------------------------------------------------|
| Gemini no responde          | 3 reintentos con backoff → mensaje de respaldo. **El envío igual sale.** |
| Telegram da 429 (rate limit)| Espera lo que indica `retry_after` y reintenta                  |
| Telegram da 400/403         | Falla rápido y loguea una pista concreta del problema           |
| Falta un secret             | Sale con código 1 y dice exactamente cuál falta                 |
| Cualquier error del flujo   | Te manda una alerta silenciosa por Telegram con el detalle      |
| Corpus corrupto             | Ignora entradas inválidas; falla solo si no queda ninguna       |

---

## 🐛 Troubleshooting

**El workflow no aparece en Actions**
Esperá 5-10 minutos tras el primer push y recargá. Verificá que el archivo esté
exactamente en `.github/workflows/recordatorio_diario.yml`.

**`Falta la variable de entorno «GEMINI_API_KEY»`**
El secret no está o está mal escrito. Revisá Settings → Secrets → Actions,
borralo y volvé a pegarlo (sin espacios), y re-corré el workflow.

**`chat not found`**
No le escribiste `/start` al bot, o el Chat ID está mal. Probá manualmente:
```bash
curl "https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<ID>&text=hola"
```

**`Unauthorized` de Telegram**
El token está mal o lo revocaste. Pedí uno nuevo a @BotFather con `/token`.

**Gemini: `quota exceeded` o `429`**
El free tier tiene límite por minuto. El código ya reintenta solo; si igual
falla, te llega el mensaje de respaldo con la frase original.

**`Gemini devolvió una respuesta vacía`**
El filtro de seguridad bloqueó la generación. Con una sola frase pasa muy poco;
el respaldo cubre el caso.

**El workflow falla en "Guardar historial" con `permission denied`**
Activá *Read and write permissions* (ver Paso 3) o borrá ese step del YAML.

**No repite nunca la misma frase, ¿está bien?**
Sí: `historial.json` recuerda las últimas 25. Cuando el ciclo se agota, se
reinicia solo. Ajustá `HISTORIAL_MAX` si querés otra ventana.

---

## 📝 Nota sobre dependencias

Se usa el SDK nuevo de Google, **`google-genai`** (`from google import genai`),
no el antiguo `google-generativeai`, que quedó descontinuado. Si copiás ejemplos
viejos de internet que usan `import google.generativeai as genai`, no van a
funcionar con este `requirements.txt`.

---

## 📄 Sobre el corpus

Las citas del Quijote son de dominio público. Los mensajes "estilo Dr. Seuss"
son originales escritos en el espíritu del autor, no reproducciones de su obra.
Las frases de clase están parafraseadas y marcadas como tales en el campo
`license` de cada entrada.
