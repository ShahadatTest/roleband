## Filas de puestos y sus controles, compartidos por Radar, Guardados y Comparar

## Trayectorias
jobs-track-management = Gestión
jobs-track-product-program = Producto y programas
jobs-track-technical = Contribuidor técnico
jobs-track-business-customer = Negocio y clientes

## Cómo coincidió un resultado de búsqueda
jobs-match-exact = Coincidencia exacta
jobs-match-exact-title = El título, el enlace o el ID de vacante que buscaste
jobs-match-close = Coincidencia cercana
jobs-match-close-title = Un título parecido y el mismo tipo de trabajo
jobs-match-partial = Coincidencia parcial
jobs-match-partial-title = Trabajo parecido, con otro título u otro enfoque
jobs-via-keyword = Palabra clave
jobs-via-fuzzy = Aproximada
jobs-via-keyword-inline = palabra clave
jobs-via-fuzzy-inline = coincidencia aproximada
jobs-matched-via = Coincide por { $sources }

## Datos de la fila
jobs-level-not-stated-title = La oferta no indica nivel
jobs-level-not-mapped-title = El título indica un nivel en los términos propios de esta empresa, aún no asignado a los niveles comunes
jobs-level-unconfirmed = nivel sin confirmar
jobs-level-unconfirmed-title = Nivel deducido del título
jobs-career-track = Trayectoria
jobs-why-world-title = Por qué aparece para ti: el ámbito al que sirve este puesto
jobs-viewed = visto
jobs-stack-title = Este puesto se ha publicado más de una vez
jobs-reposted = republicado
jobs-related-title = Puestos distintos, muy relacionados
jobs-related = { $count } relacionados
jobs-places-title = El mismo puesto, publicado una vez por lugar con la misma descripción
jobs-places = { $count ->
    [one] Publicado en { $count } lugar
    [many] Publicado en { $count } de lugares
   *[other] Publicado en { $count } lugares
}
jobs-place-set-title = El mismo puesto, publicado de nuevo en el mismo lugar con la misma descripción
jobs-place-set = Publicado { $count } veces
jobs-standing-badge = Puede estar siempre abierta
jobs-unfollowed-badge = Ya no se escanea
jobs-loc-more = más: { $places }
jobs-listed-since-employer = Publicado desde el { $date }, fecha del empleador
jobs-listed-since-seen = Publicado al menos desde el { $date }

## El veredicto de oferta permanente
jobs-standing-title = Puede ser una oferta siempre abierta
jobs-standing-card-title = Puede ser una oferta siempre abierta: { $signs }. Son patrones en cómo se publica, no un veredicto sobre la empresa. Puede que aún esté contratando.
jobs-sign-long-open = Publicado durante mucho tiempo
jobs-sign-relisted = Publicado { $count } veces
jobs-sign-date-moved = Su fecha se retrasó mientras seguía publicado
jobs-sign-long-open-inline = publicado durante mucho tiempo
jobs-sign-relisted-inline = publicado { $count } veces
jobs-sign-date-moved-inline = su fecha se retrasó mientras seguía publicado

## Acciones de la fila
jobs-restore = Restaurar
jobs-restore-title = Restaurar en tu radar
jobs-compare = Comparar
jobs-compare-title = Comparar ({ $key })
jobs-compare-full = La comparación está llena
jobs-compare-full-cap = La comparación está llena: { $cap } como máximo
jobs-save = Guardar
jobs-save-title = Guardar ({ $key })
jobs-saved-title = Guardado ({ $key })
jobs-saved = Guardado

## La cabecera de la lista
jobs-head-role = Puesto
jobs-head-location = Ubicación
jobs-head-pay = Base
jobs-est-short = est.
jobs-sort-label-abbr = { $short } ({ $full })
jobs-sort-by = Ordenar por { $label }
jobs-sort-by-ascending = Ordenar por { $label }, ascendente
jobs-sort-by-descending = Ordenar por { $label }, descendente

## Indicadores en el margen
jobs-dismissed-aria = Marcaste { $title } como No es para mí. Deshacer
jobs-not-for-me-just-now = No es para mí · ahora mismo
jobs-compare-beacon-aria = { $count } en comparación. Comparar { $count } puestos
jobs-compare-beacon-aria-full = { $count } en comparación, llena. Comparar { $count } puestos
jobs-compare-full-pill = llena
jobs-in-compare = En comparación
jobs-in-compare-count = En comparación · { $count } de { $cap }
jobs-compare-not-saved = No guardada. Esta selección puede perderse al recargar.
jobs-compare-remove = Quitar { $title } de la comparación
jobs-clear = Vaciar

## Pasajes de la descripción
jobs-description-passages-description = Descripción

## Empresas que no sigues
jobs-unfollowed-you-don-t-follow-so = No sigues a { $company }, así que este puesto ya no se escanea. Visto por última vez: { $last_seen }.
