## Palabras compartidas por pantallas diferidas, nunca por el marco de la app
## (docs/copy.md, sección 3).

shared-count-role = { $count ->
    [one] { $count } { -role(num: "one") }
    [many] { $count } de { -role(num: "other") }
   *[other] { $count } { -role(num: "other") }
}
shared-count-posting = { $count ->
    [one] { $count } { -posting(num: "one") }
    [many] { $count } de { -posting(num: "other") }
   *[other] { $count } { -posting(num: "other") }
}
shared-count-company = { $count ->
    [one] { $count } { -company(num: "one") }
    [many] { $count } de { -company(num: "other") }
   *[other] { $count } { -company(num: "other") }
}
shared-curated-list = lista seleccionada
shared-not-for-me = No es para mí
shared-results-role = { $count ->
    [one] { $n } { -role(num: "one") }
    [many] { $n } de { -role(num: "other") }
   *[other] { $n } { -role(num: "other") }
}
shared-results-of-role = { $total ->
    [one] { $n } de { $t } { -role(num: "one") }
    [many] { $n } de { $t } de { -role(num: "other") }
   *[other] { $n } de { $t } { -role(num: "other") }
}
shared-results-company = { $count ->
    [one] { $n } { -company(num: "one") }
    [many] { $n } de { -company(num: "other") }
   *[other] { $n } { -company(num: "other") }
}
shared-results-of-company = { $total ->
    [one] { $n } de { $t } { -company(num: "one") }
    [many] { $n } de { $t } de { -company(num: "other") }
   *[other] { $n } de { $t } { -company(num: "other") }
}

## El botón de filtros (patterns/FilterSurface.tsx), en Radar y Notificaciones
shared-filters = Filtros
shared-filters-count = Filtros · { $count }

## La etiqueta de empresa y su tarjeta flotante (patterns/companies/CompanyChip.tsx)
shared-company-chip-aria = { $company }, ver el perfil de la empresa
shared-company-not-followed = No está en tu radar. Sigue a { $company } para ver sus puestos.
shared-company-open-roles = { $count ->
    [one] { $count } { -role(num: "one") } abierto
    [many] { $count } de { -role(num: "other") } abiertos
   *[other] { $count } { -role(num: "other") } abiertos
}
shared-company-no-open-roles = No hay puestos abiertos ahora mismo
shared-company-view-profile = Ver perfil

## patterns/Pager.tsx
shared-pager-prev = Anterior
shared-pager-page-of = Página { $page } de { $pages }
shared-pager-next = Siguiente

## ui/EChart.tsx
shared-echart-chart-unavailable = Gráfico no disponible. { $summary }

## ui/FilterRail.tsx
shared-filter-rail-clear = borrar
shared-filter-rail-more = + { $hidden } más
shared-filter-rail-select-all = Seleccionar todo
shared-filter-rail-no-options-match = Ninguna opción coincide.
shared-filter-rail-search = Buscar { $title }
shared-filter-rail-search-2 = Buscar { $title }…
shared-filter-rail-show-all = Ver todo: { $title }
shared-filter-rail-select-all-2 = Seleccionar todo: { $title }

## ui/FilterSelect.tsx
shared-filter-select-clear = Borrar
shared-filter-select-filter-by = Filtrar por { $label }
shared-filter-select-search = Buscar { $label }
shared-filter-select-search-2 = Buscar { $label }…

## patterns/companies/CompanyChip.tsx
shared-company-chip-summary = Resumen de { $display_name }

## ui/FilterSelect.tsx
shared-filter-select-filter = Filtro de { $label }
shared-filter-select-options = Opciones de { $label }

## Bandas de encaje por clave (backend/tracker/search/fit.py FIT_BAND_EDGES).
shared-fit-band-strong = Alto
shared-fit-band-good = Bueno
shared-fit-band-some = Aceptable
shared-fit-band-weak = Bajo
shared-pay-est-base = Base est. { $range }
shared-pay-est-base-hint = Solo el salario base. El bonus y la equity aún no se conocen.
shared-tc-full = Compensación total
shared-est-tc-full = Compensación total estimada
shared-base-salary-full = Salario base
shared-base-posted-hint = Rango publicado: de { $low } a { $high }{ $unit }
shared-base-posted-point-hint = Salario base publicado: { $amount }{ $unit }
shared-base-estimate-hint = Nuestra estimación para este nivel
shared-base-unknown = Salario base desconocido
shared-pay-not-covered = Aún sin leer por { $plugin }
shared-pay-not-covered-hint = Mientras { $plugin } aporta la compensación, una empresa que aún no ha leído no muestra estimación, ni tampoco una integrada.
shared-price-feed-get-key = Consigue una clave gratis

## ui/AsyncBoundary.tsx: lo que dice cuando quien lo usa no da un mensaje propio
shared-empty = Aún no hay nada aquí
shared-refresh-failed = No se pudo actualizar. Se muestra el último resultado.
