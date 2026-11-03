### eager: the shell imports this file, so every message in it ships in the shell
### (docs/copy.md section 3). The compiler numbers its messages first.

## Navegación
shell-nav-radar = Radar
shell-nav-saved = Guardados
shell-nav-profile = Perfil
shell-nav-insights = Análisis
shell-nav-companies = Empresas
shell-nav-duplicates = Duplicados
shell-nav-notifications = Notificaciones
shell-nav-settings = Ajustes

## Pestañas de Análisis
shell-tab-insights-overview = Resumen
shell-tab-insights-hiring = Contratación
shell-tab-insights-pace = Ritmo
shell-tab-insights-pay = Compensación
shell-tab-insights-stock = Acciones
shell-tab-insights-skills = Habilidades
shell-tab-insights-trends = Tendencias
shell-tab-insights-overlap = Solapamiento
shell-tab-insights-groups = Grupos

## Pestañas de Ajustes
shell-tab-settings-companies = Empresas que sigues
shell-tab-settings-ai = IA
shell-tab-settings-schedule = Programación
shell-tab-settings-recipes = Recetas
shell-tab-settings-retention = Conservación de datos

## Pestañas de Perfil
shell-tab-profile-looking-for = Qué buscas
shell-tab-profile-experience = Tu experiencia
shell-tab-settings-language = Idioma

## La barra superior
shell-route-welcome = Bienvenida
shell-route-compare = Comparar
shell-route-dashboard = RoleBand
shell-skip-to-content = Saltar al contenido
shell-topbar-aria = Navegación de la aplicación
shell-breadcrumb-aria = Ruta de navegación
shell-palette-open-aria = Abrir la paleta de comandos, ⌘ K
shell-palette-open-title = Paleta de comandos (⌘K)
shell-stats-aria = Telemetría de la misión
shell-stat-unknown = Desconocido
shell-stat-open = abiertos
shell-stat-open-aria = { $count ->
    [one] { $count } puesto abierto
    [many] { $count } de puestos abiertos
   *[other] { $count } puestos abiertos
}
shell-stat-open-aria-unknown = Puestos abiertos, aún sin contar
shell-stat-open-title = Mostrar todos los puestos abiertos
shell-stat-new = nuevos
shell-stat-new-aria = { $count } nuevos en los últimos 2 días
shell-stat-new-title = Mostrar los puestos publicados en los últimos 2 días
shell-stat-reposted = republicados
shell-stat-reposted-aria = { $count } republicados hoy
shell-stat-reposted-title = Mostrar los puestos republicados hoy
shell-stat-saved = guardados
shell-stat-saved-aria = { $count ->
    [one] { $count } puesto guardado
    [many] { $count } de puestos guardados
   *[other] { $count } puestos guardados
}
shell-stat-saved-aria-unknown = Puestos guardados, aún sin contar
shell-stat-saved-title = Puestos guardados
shell-loading-page = Cargando esta página…
shell-load-page-failed = No se pudo cargar esta página
shell-loading-role = Cargando este puesto…
shell-load-role-failed = No se pudo cargar este puesto

## La barra lateral
shell-rail-aria = Principal
shell-brand = RoleBand
shell-brand-line = Radar de oportunidades
shell-rail-collapse-aria = Contraer la navegación
shell-rail-expand-aria = Expandir la navegación
shell-rail-collapse = Contraer
shell-rail-expand = Expandir
shell-rail-workspace = Espacio de trabajo
shell-theme-aria = Cambiar el tema
shell-theme-title = Tema
shell-theme-light = Modo claro
shell-theme-dark = Modo oscuro

## Actualidad de los datos
shell-freshness-label = Último escaneo
shell-freshness-offline = Último escaneo desconocido
shell-freshness-offline-aria = Último escaneo: estado sin conexión
shell-freshness-offline-title = Estado no disponible
shell-freshness-oldest = Escaneo más antiguo: { $when }
shell-freshness-never = Aún sin escanear
shell-freshness-waiting = Esperando un escaneo completo: { $companies }
shell-freshness-aria = Último escaneo: { $state }
shell-freshness-loading-aria = Último escaneo: cargando

## El botón de escaneo
shell-scan-result-new = +{ $count } nuevos
shell-scan-result-none = Al día
shell-scan-queued-until = { $count } en cola · esperando hasta las { $time }
shell-scan-queued-blocked = { $count } en cola · { $reason ->
    [paused] en pausa
    [policy_denied] sin escaneo programado
    [backoff] esperando para reintentar
   *[other] en espera
}
shell-scan-queued = { $count } en cola
shell-scan-waiting =
    { $count } en cola · { $reason ->
        [preflight_running] comprobando el código primero
        [preflight_failed] retenido: el código no pasó sus comprobaciones
        [waiting_for_wake] esperando a que el ordenador despierte
        [waiting_for_mains] esperando corriente
        [schema_pending] esperando a que termine una actualización
        [dependencies_pending] esperando a que termine una actualización
        [supervisor_stale] el servicio en segundo plano no está en marcha
        [busy_external] hay otro escaneo en marcha
       *[other] esperando
    }
shell-scan-stopping = Deteniendo…
shell-scan-stop = Detener el escaneo
shell-scan-scanning = Escaneando…
shell-scan-queued-label = En cola
shell-scan-now = Escanear ahora
shell-scan-stop-queued-aria = Detener el escaneo en cola
shell-scan-in-progress-aria = Escaneo en curso
shell-scan-queued-aria = Escaneo en cola
shell-scan-stopped = Detenido
shell-scan-could-not-start = No se pudo iniciar
shell-scan-could-not-stop = No se pudo detener
shell-scan-stop-title = Detener el escaneo
shell-scan-running-title = Buscando puestos nuevos en todas las empresas que sigues…
shell-scan-requested-title = Solicitado; esperando a que el programador lo recoja
shell-scan-idle-title = Buscar puestos nuevos en todas las empresas que sigues
shell-scan-company-count = { $count ->
    [one] { $count } empresa
    [many] { $count } de empresas
   *[other] { $count } empresas
}
shell-scan-found = { $count } encontrados
shell-scan-choose-aria = Elegir las empresas que escanear
shell-scan-some-title = Escanear algunas empresas
shell-scan-add-title = Añadir empresas a este escaneo

## La paleta de comandos
shell-palette-navigate = Ir a
shell-palette-actions = Acciones
shell-palette-subtab = { $section }: { $tab }
shell-palette-theme-light = Cambiar al tema claro
shell-palette-theme-dark = Cambiar al tema oscuro
shell-palette-shortcuts = Atajos de teclado
shell-palette-compare = { $count ->
    [one] Comparar { $count } puesto
    [many] Comparar { $count } de puestos
   *[other] Comparar { $count } puestos
}
shell-palette-clear-compare = Vaciar la selección de comparación ({ $count })
shell-palette-search = Buscar puestos con “{ $query }”
shell-palette-aria = Paleta de comandos
shell-palette-placeholder = Busca puestos o ve a cualquier sitio…
shell-palette-query-aria = Consulta de comandos
shell-palette-list-aria = Comandos
shell-palette-empty = Ningún comando coincide

## La campana de notificaciones y sus categorías
shell-notif-digest = Puestos nuevos para ti
shell-notif-reminder = Recordatorio
shell-notif-saved-listed = Puesto guardado publicado
shell-notif-pay-up = El rango publicado subió
shell-notif-pay-down = El rango publicado bajó
shell-notif-reposted = Puesto guardado republicado
shell-notif-long-open = Puesto guardado abierto hace tiempo actualizado
shell-notif-changed = Puesto guardado modificado
shell-notif-closed = Puesto guardado cerrado
shell-notif-scanning = Escaneando
shell-notif-scan-problems = El escaneo terminó con problemas
shell-notif-scan-unfinished = El escaneo se quedó sin tiempo
shell-notif-scan-failed = El escaneo falló
shell-notif-coverage = Problema de cobertura en una empresa que sigues
shell-notif-scan-stopped = Escaneo detenido
shell-notif-other = Notificación
shell-notif-mark-read-failed = No se pudo marcar como leída. Inténtalo de nuevo.
shell-bell-aria-count = Notificaciones, { $badge }
shell-bell-unread = { $count } sin leer
shell-bell-row-unread = no leída
shell-bell-empty = Aún no hay notificaciones.
shell-bell-load-failed = No se pudieron cargar las notificaciones. Inténtalo de nuevo.
shell-bell-view-all = Ver todas

## Comparar en la barra superior
shell-compare-chip = en comparación
shell-compare-chip-aria = { $count ->
    [one] { $count } puesto en comparación
    [many] { $count } de puestos en comparación
   *[other] { $count } puestos en comparación
}
shell-compare-chip-title = Abrir la comparación
shell-compare-save-failed = No se pudo guardar lo que estás comparando. Puede perderse al recargar.
shell-compare-cleared = { $count ->
    [one] Se quitó { $count } puesto de la comparación
    [many] Se quitaron { $count } de puestos de la comparación
   *[other] Se quitaron { $count } puestos de la comparación
}
shell-rail-pending = { $count } pendientes
shell-rail-item-count = { $label }, { $badge }

## La paleta de comandos: pistas de teclado
shell-palette-hint-navigate = navegar
shell-palette-hint-select = seleccionar
shell-palette-hint-close = cerrar
shell-model-switch = { $phase ->
    [downloading] descargando modelo
   *[converting] cambiando modelo
}
shell-model-switch-aria = { $phase ->
    [downloading] Descargando el modelo de clasificación. Abre Ajustes, IA para seguirlo
   *[converting] Cambiando el modelo de clasificación. Abre Ajustes, IA para seguirlo
}
shell-model-switch-title = Síguelo en Ajustes › IA. La clasificación sigue funcionando mientras tanto.
shell-tab-settings-plugins = Plugins
shell-tab-settings-privacy = Privacidad
shell-freshness-checked = Último escaneo · { $age }
shell-freshness-behind = Último escaneo · { $age } · { $count ->
    [one] { $count } empresa atrasada
    [many] { $count } de empresas atrasadas
   *[other] { $count } empresas atrasadas
}
shell-scan-updating-estimates = Actualizando estimaciones…
shell-scan-updating-estimates-aria = Actualizando estimaciones
