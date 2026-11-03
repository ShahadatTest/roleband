## scan: traducción al español (borrador de IA, pendiente de revisión)

## features/sync/SyncScopePopover.tsx
scan-sync-scope-popover-roleband-can-t-scan-any = Aún no se puede escanear ninguna empresa. Primero sigue una en Ajustes › Empresas seguidas.
scan-sync-scope-popover-all-shown = { $choice ->
    [yes] Todas las visibles ({ $shown } de { $total })
   *[no] Todas las visibles ({ $shown })
}
scan-sync-scope-popover-no-company-matches-that-filter = Ninguna empresa coincide con ese filtro.
scan-sync-scope-popover-stale = Desactualizadas ({ $length })
scan-sync-scope-popover-failed-last-run = No se pudieron escanear ({ $length })
scan-sync-scope-popover-a-targeted-sync-refreshes-only = Escanear unas pocas empresas actualiza solo las que eliges. Todo lo demás conserva la hora de su último escaneo.
scan-sync-scope-popover-cut-short = interrumpida
scan-sync-scope-popover-not-reached = no alcanzada
scan-sync-scope-popover-lists-no-roles = no publica puestos
scan-sync-scope-popover-failed = fallida
scan-sync-scope-popover-blocked = bloqueada
scan-sync-scope-popover-partial = parcial
scan-sync-scope-popover-a-few-rows-unread = algunas filas sin leer
scan-sync-scope-popover-capped = limitada
scan-sync-scope-popover-paused = en pausa
scan-sync-scope-popover-companies = { $count ->
    [one] empresa
    [many] empresas
   *[other] empresas
}
scan-sync-scope-popover-scan = { $choice ->
    [yes] Escanear todas las empresas
   *[no] Escanear { $count } { $value }
}
scan-sync-scope-popover-filter-companies-to-scan = Filtrar empresas para escanear
scan-sync-scope-popover-filter-companies = Filtrar empresas…
scan-sync-scope-popover-select-all-shown-companies = Seleccionar todas las empresas visibles
scan-sync-scope-popover-companies-to-scan-2 = Empresas para escanear
scan-sync-scope-popover-select-companies = Seleccionar empresas
scan-sync-scope-popover-choose-companies-to-scan = Elige empresas para escanear
scan-sync-scope-popover-loading = Cargando las empresas para escanear…
scan-sync-scope-popover-load-failed = No se pudieron cargar las empresas para escanear
scan-sync-scope-popover-joins-running = El escaneo en curso las lee a continuación.
scan-sync-scope-popover-joined = { $count ->
    [one] { $count } { -company(num: "one") } es la siguiente en el escaneo en curso.
    [many] { $count } de { -company(num: "other") } son las siguientes en el escaneo en curso.
   *[other] { $count } { -company(num: "other") } son las siguientes en el escaneo en curso.
}
