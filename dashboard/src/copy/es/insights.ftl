## insights

## features/statistics/ClustersView.tsx
insights-clusters-view-semantic-groups-built-from-role = Puestos agrupados según lo que dicen sus descripciones y nombrados por las habilidades que comparten. Un mismo tipo de puesto puede dividirse en varios grupos.
insights-clusters-view-market-terrain = Terreno del mercado
insights-clusters-view-group-landscape = Mapa de grupos
insights-clusters-view-area-encodes-active-role-volume = Cuanto mayor es el recuadro, más puestos abiertos. Selecciona uno para ver sus puestos.
insights-clusters-view-groups = { $count } grupos
insights-clusters-view-roles = { $family_display } · { $size } puestos
insights-clusters-view-clear = Borrar
insights-clusters-view-and-more-companies = y { $n } empresas más
insights-clusters-view-role-groups = { $count ->
    [one] { $count } grupo de puestos
    [many] { $count } de grupos de puestos
   *[other] { $count } grupos de puestos
}
insights-clusters-view-largest-group = Mayor: { $label } · { $size } puestos
insights-clusters-view-groups-are-built-from-role = Los grupos se forman a partir de las descripciones de los puestos tras un escaneo
insights-clusters-view-about-role-groups = Acerca de los grupos de puestos
insights-clusters-view-groups-tile = Grupos
insights-clusters-view-from-role-descriptions = a partir de las descripciones
insights-clusters-view-roles-grouped = Puestos agrupados
insights-clusters-view-largest = Mayor
insights-clusters-view-roles-in-one-group = puestos en un grupo
insights-clusters-view-with-a-grouped-role = con un puesto agrupado
insights-clusters-view-how-to-read-the-cluster = Cómo leer el mapa de grupos
insights-clusters-view-loading = Cargando los grupos de puestos…
insights-clusters-view-load-failed = No se pudieron cargar los grupos de puestos
insights-clusters-view-group-loading = Cargando este grupo…
insights-clusters-view-group-load-failed = No se pudo cargar este grupo

## features/statistics/CompTrendChart.tsx
insights-comp-trend-chart-compensation-over-time = Compensación total a lo largo del tiempo
insights-comp-trend-chart-median-total-pay = Mediana de la compensación total estimada{ $series ->
        [single] { " " }con dispersión p25–p75
       *[several] { "" }
    } · { $period ->
        [all] todo el historial
       *[days] últimos { $days } d
    }
insights-comp-trend-chart-history-is-still-accruing-one = El historial aún se está acumulando: se registra una instantánea por escaneo, así que la línea de tendencia se mantiene plana hasta que el escaneo nocturno se haya ejecutado varios días.
insights-comp-trend-chart-no-comp-history-yet = Aún no hay historial de compensación.
insights-comp-trend-chart-roles = { $dim } · { $count } puestos
insights-comp-trend-chart-by-family = Por familia
insights-comp-trend-chart-breakdown = Desglose
insights-comp-trend-chart-compensation-percentile-trend = Tendencia de la compensación por percentil
insights-comp-trend-chart-loading = Cargando la tendencia de la compensación…
insights-comp-trend-chart-load-failed = No se pudo cargar la tendencia de la compensación

## features/statistics/CompensationPanel.tsx
insights-compensation-panel-compensation = Compensación
insights-compensation-panel-no-open-roles-with-a = Aún no hay puestos abiertos con una estimación de compensación.
insights-compensation-panel-open-roles-now-coverage = { $with_comp } / { $total_open } puestos abiertos ahora · { $pct }% de cobertura
insights-compensation-panel-estimated-total-compensation-is-imputed = La compensación total estimada se deduce de una tabla por empresa, nivel y familia. Las empresas no indicaron estas cifras; tómalas como referencia, no como una oferta.
insights-compensation-panel-published-bands = Rangos publicados
insights-compensation-panel-what-employers-actually-print = Lo que las empresas publican de verdad
insights-compensation-panel-bands-from-employers = { $bands } rangos · { $employers ->
    [one] { $employers } empleador
    [many] { $employers } de empleadores
   *[other] { $employers } empleadores
}
insights-compensation-panel-estimated-comp-distribution = Distribución de la compensación total estimada
insights-compensation-panel-median-comp-by-level = Mediana de la compensación total estimada por nivel
insights-compensation-panel-top-paying-companies = Empresas que más pagan
insights-compensation-panel-median-pay-by-discipline = Mediana de la compensación total estimada por disciplina
insights-compensation-panel-what-a-skill-adds-at = Lo que aporta una habilidad en el mismo nivel
insights-compensation-panel-roles-naming-the-skill-against = Puestos que mencionan la habilidad frente a todos los puestos del mismo nivel y la misma disciplina. La estimación se consulta por empresa, nivel y disciplina, así que la diferencia indica qué empresas piden la habilidad, no cuánto vale la habilidad en sí.
insights-compensation-panel-not-enough-priced-roles-per = Aún no hay suficientes puestos con salario por habilidad.
insights-compensation-panel-roles = { $count ->
    [one] { $count } puesto
    [many] { $count } de puestos
   *[other] { $count } puestos
}
insights-compensation-panel-groups-of-roles-or-more = Grupos de { $min_roles } puestos o más
insights-compensation-panel-base-salary-quoted-from-the = Salario base tomado de la oferta, no de la estimación anterior ni de la compensación total. Cada línea es un rango publicado, sin importar cuántos puestos abiertos lo compartan.
insights-compensation-panel-how-compensation-is-estimated = Cómo se estima la compensación
insights-compensation-panel-coverage = Cobertura
insights-compensation-panel-middle-50 = 50% central
insights-compensation-panel-top-decile = Decil superior
insights-compensation-panel-range = Dispersión
insights-compensation-panel-about-published-salary-bands = Acerca de los rangos publicados
insights-compensation-panel-how-a-skill-s-pay = Cómo se mide la diferencia de compensación de una habilidad
insights-compensation-panel-median = { $roles } · mediana { $p50 }

## features/statistics/Demand.tsx
insights-demand-open-roles-by-company = Puestos abiertos por empresa
insights-demand-each-role-counts-once-however = Cada puesto cuenta una vez, aunque se publique en varios lugares. Nuevos cuenta los últimos 2 días; cerrados, hoy.
insights-demand-no-open-roles-at-these = No hay puestos abiertos en estas empresas.
insights-demand-more-hold = { $share ->
    [none] { $companies } más tienen { $roles }.
   *[known] { $companies } más tienen { $roles } ({ $percent }% de estos puestos).
}
insights-demand-show-all = Mostrar todas ({ $company })
insights-demand-open-roles-by-region = Puestos abiertos por región
insights-demand-a-role-open-in-several = Un puesto abierto en varias regiones cuenta en cada una. Un puesto que solo indica una región, como Remoto EMEA, cuenta ahí para toda la región, nunca en cada país.
insights-demand-no-open-roles-yet = Aún no hay puestos abiertos.
insights-demand-all-of = Todo { $region }
insights-demand-and-more-countries = { $more ->
    [one] y { $more } país más
    [many] y { $more } de países más
   *[other] y { $more } países más
}
insights-demand-name-no-place-we-can = { $role } no indican ningún lugar concreto, como Remoto sin más.
insights-demand-of = { $shown } de { $companies }
insights-demand-hiring-now-today-new-closed = { $company } contratando ahora · { $new_today } nuevos en los últimos 2 días, { $closed_today } cerrados hoy
insights-demand-each-role-once = cada puesto una vez
insights-demand-with-an-open-role = con un puesto abierto
insights-demand-how-companies-are-counted = Cómo se cuentan las empresas
insights-demand-longest-open-roles = Puestos abiertos desde hace más tiempo
insights-demand-potential-hard-to-fill-signal = Posible señal de puesto difícil de cubrir.
insights-demand-no-data-yet = Aún no hay datos.
insights-demand-listed-over-a-year-are = Se excluyen los { $role } publicados hace más de un año: sus fechas se consideran obsoletas.
insights-demand-reposted-roles = Puestos republicados
insights-demand-closed-then-reappeared-a-repeated = Cerrado y luego reapareció: una señal repetida de presión para contratar.
insights-demand-none-detected-yet = Aún no se ha detectado ninguno.
insights-demand-reposted = { $company } · republicado ×{ $repost_count }
insights-demand-updated-but-never-closed = Actualizados pero nunca cerrados
insights-demand-changed-repeatedly-without-a-closure = Cambió varias veces sin llegar a cerrarse.
insights-demand-updated-times = Actualizado { $update_count } veces
insights-demand-about = Acerca de { $title }
insights-demand-how-regions-are-counted = Cómo se cuentan las regiones
insights-demand-all-companies-hiring = Todas las empresas que contratan
insights-demand-find-a-company = Buscar una empresa

## features/statistics/DisclosurePanel.tsx
insights-disclosure-panel-of-open-roles-have-not = { $pending } de { $open } puestos abiertos aún no se han revisado en busca de un rango publicado. Quedan fuera del porcentaje en lugar de contarse como empresas que no publican nada.
insights-disclosure-panel-pay-transparency = Transparencia salarial
insights-disclosure-panel-who-states-pay = Quién publica un rango
insights-disclosure-panel-the-share-of-open-roles = La proporción de puestos abiertos que publican un rango, contada sobre los puestos revisados hasta ahora, no sobre todos los puestos abiertos. Cuenta cualquier rango, sea salario base, compensación total o sin indicar; lo que vale el rango es una cuestión distinta de si se publicó.
insights-disclosure-panel-of-checked-roles-state-pay = { $rate } de { $checked } puestos revisados publican un rango
insights-disclosure-panel-no-open-roles-have-been = Aún no se ha revisado ningún puesto abierto en busca de un rango publicado.
insights-disclosure-panel-history-is-still-accruing-one = El historial aún se está acumulando: se registra una instantánea por escaneo, así que la línea se mantiene plana hasta que el escaneo nocturno se haya ejecutado varios días.
insights-disclosure-panel-over-time = A lo largo del tiempo
insights-disclosure-panel-pay-transparency-trend = Tendencia de la transparencia salarial
insights-disclosure-panel-share-of-checked-open-roles = Proporción de puestos abiertos revisados que publican un rango · { $window }
insights-disclosure-panel-no-pay-transparency-history-yet = Aún no hay historial de transparencia salarial.
insights-disclosure-panel-the-market-line-moves-when = La línea del mercado se mueve cuando se añaden empresas, y las empresas añadidas publican un rango con menos frecuencia. Mismas empresas sigue solo a las { $companies } leídas el { $since }.
insights-disclosure-panel-published-band-trend = Tendencia de los rangos publicados
insights-disclosure-panel-the-median-floor-and-ceiling = El mínimo y el máximo medianos que publican las empresas, contados una vez por rango publicado distinto y no una vez por puesto: un rango abarca muchos puestos abiertos, así que contar por puesto seguiría las republicaciones, no la compensación. Solo salario base; un rango que nunca dice si incluye bonus o acciones no puede compartir este eje.
insights-disclosure-panel-median-published-band = Rango mediano publicado de { $basis } · { $window }
insights-disclosure-panel-no-published-base-salary-band = Aún no se ha registrado ningún rango publicado de salario base.
insights-disclosure-panel-pay-transparency-over-time-covers = La transparencia salarial a lo largo del tiempo abarca todas las disciplinas: su historial se guarda por empresa y nivel.
insights-disclosure-panel-by-employer = Por empleador
insights-disclosure-panel-how-the-disclosure-rate-is = Cómo se mide el porcentaje de transparencia
insights-disclosure-panel-disclosure-breakdown = Desglose de transparencia
insights-disclosure-panel-share-of-open-roles-stating = { $group ->
    [company] Proporción de puestos abiertos que publican un rango, por empleador
   *[level] Proporción de puestos abiertos que publican un rango, por nivel
}
insights-disclosure-panel-trend-breakdown = Desglose de la tendencia
insights-disclosure-panel-share-of-open-roles-stating-over-time = Proporción de puestos abiertos que publican un rango a lo largo del tiempo
insights-disclosure-panel-about-the-published-band-trend = Acerca de la tendencia de los rangos publicados
insights-disclosure-panel-median-published-base-salary-band = Rango mediano publicado de salario base a lo largo del tiempo
insights-disclosure-panel-trend-loading = Cargando la tendencia de la transparencia salarial…
insights-disclosure-panel-trend-load-failed = No se pudo cargar la tendencia de la transparencia salarial
insights-disclosure-panel-band-trend-loading = Cargando la tendencia de los rangos publicados…
insights-disclosure-panel-band-trend-load-failed = No se pudo cargar la tendencia de los rangos publicados

## features/statistics/OverlapPanel.tsx
insights-overlap-panel-how-alike-their-roles-are = Cuánto se parecen sus puestos
insights-overlap-panel-not-enough-companies-with-skills = No hay suficientes empresas con habilidades para comparar. Elige dos o más.
insights-overlap-panel-shared-vocabulary = Vocabulario compartido
insights-overlap-panel-each-company-is-its-open = Cada empresa se representa por las habilidades de sus puestos abiertos, y una habilidad pesa más cuantas menos de estas empresas la mencionan, así que las habilidades que piden todas cuentan poco. Cada empresa queda junto a las que más se le parecen. Se usan las habilidades mencionadas por al menos { $min_jobs } puestos por empresa; se excluye lo que se espera de cualquier puesto.
insights-overlap-panel-comparison = Comparación { $companies } × { $companies }
insights-overlap-panel-exact-matrix = Matriz exacta
insights-overlap-panel-cells-show-how-alike-two = Las celdas muestran cuánto se parecen dos empresas, ×100; la diagonal muestra el número de habilidades distintas de cada empresa. Pasa el cursor sobre una celda para ver las habilidades compartidas.
insights-overlap-panel-companies-picked = { $picker ->
    [default] Más puestos abiertos
   *[chosen] { $picked } empresas
}
insights-overlap-panel-pair-names = { $a } y { $b }
insights-overlap-panel-no-shared-skills-yet = Aún no hay habilidades compartidas
insights-overlap-panel-most-alike-of = son las más parecidas de { $companies } empresas en las habilidades que distinguen a las empresas ({ $similarity })
insights-overlap-panel-companies-compared = { $companies } empresas comparadas
insights-overlap-panel-closest-pair = Par más cercano
insights-overlap-panel-median-pair = Par mediano
insights-overlap-panel-furthest-pair = Par más lejano
insights-overlap-panel-how-skill-overlap-is-calculated = Cómo se calcula la coincidencia de habilidades
insights-overlap-panel-cross-company-skill-overlap-matrix = Matriz de coincidencia de habilidades entre empresas
insights-overlap-panel-skills-open = { $company } · { $skill_count } habilidades · { $open } abiertos
insights-overlap-panel-pair-alike = { $listed ->
    [none] { $a } y { $b }: { $percent }% parecidas, { $shared } de { $union } habilidades compartidas
   *[some] { $a } y { $b }: { $percent }% parecidas, { $shared } de { $union } habilidades compartidas: { $skills }
}
insights-overlap-panel-no-shared-skills = { $a } y { $b }: sin habilidades compartidas

## features/statistics/OverviewPanel.tsx
insights-overview-panel-most-named-skills = Habilidades más mencionadas
insights-overview-panel-what-is-pulling-the-market = Lo que mueve el mercado
insights-overview-panel-the-skills-open-roles-name = Las habilidades que más mencionan los puestos abiertos, según cuántos puestos menciona cada una.
insights-overview-panel-leads-roles = { $display } encabeza · { $job_count } puestos
insights-overview-panel-largest-groups = Grupos más grandes
insights-overview-panel-no-groups-built-yet = Aún no se ha formado ningún grupo.
insights-overview-panel-open-the-longest = Abiertos desde hace más tiempo
insights-overview-panel-the-roles-advertised-longest-that = Los puestos anunciados desde hace más tiempo que siguen publicados. Puede que sean difíciles de cubrir o que simplemente sigan ahí: la página de empleo no dice cuál. Se excluye una fecha de publicación de hace más de un año por obsoleta.
insights-overview-panel-no-open-roles = No hay puestos abiertos.
insights-overview-panel-opened-closed = { $new_count } abiertos · { $closed_count } cerrados
insights-overview-panel-about-the-demand-field = Acerca del mapa de demanda
insights-overview-panel-what-open-the-longest-means = Qué significa abiertos desde hace más tiempo

## features/statistics/PayBands.tsx
insights-pay-bands-each-line-is-one-published = Cada línea es un rango publicado. El tramo resaltado es el rango mediano del nivel.
insights-pay-bands-any-employer = Cualquier empleador
insights-pay-bands-published-base-salary-bands-by = Rangos publicados de salario base por nivel
insights-pay-bands-bands-from-employers = { $bands ->
    [one] { $bands } rango
    [many] { $bands } de rangos
   *[other] { $bands } rangos
} · { $employers ->
    [one] { $employers } empleador
    [many] { $employers } de empleadores
   *[other] { $employers } empleadores
}
insights-pay-bands-employer-bands = { $published ->
    [none] Sin rango
   *[some] { $range } · { $bands } rangos
}

## features/statistics/SkillsView.tsx
insights-skills-view-a-narrowed-view-ranks-skills = Una vista filtrada ordena las habilidades según cuánto más las mencionan sus puestos que el resto del mercado, acercando las muestras pequeñas al mercado. El mercado completo las ordena según cuántos puestos menciona cada habilidad. Lo que se espera de cualquier puesto aparece aparte.
insights-skills-view-no-skills-extracted-for-this = Aún no hay habilidades para esta selección.
insights-skills-view-expected-of-the-role = Lo que se espera del puesto
insights-skills-view-process-leadership-and-collaboration-asks = Requisitos de procesos, liderazgo y colaboración. La mayoría de los puestos los mencionan, así que dicen en qué consiste el trabajo, no qué distingue a estos puestos.
insights-skills-view-against-the-market = Frente al mercado
insights-skills-view-what-sets-these-roles-apart = Qué distingue a estos puestos
insights-skills-view-above-the-line-named-more = Por encima de la línea: más mencionadas que en el mercado
insights-skills-view-pick-a-company-a-discipline = Elige una empresa, una disciplina o un lado para ver qué distingue a esos puestos del mercado.
insights-skills-view-skill = Habilidad
insights-skills-view-category = Categoría
insights-skills-view-share-of-roles = Proporción de puestos
insights-skills-view-lift = Factor
insights-skills-view-lead-skill = { $view ->
    [narrowed] { $skill } distingue a estos puestos
   *[market] { $skill } encabeza
}
insights-skills-view-of-roles-name-it = { $view ->
    [narrowed] { $share } de estos puestos la mencionan, frente a { $market_share } del mercado
   *[market] { $share } de los puestos la mencionan
}
insights-skills-view-how-skills-are-ranked = Cómo se ordenan las habilidades
insights-skills-view-roles = Puestos
insights-skills-view-naming-a-skill = que mencionan una habilidad
insights-skills-view-share-or-lift = { $view ->
    [narrowed] Factor
   *[market] Proporción
}
insights-skills-view-ranked-here = ordenadas aquí
insights-skills-view-expected = Esperadas
insights-skills-view-of-every-role = de cualquier puesto
insights-skills-view-any-company = Cualquier empresa
insights-skills-view-what-expected-of-the-role = Qué significa lo que se espera del puesto
insights-skills-view-skills-order = { $view ->
    [narrowed] Habilidades, las más características primero
   *[market] Habilidades, las más mencionadas primero
}
insights-skills-view-loading = Cargando las habilidades…
insights-skills-view-load-failed = No se pudieron cargar las habilidades

## features/statistics/StatisticsView.tsx
insights-statistics-view-window = Periodo
insights-statistics-view-all-time = Desde siempre
insights-statistics-view-statistics-sections = Secciones de estadísticas
insights-statistics-view-discipline = Disciplina
insights-statistics-view-time-range = Intervalo de tiempo
insights-statistics-view-advanced-view = Vista avanzada
insights-statistics-view-advanced-warning-title = Quedas avisado
insights-statistics-view-advanced-warning-body = La vista avanzada es para quien lee las notas al pie por diversión: percentiles, mapas de calor, diagramas de flujo y cada número que hay detrás. Puedes volver cuando quieras.
insights-statistics-view-show-me-everything = Enséñamelo todo
insights-statistics-view-keep-it-simple = Mantenlo simple
insights-statistics-view-part-of-advanced-view = Esta pestaña es parte de la vista avanzada.
insights-statistics-view-show-advanced-view = Mostrar vista avanzada

## features/statistics/StockTrajectoryPanel.tsx
insights-stock-trajectory-panel-stock-trajectory = Trayectoria de las acciones
insights-stock-trajectory-panel-no-open-roles-at-public = Aún no hay puestos abiertos en empresas cotizadas con una estimación de compensación, así que no hay acciones que proyectar frente a una cotización.
insights-stock-trajectory-panel-typical-package = { $split ->
    [measured] Compensación típica de empresa cotizada · repartos medidos
    [mixed] Compensación típica de empresa cotizada · repartos con datos mixtos
   *[heuristic] Compensación típica de empresa cotizada · repartos estimados
}
insights-stock-trajectory-panel-stock-moves-re-price-equity = { $split ->
    [measured] Los movimientos de la cotización cambian el valor de las acciones; el salario base y el bonus no cambian. Los repartos se miden por empresa y nivel. Son cifras de referencia, no ofertas.
    [mixed] Los movimientos de la cotización cambian el valor de las acciones; el salario base y el bonus no cambian. Los repartos se miden donde hay datos y se estiman en el resto. Son cifras de referencia, no ofertas.
   *[heuristic] Los movimientos de la cotización cambian el valor de las acciones; el salario base y el bonus no cambian. Los repartos se estiman con un bonus supuesto de { $bonus_pct } y acciones según la antigüedad profesional. Son cifras de referencia, no ofertas.
}
insights-stock-trajectory-panel-stock-price-change = Cambio en la cotización
insights-stock-trajectory-panel-reset-to-today = Volver a hoy
insights-stock-trajectory-panel-equity-shockwave = Onda de choque en las acciones
insights-stock-trajectory-panel-who-moves-when-the-stock = Quién se mueve cuando se mueve la cotización
insights-stock-trajectory-panel-public-companies = { $move ->
    [up] Empresas cotizadas · +{ $pct }%
   *[other] Empresas cotizadas · { $pct }%
}
insights-stock-trajectory-panel-sorted-by-equity-exposure-only = Ordenadas por exposición a acciones. Solo se mueve la parte en acciones.
insights-stock-trajectory-panel-no-open-roles-at-public-yet = Aún no hay puestos abiertos en empresas cotizadas.
insights-stock-trajectory-panel-ticker = Símbolo
insights-stock-trajectory-panel-equity = Acciones
insights-stock-trajectory-panel-equity-share = Parte en acciones
insights-stock-trajectory-panel-today = Hoy
insights-stock-trajectory-panel-projected = Proyectado
insights-stock-trajectory-panel-change = Cambio
insights-stock-trajectory-panel-no-exposure = sin exposición
insights-stock-trajectory-panel-private-companies = Empresas privadas
insights-stock-trajectory-panel-pre-ipo-equity-is-illiquid = Las acciones antes de la salida a bolsa no son líquidas y no tienen cotización diaria, así que este escenario no cambia aquí la compensación total.
insights-stock-trajectory-panel-median-tc = Compensación total mediana
insights-stock-trajectory-panel-median-tc-full = Compensación total mediana
insights-stock-trajectory-panel-options = Opciones
insights-stock-trajectory-panel-no-equity = Sin acciones
insights-stock-trajectory-panel-cash-election = Opción en efectivo
insights-stock-trajectory-panel-split-source = { $split ->
    [measured] Medido
    [mixed] Medido en parte
   *[heuristic] Estimado
}
insights-stock-trajectory-panel-split-source-explained = { $split ->
    [measured] Reparto real entre base, bonus y acciones a partir de los niveles de esta empresa
    [mixed] Algunos niveles tienen un reparto real; el resto son estimados
   *[heuristic] No hay reparto observado para esta empresa: se usa la estimación por antigüedad profesional
}
insights-stock-trajectory-panel-projected-tc = { $projected } de compensación total proyectada
insights-stock-trajectory-panel-projected-tc-full = { $projected } de compensación total proyectada
insights-stock-trajectory-panel-equity-figure = El { $share } de la compensación total es en acciones
insights-stock-trajectory-panel-how-stock-trajectory-is-projected = Cómo se proyecta la trayectoria de las acciones
insights-stock-trajectory-panel-median-tc-tile = compensación total mediana
insights-stock-trajectory-panel-median-tc-tile-full = compensación total mediana
insights-stock-trajectory-panel-at-price-change = { $move ->
    [up] con +{ $pct }%
   *[other] con { $pct }%
}
insights-stock-trajectory-panel-vs-today = frente a hoy
insights-stock-trajectory-panel-of-tc-at-risk = de la compensación total (en riesgo)
insights-stock-trajectory-panel-of-tc-at-risk-full = de la compensación total (en riesgo)
insights-stock-trajectory-panel-stock-price-change-percent = Porcentaje de cambio en la cotización
insights-stock-trajectory-panel-how-to-read-equity-sensitivity = Cómo leer la sensibilidad a las acciones
insights-stock-trajectory-panel-sensitivity-explained = { $move ->
    [flat] Con la cotización de hoy, cada barra es lo que una subida del 10% en las acciones añade a la compensación total típica. Mueve el control deslizante para ver un escenario.
   *[other] Muestra el cambio en dólares de la compensación total típica en este escenario.
}
insights-stock-trajectory-panel-scenario = { $move ->
    [flat] Por cada 10% de movimiento de la cotización · ajústalo arriba para ver un escenario
    [up] Escenario de +{ $pct }%
   *[down] Escenario de { $pct }%
}
insights-stock-trajectory-panel-about-public-company-projections = Acerca de las proyecciones de empresas cotizadas
insights-stock-trajectory-panel-paid-in-cash-unaffected-by = Se paga en efectivo: no depende de la cotización
insights-stock-trajectory-panel-why-private-companies-do-not = Por qué no se mueven las empresas privadas
insights-stock-trajectory-panel-loading = Cargando la trayectoria de las acciones…
insights-stock-trajectory-panel-load-failed = No se pudo cargar la trayectoria de las acciones
insights-stock-trajectory-panel-rsus = RSU

## features/statistics/TrendsPanel.tsx
insights-trends-panel-demand-history = Historial de demanda
insights-trends-panel-skill-demand-over-time = Demanda de habilidades a lo largo del tiempo
insights-trends-panel-each-skill-s-share-of = Proporción de cada habilidad en las menciones de habilidades del día · { $window }
insights-trends-panel-top-plotted-in-ledger = { $plotted } principales en el gráfico · { $total } en el registro
insights-trends-panel-history-is-still-accruing-one = El historial aún se está acumulando: se registra una instantánea por escaneo, así que las líneas de tendencia se mantienen planas hasta que el escaneo nocturno se haya ejecutado varios días.
insights-trends-panel-no-skill-history-yet = Aún no hay historial de habilidades.
insights-trends-panel-what-is-measured-changed-on = Lo que se mide cambió el { $dates } (llegó un grupo de empresas o se volvieron a leer las habilidades), así que se muestran proporciones, no recuentos.
insights-trends-panel-current-ledger = Registro actual
insights-trends-panel-now = Ahora
insights-trends-panel-skill-leads = { $skill } encabeza
insights-trends-panel-nothing-to-plot-yet = Aún no hay nada que mostrar
insights-trends-panel-leader-share-line = { $current_share } de las menciones de habilidades el último día · { $days } días de historial · { $window }
insights-trends-panel-history-accrues-one-day-per = El historial suma un día por escaneo · { $window }
insights-trends-panel-leader-s-share = Proporción de la primera
insights-trends-panel-of-skill-mentions = de las menciones de habilidades
insights-trends-panel-in-the-ledger = en el registro
insights-trends-panel-history = Historial
insights-trends-panel-days = { $count ->
    [one] día
    [many] días
   *[other] días
}
insights-trends-panel-latest-day = Último día
insights-trends-panel-none-yet = Aún ninguna
insights-trends-panel-of-the-series = de la serie
insights-trends-panel-of-skill-mentions-open-roles = { $current_share } de las menciones de habilidades, { $current } puestos abiertos
insights-trends-panel-change-points = cambio de { $share_delta } puntos
insights-trends-panel-loading = Cargando las tendencias de habilidades…
insights-trends-panel-load-failed = No se pudieron cargar las tendencias de habilidades

## features/statistics/VelocityPanel.tsx
insights-velocity-panel-market-current = Corriente del mercado
insights-velocity-panel-hiring-flow = Flujo de contratación
insights-velocity-panel-closures-pull-left-openings-push = Los cierres tiran hacia la izquierda y las aperturas empujan hacia la derecha; los rombos marcan la presión de actualizaciones.
insights-velocity-panel-net = { $direction ->
    [up] Neto +{ $net } { $window }
   *[down] Neto { $net } { $window }
}
insights-velocity-panel-companies = Empresas · { $window }
insights-velocity-panel-open = Abiertos
insights-velocity-panel-opened = Nuevos
insights-velocity-panel-time-posted = Tiempo publicado
insights-velocity-panel-from-the-first-scan-that = Desde el primer escaneo que vio una oferta hasta el escaneo que ya no la encontró. Las empresas retiran ofertas por muchos motivos (cubiertas, en pausa, caducadas, republicadas), así que esto es cuánto tiempo estuvo anunciado el puesto, nunca cuánto se tardó en contratar.
insights-velocity-panel-age-of-open-roles = Antigüedad de los puestos abiertos
insights-velocity-panel-how-long-postings-stay-up = Cuánto tiempo siguen publicadas las ofertas
insights-velocity-panel-this-builds-up-as-roles = Esto se completa a medida que los puestos se cierran: de momento solo lo han hecho { $closed_sample }. Se irá llenando cuando se retiren más ofertas.
insights-velocity-panel-median-age = Antigüedad mediana: { $median_days_open }
insights-velocity-panel-median-time-posted = Tiempo publicado mediano: { $median_observed_listing_duration_days }
insights-velocity-panel-more-already-listed-when-their = { $first_scan } más ya estaban publicados cuando se escaneó su empresa por primera vez
insights-velocity-panel-net-flow = Flujo neto
insights-velocity-panel-opened-closed = nuevos − cerrados
insights-velocity-panel-how-to-read-hiring-flow = Cómo leer el flujo de contratación
insights-velocity-panel-what-time-posted-measures = Qué mide el tiempo publicado

## features/statistics/ageCopy.ts
insights-age-copy-listed-today = Publicado hoy
insights-age-copy-listed-for = Publicado desde hace { $days }
insights-age-copy-dated-by-the-employer = { $percent }% con fecha del empleador
insights-age-copy-counted-from-when-each-role = Contado desde que se publicó cada puesto por primera vez · { $dated }

## features/statistics/charts/StatisticsCharts.tsx
insights-statistics-charts-skill-open-roles = { $job_count } puestos abiertos · { $category }
insights-statistics-charts-market-demand-field = Mapa de demanda del mercado
insights-statistics-charts-company-open-roles = { $open } puestos abiertos
insights-statistics-charts-new-closed-today = { $new_roles } en los últimos 2 días · { $closed_roles } hoy
insights-statistics-charts-new-count = +{ $fresh } nuevos
insights-statistics-charts-closed-count = −{ $closed } cerrados
insights-statistics-charts-open-roles-by-company = Puestos abiertos por empresa
insights-statistics-charts-open-new-closed = { $label }: { $open } abiertos, { $fresh } nuevos, { $closed } cerrados
insights-statistics-charts-closed = Cerrados ←
insights-statistics-charts-opened = → Nuevos
insights-statistics-charts-hiring-flow-by-company = Flujo de contratación por empresa
insights-statistics-charts-opened-closed-updated = { $company }: { $opened } nuevos, { $closed } cerrados, { $updated } actualizados
insights-statistics-charts-equity-change = { $direction ->
    [flat] Cambio de $0
    [down] −{ $amount }
   *[up] +{ $amount }
}
insights-statistics-charts-no-change = Sin cambios
insights-statistics-charts-equity-shockwave-by-company = Onda de choque en las acciones por empresa
insights-statistics-charts-share-against-market = { $share }% de estos puestos · { $market_share }% del mercado
insights-statistics-charts-lift-the-market-s-rate = ×{ $lift } la tasa del mercado
insights-statistics-charts-share-of-these-roles = proporción de estos puestos →
insights-statistics-charts-the-market-s-rate = × la tasa del mercado →
insights-statistics-charts-what-sets-these-roles-apart = Qué distingue a estos puestos
insights-statistics-charts-of-these-roles-the-market = { $skill }: { $share }% de estos puestos, ×{ $lift } el mercado
insights-statistics-charts-set-changed = cambió el conjunto
insights-statistics-charts-skill-demand-trends = Tendencias de demanda de habilidades
insights-statistics-charts-skill-mentions-change = { $direction ->
    [up] { $skill }: { $share }% de las menciones, +{ $points } puntos
   *[down] { $skill }: { $share }% de las menciones, { $points } puntos
}
insights-statistics-charts-skill-mentions-share = { $skill }: { $share }% de las menciones
insights-statistics-charts-pair-alike = { $similarity }% parecidas · { $shared } habilidades compartidas
insights-statistics-charts-pair = { $a } × { $b }
insights-statistics-charts-more-alike = más parecidas
insights-statistics-charts-less-alike = menos
insights-statistics-charts-cross-company-skill-overlap-heatmap = Mapa de calor de coincidencia de habilidades entre empresas
insights-statistics-charts-pair-similarity = { $a } y { $b }: { $percent }%
insights-statistics-charts-cluster-roles = { $size } puestos · { $family }
insights-statistics-charts-role-cluster-landscape = Mapa de grupos de puestos
insights-statistics-charts-roles = { $label }: { $size } puestos

## features/statistics/charts/compBands.ts
insights-comp-bands-level-summary = { $label }: { $bands } { $bands ->
        [one] rango
        [many] rangos
       *[other] rangos
    } de { $employers } { $employers ->
        [one] empleador
        [many] empleadores
       *[other] empleadores
    }, mediana de { $low } a { $high }.
insights-comp-bands-1-more-role-states-a = 1 puesto más publica un rango pero nunca dice si incluye bonus o acciones, así que no se muestra.
insights-comp-bands-more-roles-state-a-range = { $unclear } puestos más publican un rango pero nunca dicen si incluye bonus o acciones, así que no se muestran.
insights-comp-bands-1-more-role-states-base = 1 puesto más publica el salario base en otra moneda o por hora o por mes, así que no está en esta escala anual en dólares.
insights-comp-bands-more-roles-state-base-pay = { $elsewhere } puestos más publican el salario base en otra moneda o por hora o por mes, así que no están en esta escala anual en dólares.

## features/statistics/charts/disclosure.ts
insights-disclosure-unclassified = Sin clasificar
insights-disclosure-no-open-roles-have-been = Aún no se ha revisado ningún puesto abierto en busca de un rango publicado.
insights-disclosure-share-of-checked-open-roles = Proporción de puestos abiertos revisados que publican un rango. { $rates }.{ $unrated ->
        [0] { "" }
        [one] { " " }Hay { $unrated } grupo más sin ningún puesto revisado aún, así que no se puede indicar su porcentaje.
        [many] { " " }Hay { $unrated } de grupos más sin ningún puesto revisado aún, así que no se puede indicar su porcentaje.
       *[other] { " " }Hay { $unrated } grupos más sin ningún puesto revisado aún, así que no se puede indicar su porcentaje.
    }
insights-disclosure-of-roles = { $label }: { $rate }, { $disclosed } de { $checked } puestos
insights-disclosure-rate-states-pay = { $rate } publican un rango
insights-disclosure-of-checked-open-roles = { $disclosed } de { $checked } puestos abiertos revisados
insights-disclosure-no-pay-transparency-history-recorded = Aún no se ha registrado historial de transparencia salarial.
insights-disclosure-no-roles-checked-yet = { $dim }: aún no hay puestos revisados
insights-disclosure-of-checked-roles-state-pay = { $series }: { $pct } de { $checked } puestos revisados publican un rango{ $readings ->
        [single] { "" }
       *[several] { " " }(desde { $from })
    }
insights-disclosure-share-of-open-roles-stating = Proporción de puestos abiertos que publican un rango, por { $dim ->
        [company] empresa
        [level] nivel
       *[overall] el mercado
    }, { $span ->
        [day] el { $first }
       *[range] del { $first } al { $last }
    }. { $lines }.
insights-disclosure-not-checked = sin revisar
insights-disclosure-rate-percent = { $rate }%
insights-disclosure-no-published-pay-band-has = Aún no se ha registrado ningún rango publicado.
insights-disclosure-median-published-salary-band-across = Rango mediano publicado de { $basis } en { $bands } rangos distintos que abarcan { $roles } puestos abiertos: de { $low_p50 } a { $high_p50 }.{ $readings ->
        [single] { "" }
       *[several] { " " }Empezó entre { $start_low } y { $start_high }.
    } Una lectura por rango distinto, no por puesto.
insights-disclosure-median-ceiling = Máximo mediano
insights-disclosure-median-floor = Mínimo mediano
insights-disclosure-no-band-posted = sin rango publicado

## features/statistics/charts/StatisticsCharts.tsx (by hand)
insights-statistics-charts-more-signals = +{ $count } señales
insights-statistics-charts-cluster-size = { $size } puestos

## features/statistics/CompensationPanel.tsx
insights-compensation-panel-median-pay = { $p50 } de mediana
insights-compensation-panel-priced-roles = { $with_comp } puestos
insights-compensation-panel-loading = Cargando la compensación…
insights-compensation-panel-load-failed = No se pudo cargar la compensación
insights-compensation-panel-min-max = mín–máx

## features/statistics/Demand.tsx
insights-demand-open = { $role } abiertos
insights-demand-loading = Cargando la actividad de contratación…
insights-demand-load-failed = No se pudo cargar la actividad de contratación
insights-demand-today = hoy
insights-demand-last-2-days = últimos 2 días

## features/statistics/OverlapPanel.tsx
insights-overlap-panel-skills = { $skill_count } habilidades
insights-overlap-panel-loading = Cargando la coincidencia de habilidades…
insights-overlap-panel-load-failed = No se pudo cargar la coincidencia de habilidades
insights-overlap-panel-compared = comparadas
insights-overlap-panel-alike = de similitud

## features/statistics/OverviewPanel.tsx
insights-overview-panel-companies = { $companies } empresas
insights-overview-panel-loading = Cargando el resumen…
insights-overview-panel-load-failed = No se pudo cargar el resumen

## features/statistics/VelocityPanel.tsx
insights-velocity-panel-opened-count = { $opened } nuevos
insights-velocity-panel-open-count = { $open_total } abiertos
insights-velocity-panel-loading = Cargando el ritmo de contratación…
insights-velocity-panel-load-failed = No se pudo cargar el ritmo de contratación

## features/statistics/charts/compBands.ts
insights-comp-bands-to = de { $low } a { $high }
insights-comp-bands-employer-at-level = { $published ->
    [none] { $summary } { $employer } no publica ningún rango en este nivel.
   *[some] { $summary } { $employer }: { $ranges }.
}

## features/statistics/charts/disclosure.ts

## features/statistics/charts/StatisticsCharts.tsx
insights-statistics-charts-overlap-cell = { $cell ->
    [self] { $skillCount }{ "\u000A" }habilidades
    [pair] { $similarity }%
   *[empty] { "" }
}

## Los dos lados de la división por empresas de Análisis
insights-your-companies = Tus empresas
insights-other-companies = Otras empresas
insights-period-days = { $days } d

## Palabras que comparten varios paneles de Insights
insights-common-companies = Empresas
insights-common-company = Empresa
insights-common-open-roles = Puestos abiertos
insights-common-open-roles-unit = puestos abiertos
insights-common-new = Nuevos
insights-common-closed = Cerrados
insights-common-updated = Actualizados
insights-common-skills = Habilidades
insights-common-market = Mercado
insights-common-by-level = Por nivel
insights-common-by-company = Por empresa
insights-common-all-companies = Todas las empresas
insights-common-distinct-skills = { $count } habilidades distintas
insights-common-last-days-or-all-time = { $period ->
    [all] desde siempre
   *[days] últimos { $days } d
}
insights-common-last-days-or-all-history = { $period ->
    [all] todo el historial
   *[days] últimos { $days } d
}

## Categorías de habilidades
insights-skill-language = Lenguaje
insights-skill-framework = Framework
insights-skill-cloud = Nube
insights-skill-data = Datos
insights-skill-ml-ai = ML / IA
insights-skill-infra = Infraestructura
insights-skill-security = Seguridad
insights-skill-process = Procesos
insights-skill-leadership = Liderazgo
insights-skill-collaboration = Colaboración
insights-skill-industry = Sector

## Nombres de estadísticas: grupo sin términos, serie de cohorte y franjas de antigüedad
insights-cluster-unlabeled = Grupo sin etiqueta
insights-series-same-companies = Mismas empresas
insights-aging-from-0-days = < 1 semana
insights-aging-from-7-days = 1–2 semanas
insights-aging-from-14-days = 2–4 semanas
insights-aging-from-30-days = 1–2 meses
insights-aging-from-60-days = 2–3 meses
insights-aging-from-90-days = 3 meses o más

## El resumen de una línea de la vista general
insights-brief-open = { $open } puestos abiertos en { $companies } empresas.
insights-brief-opened = { $allTime ->
    [yes] { $opened } nuevos desde siempre, { $closed } cerrados.
   *[no] { $opened } nuevos en { $days } d, { $closed } cerrados.
}
insights-brief-top-skill = Habilidad principal: { $skill } ({ $count } puestos).
insights-brief-largest-group = Grupo más grande: { $group } ({ $size }).
insights-comp-trend-chart-reference-changed = { $count ->
    [one] La línea discontinua marca cuándo cambiaron a la vez las estimaciones de compensación: un cambio de datos, no del mercado.
    [many] Las líneas discontinuas marcan cuándo cambiaron a la vez las estimaciones de compensación: un cambio de datos, no del mercado.
   *[other] Las líneas discontinuas marcan cuándo cambiaron a la vez las estimaciones de compensación: un cambio de datos, no del mercado.
}
insights-comp-trend-chart-reference-marker = Las estimaciones de compensación cambiaron el { $date }
insights-compensation-panel-spread = p25–p75 { $low }–{ $high } · { $roles }
insights-compensation-panel-estimated-base-by-level = Salario base estimado por nivel
insights-compensation-panel-base-only = Solo base
insights-compensation-panel-base-only-lead =
    { $count ->
        [one] { $count } puesto más solo tiene un salario base estimado. Su bonus y su equity aún no se conocen, así que no está en las cifras de arriba.
        [many] { $count } de puestos más solo tienen un salario base estimado. Su bonus y su equity aún no se conocen, así que no están en las cifras de arriba.
       *[other] { $count } puestos más solo tienen un salario base estimado. Su bonus y su equity aún no se conocen, así que no están en las cifras de arriba.
    }
