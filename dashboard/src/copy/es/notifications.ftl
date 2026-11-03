## notifications: traducción al español (borrador de IA, pendiente de revisión)

## features/notifications/DigestPanel.tsx
notifications-digest-panel-more-roles-opened-today = { $count ->
    [one] { $hidden } puesto más se abrió hoy.
    [many] { $hidden } de puestos más se abrieron hoy.
   *[other] { $hidden } puestos más se abrieron hoy.
}
notifications-digest-panel-unranked-set-an-intent-statement = { $choice ->
    [yes] Mejor encaje primero, según tu intención actual.
   *[no] Sin ordenar: escribe una declaración de intención o guarda algunos puestos para ordenarlos.
}

## features/notifications/NotificationFilters.tsx
notifications-notification-filters-status = Estado
notifications-notification-filters-read-status = Estado de lectura
notifications-notification-filters-all = Todas
notifications-notification-filters-unread = No leídas
notifications-notification-filters-priority = Prioridad
notifications-notification-filters-priority-2 = Prioridad
notifications-notification-filters-high = Alta
notifications-notification-filters-scans = Escaneos
notifications-notification-filters-filter-by-scan-event = Filtrar por evento de escaneo
notifications-notification-filters-roles = Puestos
notifications-notification-filters-filter-by-role-event = Filtrar por evento de puesto

## features/notifications/NotificationRow.tsx
notifications-notification-row-unread = no leída
notifications-notification-row-show-details = { $choice ->
    [yes] Ocultar detalles
   *[no] Mostrar detalles
}
notifications-notification-row-copy-notification-text = Copiar texto de la notificación
notifications-notification-row-copy-notification-text-2 = { $choice ->
    [yes] Tu navegador bloqueó el acceso al portapapeles
   *[no] Copiar texto de la notificación
}
notifications-notification-row-mark-read = { $choice ->
    [yes] Marcar como no leída
   *[no] Marcar como leída
}
notifications-notification-row-dismiss = Descartar
notifications-notification-row-dismiss-2 = Descartar
notifications-notification-row-details-for = Detalles de { $title }
notifications-notification-row-copy-summary = Copiar resumen
notifications-notification-row-copy-full-details = Copiar todos los detalles

## features/notifications/NotificationScreen.tsx
notifications-notification-screen-reset-all = Restablecer todo
notifications-notification-screen-nothing-unread = Nada sin leer
notifications-notification-screen-mark-all-read = Marcar todo como leído
notifications-notification-screen-nothing-here-yet = { $choice ->
    [yes] Nada coincide
   *[no] Aún no hay nada
}
notifications-notification-screen-scans-new-roles-for-you = { $choice ->
    [yes] Ninguna notificación coincide con estos filtros.
   *[no] Aquí llegan los escaneos, los puestos nuevos para ti, los cambios de rango publicado y las novedades de los puestos que guardaste.
}
notifications-notification-screen-search-notifications = Buscar notificaciones
notifications-notification-screen-find-a-role-company-or = Busca un puesto, una empresa o un escaneo…
notifications-notification-screen-clear-every-filter-and-lens = Quitar todos los filtros y vistas
notifications-notification-screen-loading = Cargando las notificaciones…
notifications-notification-screen-load-failed = No se pudieron cargar las notificaciones
notifications-notification-screen-refresh-failed = No se pudieron actualizar las notificaciones. Se muestra el último resultado.

## features/notifications/diagnostics/NotifDiagnostics.tsx
notifications-notif-diagnostics-run = Ejecución
notifications-notif-diagnostics-status = Estado
notifications-notif-diagnostics-duration = Duración
notifications-notif-diagnostics-sources-ok = Fuentes correctas
notifications-notif-diagnostics-errors = Errores ({ $length })
notifications-notif-diagnostics-drift-alerts = Alertas de desviación ({ $length })
notifications-notif-diagnostics-per-source = Por fuente
notifications-notif-diagnostics-source = Fuente
notifications-notif-diagnostics-scanned = Escaneados
notifications-notif-diagnostics-kept = Conservados
notifications-notif-diagnostics-new = Nuevos
notifications-notif-diagnostics-closed = Cerrados
notifications-notif-diagnostics-took = Tardó
notifications-notif-diagnostics-error = error
notifications-notif-diagnostics-drift = { $drift_count } desviaciones
notifications-notif-diagnostics-ok = ok
notifications-notif-diagnostics-drift-recorded = desviación registrada
notifications-notif-diagnostics-unknown-error = error desconocido
notifications-notif-diagnostics-run-started-took = Ejecución #{ $value } ({ $value2 }) · inicio { $value3 } · duración { $duration_seconds }
notifications-notif-diagnostics-errors-2 = Errores ({ $length }):
notifications-notif-diagnostics-drift-alerts-2 = Alertas de desviación ({ $length }):
notifications-notif-diagnostics-per-source-2 = Por fuente:
notifications-notif-diagnostics-source-scanned-kept-new-closed = fuente | escaneados | conservados | nuevos | cerrados | duración | estado
notifications-notif-diagnostics-notes = Notas: { $notes }
notifications-notif-diagnostics-copy-blocked = { $choice ->
    [yes] Copiado
   *[no] Copia bloqueada
}
notifications-notif-diagnostics-your-browser-blocked-clipboard-access = Tu navegador bloqueó el acceso al portapapeles
notifications-notif-diagnostics-text = { $choice ->
    [v1] Copiado al portapapeles
    [v2] El navegador bloqueó el portapapeles
   *[v3] { "" }
}

## features/notifications/moved-page/MovedPagePanel.tsx
notifications-moved-page-panel-stop-following = Dejar de seguir
notifications-moved-page-panel-find-new-careers-page = Buscar la nueva página de empleo
notifications-moved-page-panel-looking-for-s-new-careers = Buscando la nueva página de empleo de { $display }…
notifications-moved-page-panel-not-this-one = Esta no
notifications-moved-page-panel-careers-page-link = Enlace de la página de empleo
notifications-moved-page-panel-check = Comprobar
notifications-moved-page-panel-roleband-couldn-t-find-it = { $choice ->
    [yes] Ese enlace no es una página de empleo que se pueda leer.
   *[no] No se encontró. Pega el enlace a la nueva página de empleo de { $display }.
}
notifications-moved-page-panel-couldn-t-look-just-now = No se pudo buscar ahora. Inténtalo de nuevo o pega su enlace.
notifications-moved-page-panel-s-careers-page = Página de empleo de { $display }
notifications-moved-page-panel-use-this-careers-page = { $choice ->
    [yes] Cambiando…
   *[no] Usar esta página de empleo
}
notifications-moved-page-panel-paste-the-link-to-s = Pega el enlace a la nueva página de empleo de { $display }.

## features/notifications/moved-page/model.ts
notifications-model-roles = { $count ->
    [one] { $count2 } puesto
    [many] { $count2 } de puestos
   *[other] { $count2 } puestos
}
notifications-model-that-page-lists = { $choice ->
    [yes] Esa página responde.
   *[no] Esa página publica { $roles }.
}
notifications-model-s-own-careers-page-links = { $choice ->
    [yes] La propia página de empleo de { $display } enlaza a ella.
   *[no] La propia página de empleo de { $display2 } enlaza a ella: { $roles }.
}
notifications-model-found-it-roleband-saw-at = Encontrada: { $shared } ya vistos en { $display }.
notifications-model-of-them-roles = { $count ->
    [one] 1 de ellos
    [many] { $shared } de ellos
   *[other] { $shared } de ellos
}
notifications-model-found-it-roleband-saw-at-2 = Encontrada: { $roles }, { $seen } ya vistos en { $display }.

## features/notifications/sync-progress/SyncContribution.tsx
notifications-sync-contribution-what-has-landed = Empresas terminadas
notifications-sync-contribution-opportunities = { $count ->
    [one] { $total } puesto
    [many] { $total } de puestos
   *[other] { $total } puestos
}
notifications-sync-contribution-landed = terminadas
notifications-sync-contribution-scraping = escaneando
notifications-sync-contribution-queued = en espera
notifications-sync-contribution-failed = fallidas
notifications-sync-contribution-blocked = bloqueadas
notifications-sync-contribution-failed-2 = Fallidas: { $failed }
notifications-sync-contribution-blocked-the-source-is-refusing = Bloqueadas por su página de empleo: { $blocked }
notifications-sync-contribution-paused-while-this-computer = En pausa mientras este equipo dormía o estaba sin conexión: { $suspended }
notifications-sync-contribution-partial = Escaneadas en parte: { $degraded }
notifications-sync-contribution-scanned-nothing-in-scope = Escaneadas, sin puestos para ti: { $emptyButFine }
notifications-sync-contribution-more = +{ $length } más
notifications-sync-contribution-opportunities-2 = { $label } · { $count ->
    [one] { $value } puesto
    [many] { $value } de puestos
   *[other] { $value } puestos
}
notifications-sync-contribution-roles-found-per-company = Puestos por empresa terminada
notifications-sync-contribution-opportunities-3 = { $label }: { $value ->
    [one] { $value } puesto
    [many] { $value } de puestos
   *[other] { $value } puestos
}
notifications-sync-contribution-more-2 = { $join } y { $value } más

## features/notifications/sync-progress/SyncProgressPanel.tsx
notifications-sync-progress-panel-sources-failed-see-the-run = { $count ->
    [one] { $companiesFailed } empresa falló: consulta el resumen del escaneo cuando termine.
    [many] { $companiesFailed } de empresas fallaron: consulta el resumen del escaneo cuando termine.
   *[other] { $companiesFailed } empresas fallaron: consulta el resumen del escaneo cuando termine.
}
notifications-sync-progress-panel-nothing-is-written-to-the = Los puestos llegan a tu radar a medida que se escanea cada empresa.
notifications-sync-progress-panel-scan-progress = Progreso del escaneo: { $pHASE_LABEL }
notifications-sync-progress-panel-companies-scanned = Empresas escaneadas
notifications-sync-progress-panel-still-scraping = Aún escaneando
notifications-sync-progress-panel-roles-found = Puestos encontrados
notifications-sync-progress-panel-recorded = De empresas terminadas

## features/notifications/sync-progress/SyncStream.tsx
notifications-sync-stream-scraping-now = Escaneando ahora
notifications-sync-stream-held = Aún escaneando
notifications-sync-stream-on-disk = { $written } terminados
notifications-sync-stream-in-memory = Puestos encontrados
notifications-sync-stream-no-update-for-this-run = Sin novedades desde hace { $staleMs }: puede que este escaneo se haya detenido.
notifications-sync-stream-every-source-recorded = Escaneo terminado
notifications-sync-stream-writing-collected-sources-to-the = Añadiendo los últimos puestos
notifications-sync-stream-running-post-passes = Terminando
notifications-sync-stream-waiting-on-the-first-source = { $choice ->
    [yes] Esperando la primera empresa · { $companiesQueued } en espera
   *[no] Esperando la primera empresa
}
notifications-sync-stream-opportunities-held-in-memory-written = { $choice ->
    [yes] Escaneando ahora: { $join }. { $written ->
        [one] { $written } puesto de empresas terminadas
        [many] { $written } de puestos de empresas terminadas
       *[other] { $written } puestos de empresas terminadas
    }, { $held } de empresas que aún se están escaneando.
   *[no] { $progress }. { $written ->
        [one] { $written } puesto de empresas terminadas
        [many] { $written } de puestos de empresas terminadas
       *[other] { $written } puestos de empresas terminadas
    }, { $held } de empresas que aún se están escaneando.
}
notifications-sync-stream-path = path("{ $path }")

## features/notifications/sync-progress/model.ts
notifications-model-scanning-companies = Escaneando empresas
notifications-model-recording-roles = Añadiendo los últimos puestos
notifications-model-finishing-up = Terminando
notifications-model-sources = { $companiesCollected }/{ $companiesTotal } empresas
notifications-model-scanned-found = { $companies } escaneadas · { $opportunitiesDetected ->
    [one] { $opportunitiesDetected } puesto encontrado
    [many] { $opportunitiesDetected } de puestos encontrados
   *[other] { $opportunitiesDetected } puestos encontrados
}

## features/notifications/useNotificationsController.ts
notifications-use-notifications-controller-could-not = No se pudo { $what }
notifications-use-notifications-controller-mark-it-read = marcarla como leída
notifications-use-notifications-controller-mark-it-unread = { $choice ->
    [yes] marcarla como leída
   *[no] marcarla como no leída
}
notifications-use-notifications-controller-dismiss-that-notification = descartar esa notificación
notifications-use-notifications-controller-removed-from-your-notifications = “{ $title }” se quitó de tus notificaciones
notifications-use-notifications-controller-undo = Deshacer
notifications-use-notifications-controller-undo-that = deshacerlo
notifications-use-notifications-controller-use-that-careers-page = usar esa página de empleo
notifications-use-notifications-controller-roleband-now-reads-s-new = Leyendo ahora la nueva página de empleo de { $display }
notifications-use-notifications-controller-stop-following = dejar de seguir a { $display }
notifications-use-notifications-controller-stopped-following = Dejaste de seguir a { $display }
notifications-use-notifications-controller-mark-them-read = marcarlas como leídas
notifications-use-notifications-controller-marked-notifications-read = { $count ->
    [one] { $updated } notificación marcada como leída
    [many] { $updated } de notificaciones marcadas como leídas
   *[other] { $updated } notificaciones marcadas como leídas
}

## features/notifications/filters.ts
notifications-category-scanning = Escaneo
notifications-category-scan-problems = Problemas de escaneo
notifications-category-ran-out-of-time = Sin tiempo
notifications-category-scan-failed = Escaneo fallido
notifications-category-coverage = Cobertura
notifications-category-for-you = Para ti
notifications-category-reminders = Recordatorios
notifications-category-saved = Guardados
notifications-category-pay-up = Rango publicado al alza
notifications-category-pay-down = Rango publicado a la baja
notifications-category-reposted = Republicados
notifications-category-long-open = Abiertos hace tiempo
notifications-category-changed = Cambiados
notifications-category-closed = Cerrados

## features/notifications/sync-progress/SyncProgressPanel.tsx
notifications-sync-progress-panel-of = de { $companiesTotal }
notifications-sync-progress-panel-pending = { $opportunitiesPending } aún escaneando

## Notificaciones del servidor: las claves que el backend escribe en `meta.say`.

notif-companies = { $count ->
    [one] { $count } empresa
    [many] { $count } de empresas
   *[other] { $count } empresas
}
notif-duration-unknown = duración desconocida
notif-duration-seconds = { $s } s
notif-duration-minutes = { $m } min { $s } s
notif-duration-hours = { $h } h { $m } min
notif-sources-all = todas las empresas que sigues
notif-sources-more = { $names } y { $more } más
notif-affected-none = ninguna empresa en concreto; consulta las notas del escaneo
notif-closed = { $company } cerró un puesto que guardaste
notif-reposted = { $company } republicó un puesto que guardaste
notif-listed-again = { $company } volvió a publicar un puesto que guardaste
notif-listed = { $company } publicó un puesto que guardaste
notif-saved-elsewhere = { $places ->
    [one] { $company } todavía publica en otro lugar un puesto que guardaste
    [many] { $company } todavía publica en otros { $places } de lugares un puesto que guardaste
   *[other] { $company } todavía publica en otros { $places } lugares un puesto que guardaste
}
notif-saved-elsewhere-body = { $more ->
    [yes] { $title }. La oferta que guardaste cerró; el puesto sigue publicado en { $places } y más.
   *[no] { $title }. La oferta que guardaste cerró; el puesto sigue publicado en { $places }.
}
notif-pay-raised = { $company } subió el rango publicado de un puesto que guardaste
notif-pay-lowered = { $company } bajó el rango publicado de un puesto que guardaste
notif-pay-change = { $title }: { $before } -> { $after }
notif-updated-long-open = { $company } actualizó un puesto que guardaste, publicado desde hace mucho tiempo
notif-changed = { $company } cambió un puesto que guardaste
notif-digest = { $count ->
    [one] { $count } puesto nuevo para ti hoy
    [many] { $count } de puestos nuevos para ti hoy
   *[other] { $count } puestos nuevos para ti hoy
}
notif-digest-lead = { $title } en { $company }
notif-digest-fit = Encaje { $band }: { $lead }
notif-digest-more = { $lead } y { $more } más
notif-follow-up = Haz seguimiento con { $company } · { $when }
notif-due-today = vence hoy
notif-overdue = { $days } d de retraso
notif-follow-up-body = { $action }: { $title } ({ $stage })
notif-no-next-action = Sin siguiente acción
notif-coverage-unreachable = Su página de empleo no responde.
notif-coverage-unreadable = Su página de empleo respondió sin nada legible.
notif-coverage-partial = Los escaneos solo leyeron parte de su página de empleo.
notif-coverage-unknown = Ningún escaneo ha llegado a su página de empleo.
notif-coverage-empty-listing = Su página de empleo respondió con una lista vacía.
notif-coverage-board-missing = Su página de empleo ya no está en su última dirección.
notif-coverage-scan-title = { $days ->
    [0] No se pudo escanear { $company }
    [one] No se pudo escanear { $company } · { $days } día
    [many] No se pudo escanear { $company } · { $days } de días
   *[other] No se pudo escanear { $company } · { $days } días
}
notif-coverage-not-scanned-since = No ha tenido un escaneo completo desde { $day }, así que pueden faltar puestos nuevos de { $company }. Esto se resuelve en su próximo escaneo completo.
notif-coverage-not-scanned = Todavía no ha tenido un escaneo completo, así que pueden faltar puestos nuevos de { $company }. Esto se resuelve en su próximo escaneo completo.
notif-coverage-empty-title = { $days ->
    [0] { $company } no publica ningún puesto
    [one] { $company } no publica ningún puesto · { $days } día
    [many] { $company } no publica ningún puesto · { $days } de días
   *[other] { $company } no publica ningún puesto · { $days } días
}
notif-coverage-empty-moved = Si { $company } sigue contratando, puede que sus puestos se hayan trasladado a una nueva página de empleo.
notif-coverage-held-until-listed = { $held ->
    [one] { $held } puesto se queda como se vio por última vez hasta que vuelva a publicar puestos.
    [many] { $held } de puestos se quedan como se vieron por última vez hasta que vuelva a publicar puestos.
   *[other] { $held } puestos se quedan como se vieron por última vez hasta que vuelva a publicar puestos.
}
notif-coverage-gone-title = { $days ->
    [0] La página de empleo de { $company } ya no existe
    [one] La página de empleo de { $company } ya no existe · { $days } día
    [many] La página de empleo de { $company } ya no existe · { $days } de días
   *[other] La página de empleo de { $company } ya no existe · { $days } días
}
notif-coverage-gone-moved = Probablemente { $company } trasladó sus puestos a una nueva página de empleo. Busca su nueva página de empleo o deja de seguir a { $company }.
notif-coverage-held-until-then = { $held ->
    [one] { $held } puesto se queda como se vio por última vez hasta entonces.
    [many] { $held } de puestos se quedan como se vieron por última vez hasta entonces.
   *[other] { $held } puestos se quedan como se vieron por última vez hasta entonces.
}
notif-coverage-outage = { $days ->
    [0] No se pudieron escanear { $count } empresas
    [one] No se pudieron escanear { $count } empresas · { $days } día
    [many] No se pudieron escanear { $count } empresas · { $days } de días
   *[other] No se pudieron escanear { $count } empresas · { $days } días
}
notif-coverage-outage-since = Ninguna ha tenido un escaneo completo desde { $day }, así que pueden faltar puestos nuevos. Esto se resuelve a medida que terminen los escaneos.
notif-coverage-outage-body = Ninguna ha tenido un escaneo completo, así que pueden faltar puestos nuevos. Esto se resuelve a medida que terminen los escaneos.
notif-scan-started = Escaneo iniciado
notif-scan-started-body = Escaneando { $count ->
    [one] { $count } empresa
    [many] { $count } de empresas
   *[other] { $count } empresas
}: { $sources }.
notif-scan-started-all-body = Escaneando { $sources }.
notif-scan-summary = { $found } encontrados / { $created } creados / { $updated } actualizados
notif-scan-summary-skipped = { $found } encontrados / { $created } creados / { $updated } actualizados / { $skipped } omitidos o sin cambios
notif-finished-at = Terminó a las { $at } tras { $duration }.
notif-failed-at = Falló a las { $at } tras { $duration }.
notif-scan-stopped = Escaneo detenido
notif-stopped-before-any = Lo detuviste antes de que escaneara ninguna empresa.
notif-stopped-after = Lo detuviste después de que escaneara { $companies }.
notif-problems-at = Problemas en: { $affected }.
notif-read-saved = Lo que encontró está guardado.
notif-scan-failed = No se pudo escanear, no se actualizó nada
notif-run-failed = el escaneo falló
notif-scan-derivation-failed = Escaneo recopilado, pero falló un cálculo derivado
notif-post-pass-unfinished = Un paso posterior al escaneo no terminó: { $failure }.
notif-every-source-delivered = Se leyeron todas las empresas de este escaneo, pero un paso posterior al escaneo no terminó: { $failure }.
notif-data-saved = Lo que encontró el escaneo está guardado.
notif-scan-problems = El escaneo terminó con problemas
notif-asleep = Este equipo estuvo en reposo durante { $duration } del escaneo, lo que deja incompleta la lista de una empresa.
notif-unreached = { $count ->
    [one] No se alcanzó antes de que el escaneo se quedara sin tiempo: { $sources }. Sigue pendiente, así que el próximo escaneo la recoge.
    [many] No se alcanzaron antes de que el escaneo se quedara sin tiempo: { $sources }. Siguen pendientes, así que el próximo escaneo las recoge.
   *[other] No se alcanzaron antes de que el escaneo se quedara sin tiempo: { $sources }. Siguen pendientes, así que el próximo escaneo las recoge.
}
notif-offline = { $count ->
    [one] Este equipo no tuvo conexión a internet durante el escaneo: { $sources }. Lo que se encontró está guardado, y sigue pendiente, así que el próximo escaneo la recoge.
    [many] Este equipo no tuvo conexión a internet durante el escaneo: { $sources }. Lo que se encontró está guardado, y siguen pendientes, así que el próximo escaneo las recoge.
   *[other] Este equipo no tuvo conexión a internet durante el escaneo: { $sources }. Lo que se encontró está guardado, y siguen pendientes, así que el próximo escaneo las recoge.
}
notif-cut-short = Detenido al llegar al límite de tiempo del escaneo: { $sources }. Lo que se encontró está guardado, y las ofertas de allí se quedan como se vieron por última vez.
notif-unfinished-u = El escaneo se quedó sin tiempo antes de { $unreached }
notif-unfinished-o = El escaneo perdió la conexión a internet en { $offline }
notif-unfinished-c = El escaneo solo cubrió parte de { $cut }
notif-unfinished-uo = El escaneo se quedó sin tiempo antes de { $unreached } y perdió la conexión a internet en { $offline }
notif-unfinished-uc = El escaneo se quedó sin tiempo antes de { $unreached } y solo cubrió parte de { $cut }
notif-unfinished-oc = El escaneo perdió la conexión a internet en { $offline } y solo cubrió parte de { $cut }
notif-unfinished-uoc = El escaneo se quedó sin tiempo antes de { $unreached }, perdió la conexión a internet en { $offline } y solo cubrió parte de { $cut }

## La prioridad de una notificación en su insignia.
notifications-priority-high = alta
notifications-priority-normal = normal
notifications-priority-low = baja

## Una candidatura sin noticias.
notif-gone-quiet = Sin noticias de { $company } desde hace { $days } días
notif-gone-quiet-body = { $title } ({ $stage }): es momento de hacer seguimiento o fijar una fecha
notif-coverage-waiting-title = Esperando para escanear { $company }
notif-coverage-waiting-outage = Esperando para escanear { $count } empresas
