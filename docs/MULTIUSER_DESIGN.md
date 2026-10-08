# Modelo multiusuario (fase 2 del plan del servicio compartido)

Objetivo: que varias personas usen el mismo servidor sin ver ni mezclar sus datos, sin tocar la forma en que funciona hoy
para el propietario. Se hace en pasos pequeños que se pueden probar y deshacer. Cada paso deja el sistema funcionando.

## Qué es común y qué es de cada persona

Común (se lee una vez para todos): `companies`, `jobs`, `job_sources`, `monitored_sources`, `company_leads`,
`company_evidence`, `contacts`. Una oferta es una sola fila aunque la vean cien personas.

De cada persona (llevarán `user_id`): `job_evaluations`, `job_reviews`, `opportunity_notifications`, `applications`
(y `application_events`), `outreaches` (y `outreach_events`), `connection_requests`, `report_deliveries`.

Hoy un fichero guarda cosas que también dependen de la persona: la caché de decisiones (su clave ya incluye el perfil,
así que no se mezcla), el estado del bot de Telegram (un solo chat) y los ficheros de cartas y paquetes. Cada uno se
trata en su paso.

## Método: expandir y luego contraer

1. **Expandir (sin cambiar el comportamiento):** crear `users` y `user_profiles`; el propietario es el usuario 1.
2. **Columna `user_id` anulable** en cada tabla de persona, rellenada con el propietario. El código aún no la usa.
3. **Cambiar el código** para filtrar y escribir por `user_id`, siempre con un usuario explícito en la llamada.
4. **Contraer:** `user_id` obligatorio, y las restricciones de unicidad pasan de `job_id` a `(user_id, job_id)`.
5. Cada paso se despliega por separado, con copia de seguridad antes y una prueba de restauración.

## Paso 2a (este)

- Tabla `users`: identificador, chat de Telegram (único), idioma, zona horaria, estado, si es el propietario, fecha y
  versión del consentimiento, inicio y fin de la prueba.
- Tabla `user_profiles`: un perfil por usuario, guardado como JSON validado con el mismo modelo que hoy lee
  `candidate.local.json` (`CandidateConfig`), más el sector para poder filtrar sin abrirlo.
- Servicio `services/users.py`: crear o recuperar al propietario, leer y guardar un perfil validado.
- Orden `ai-job-hunter users import-owner`: importa `candidate.local.json` como perfil del propietario. Es idempotente.
- Nada del ciclo de lectura, evaluación ni avisos usa todavía estas tablas.

## Decisiones

- **Perfil en JSON y no en columnas:** el perfil cambia con frecuencia (campos nuevos, plantillas por sector) y se valida
  con un modelo; columnas por campo obligarían a una migración por cada ajuste.
- **Estado de la cuenta:** `ACTIVE`, `PAUSED` (la persona lo pidió), `TRIAL_ENDED` (se acabó la prueba, alertas
  pausadas, perfil conservado), `DELETED` (borrado pedido o por caducidad; la fila queda sin datos personales).
- **Un solo chat de Telegram por usuario** y único en la tabla: es la clave de identidad del bot.
- **El propietario sigue pudiendo usar el fichero:** `import-owner` es una importación, no una dependencia.

## Riesgos y cómo se cubren

- Mezclar datos entre personas: ninguna función de lectura o escritura por persona tendrá `user_id` opcional; las
  consultas sin filtro quedan solo para tareas de mantenimiento con nombre explícito.
- Doble coste de Jev: la huella de evaluación incluye el perfil, así que dos personas con el mismo perfil exacto
  comparten caché y dos distintos no.
- Migración sobre datos reales: copia de seguridad automática antes del despliegue (ya existe) y ensayo previo en una
  base aparte, como la de la prueba de finanzas.
