# Alta por Telegram (fase 4 del plan)

Una persona nueva se apunta sola desde Telegram, solo con invitación (beta cerrada).

## Flujo

1. El propietario escribe `/invite` al bot y recibe un código de un solo uso (caduca en 7 días) y un enlace
   `t.me/<bot>?start=<código>`.
2. La persona abre el bot y escribe `/start CÓDIGO`. Sin código válido el bot solo dice que necesita invitación.
3. **Consentimiento:** el bot explica qué guarda y qué comparte con terceros y pide aceptar con un botón. Si no acepta,
   no se guarda nada.
4. **CV:** PDF, Word o texto pegado (máx. 5 MB). Un modelo pequeño (`claude-haiku-5-5`) lo lee una vez y rellena un
   borrador de perfil. El CV no se guarda. El esquema no tiene campos para nombre, correo, teléfono ni dirección.
5. **Confirmar** el borrador o **corregirlo** con texto libre.
6. Preguntas que el CV no responde: sector, puesto buscado, lugares, mudanza, sueldo mínimo, modalidad.
7. Se valida el perfil con el mismo modelo que usa el resto del sistema, se guarda y empieza la prueba (7 días).

Comandos de cualquier persona registrada: `/my_data` (lo que hay guardado, con recuentos), `/pause`, `/resume`,
`/erase` (borra perfil, votos, notas, avisos, evaluaciones; la cuenta queda como una fila vacía sin chat ni consentimiento).

## Piezas

- `services/onboarding.py`: la conversación, sin Telegram (eventos de entrada, respuestas de salida). `ALERTS_LIVE`
  controla si el mensaje final promete avisos.
- `services/cv_extraction.py`: lectura del CV con tool use forzado y limpieza de lo devuelto.
- `services/telegram_signup.py`: enrutado de chats ajenos y `/invite`; delante de los manejadores del propietario.
- `services/user_erasure.py`: recuento y borrado de lo que hay guardado de una persona.
- Tablas: `invitations`, columna `users.onboarding` (paso y borrador), estado `ONBOARDING`.

## Lo que falta antes de invitar a nadie

- **Fase 3:** el ciclo que evalúa las ofertas por usuario y les manda los avisos a su chat. Hoy una persona dada de alta
  tiene perfil pero no recibe avisos; por eso el mensaje final lo dice y no se debe invitar a nadie todavía.
- Revisar el aviso de privacidad (`docs/PRIVACY_NOTICE_DRAFT.md`) y la versión que se guarda en `consent_version`.
- Alerta de prueba al terminar el alta, y cuotas de uso.
