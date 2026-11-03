## role: movido tal como se encontró (wording=as-is)

## features/job-detail/JobCompPanel.tsx
role-job-comp-panel-the-employer-s-exact-words = Las palabras exactas del empleador
role-job-comp-panel-no-compensation-data-for-this = No hay datos de compensación para este puesto.
role-job-comp-panel-market-median-at-this-level = Mediana del mercado en este nivel
role-job-comp-panel-this-package-is-the-market = Esta estimación es { $toFixed }× la mediana del mercado para este nivel, normalmente señal de que el nivel o la disciplina no son correctos.
role-job-comp-panel-base = Base
role-job-comp-panel-base-salary-stated-in-the = Salario base indicado en la oferta.
role-job-comp-panel-this-employer-publishes-no-pay = Este empleador no publica ningún rango. Todo lo de abajo es una estimación.
role-job-comp-panel-we-have-not-checked-this = Aún no se ha revisado si esta oferta publica un rango.
role-job-comp-panel-stated = indicado
role-job-comp-panel-estimated = estimado
role-job-comp-panel-our-independent-estimate-of-total = Estimación independiente de la compensación total: { $range }
role-job-comp-panel-from-the-posting-s-pay = Del campo de compensación de la oferta, no de su texto.
role-job-comp-panel-bonus = Bono
role-job-comp-panel-equity = Acciones
role-job-comp-panel-cash-every-month = efectivo, cada mes
role-job-comp-panel-target-not-guaranteed = objetivo, no garantizado
role-job-comp-panel-per-year-vests-over-time = por año, se consolida con el tiempo
role-job-comp-panel-measured-split = Reparto medido
role-job-comp-panel-split-from-another-discipline = Reparto de otra disciplina
role-job-comp-panel-estimated-split = Reparto estimado
role-job-comp-panel-this-company-s-real-base = El reparto real de base/bono/acciones de esta empresa para este nivel y disciplina
role-job-comp-panel-no-measured-split-for-this = No hay reparto medido para esta disciplina: escalado a partir de las cifras de esta empresa para el mismo nivel en otra disciplina
role-job-comp-panel-no-measured-split-for-this-2 = No hay reparto medido para esta empresa: se usa la heurística por nivel de experiencia
role-job-comp-panel-posted-band-sits-well-above = El rango publicado está muy por encima del salario base { $band } medido en esta empresa, así que el nivel puede ser más alto.
role-job-comp-panel-posted-band-sits-well-below = El rango publicado está muy por debajo del salario base { $band } medido en esta empresa, así que el nivel puede ser más bajo.
role-job-comp-panel-you-choose-the-cash-stock = Tú eliges la mezcla de efectivo y acciones
role-job-comp-panel-equity-fills-a-per-level = Las acciones completan un objetivo de compensación total por nivel
role-job-comp-panel-equity-is-a-dollar-grant = Las acciones son una concesión en dólares según el nivel
role-job-comp-panel-vests = { $choice ->
    [yes] se consolidan { $vesting }, un bono de firma en efectivo cubre los años 1–2
   *[no] se consolidan { $vesting }
}
role-job-comp-panel-no-annual-bonus = sin bono anual
role-job-comp-panel-bonus-is-a-level-set = el bono es un % del salario base fijado por nivel
role-job-comp-panel-base-capped-at = salario base con tope de { $base_cap_usd }
role-job-comp-panel-yr = / año
role-job-comp-panel-mo = / mes
role-job-comp-panel-hr = / h
role-job-comp-panel-hourly-rate = tarifa por hora
role-job-comp-panel-the-posting-gives-an-hourly = La oferta indica una tarifa por hora, mostrada tal cual.
role-job-comp-panel-monthly-rate = tarifa mensual
role-job-comp-panel-the-posting-gives-a-monthly = La oferta indica una tarifa mensual, mostrada tal cual.
role-job-comp-panel-period-unclear = periodo poco claro
role-job-comp-panel-the-posting-s-wording-and = La redacción de la oferta y la magnitud de esta cifra no coinciden, así que no está claro si se paga por hora, por mes o por año. Lee abajo las palabras del propio empleador.
role-job-comp-panel-states-this-as-total-annual = { $company } lo indica como compensación anual total sin bono. Los empleados eligen cuánto es salario y cuánto opciones sobre acciones, así que no hay un reparto fijo de efectivo/acciones que mostrar.
role-job-comp-panel-employee-selected-mix = a elección del empleado
role-job-comp-panel-total-compensation = compensación total
role-job-comp-panel-the-posting-states-total-compensation = La oferta indica la compensación total sin desglose, así que no se muestra ninguno.
role-job-comp-panel-basis-not-stated = tipo no indicado
role-job-comp-panel-the-posting-states-this-figure = La oferta no dice si esta cifra es salario base o compensación total, así que no se divide en base, bonus y acciones.
role-job-comp-panel-no-estimate-available = No hay estimación disponible
role-job-comp-panel-estimated-total-package = { $choice ->
    [yes] Compensación total publicada
   *[no] Compensación total estimada
}
role-job-comp-panel-estimated-total-comp = Compensación total estimada
role-job-comp-panel-stated-by-the-employer = Indicado por el empleador
role-job-comp-panel-about-stated-base-salary = Sobre el salario base publicado
role-job-comp-panel-of-base-stated = { $round }% del salario base, indicado

## features/job-detail/JobDescription.tsx
role-job-description-no-description-captured = No se capturó ninguna descripción.

## features/job-detail/JobDetail.tsx
role-job-detail-back = Volver
role-job-detail-1-in-compare-pick-one = 1 en comparación · elige uno más
role-job-detail-compare-roles = Comparar { $compareCount } puestos
role-job-detail-view-apply = Ver y postular
role-job-detail-postings = { $lineage_size } ofertas
role-job-detail-reposted = republicado ×{ $repost_count }
role-job-detail-description = Descripción
role-job-detail-your-progress = Tu progreso
role-job-detail-set-a-stage = Elige una etapa…
role-job-detail-next = Siguiente: { $next_action }
role-job-detail-radar-s-read = Lectura del radar
role-job-detail-advisory-unclear = La redacción de la oferta no encaja claramente con un solo ámbito.
role-job-detail-advisory-basis = Una estimación a partir de la redacción de la oferta. Nunca saca un puesto de tu radar.
role-job-detail-details = Detalles
role-job-detail-team = Equipo
role-job-detail-workplace = Modalidad
role-job-detail-status = Estado
role-job-detail-to-apply = Para postular
role-job-detail-more-like-this = Más como este
role-job-detail-other-companies = Otras empresas
role-job-detail-same-company = Misma empresa · { $company }
role-job-detail-could-not-unsave-this-role = { $choice ->
    [yes] No se pudo guardar este puesto
   *[no] No se pudo quitar este puesto de guardados
}
role-job-detail-couldn-t-update-the-stage = No se pudo actualizar la etapa
role-job-detail-role = { $choice ->
    [yes] Puesto: { $title }
   *[no] Puesto
}
role-job-detail-back-2 = Volver
role-job-detail-compare-is-full-max = La comparación está llena (máx. { $compareCap })
role-job-detail-compare = { $choice ->
    [yes] En comparación
   *[no] Comparar
}
role-job-detail-it-s-no-longer-in = Este puesto ya no existe.
role-job-detail-not-started = { $choice ->
    [yes] Etapa
   *[no] Sin empezar
}
role-job-detail-stage = Etapa
role-job-detail-likely-your-kind-of-role = Probablemente tu tipo de puesto
role-job-detail-likely-outside-your-worlds = Probablemente fuera de tus ámbitos
role-job-detail-hard-to-place = Difícil de clasificar
role-job-detail-questions-the-employer-added-beyond = Preguntas que el empleador añadió además del nombre, el contacto y el currículum, leídas de la página de la oferta
role-job-detail-similarity = Similitud

## features/job-detail/JobRequirementsPanel.tsx
role-job-requirements-panel-no-explicit-skill-requirements-found = No se encontraron requisitos de habilidades explícitos en esta oferta. Significa que ninguno coincidió con las habilidades conocidas, no que el puesto no requiera habilidades.
role-job-requirements-panel-core-skills = Habilidades clave
role-job-requirements-panel-supporting = Complementarias
role-job-requirements-panel-show-more = Ver { $value } más
role-job-requirements-panel-industry = Sector
role-job-requirements-panel-qualifications = Cualificaciones
role-job-requirements-panel-ways-of-working = Formas de trabajo
role-job-requirements-panel-role-requirements = Requisitos del puesto
role-job-requirements-panel-what-this-role-asks-for = Lo que pide este puesto
role-job-requirements-panel-importance-reflects-how-strongly-this = La importancia refleja con qué fuerza esta oferta destaca cada elemento: requisitos explícitos encontrados en esta oferta, con las palabras exactas del empleador. No dice nada sobre tus habilidades ni tus posibilidades.
role-job-requirements-panel-required = Se requieren { $requiredYears } { $requiredYears2 }
role-job-requirements-panel-core = { $core } clave
role-job-requirements-panel-supporting-2 = { $supporting } complementarias
role-job-requirements-panel-sources = { $count ->
    [one] { $sources } fuente
    [many] { $sources } de fuentes
   *[other] { $sources } fuentes
}
role-job-requirements-panel-show-in-description = Ver en la descripción
role-job-requirements-panel-required-2 = Obligatorio
role-job-requirements-panel-preferred = Deseable
role-job-requirements-panel-used-in-role = Se usa en el puesto
role-job-requirements-panel-mentioned = Mencionado
role-job-requirements-panel-technology = Tecnología
role-job-requirements-panel-skill = Habilidad
role-job-requirements-panel-language = Lenguaje
role-job-requirements-panel-framework = Framework
role-job-requirements-panel-ml-ai = ML / IA
role-job-requirements-panel-cloud = Nube
role-job-requirements-panel-data = Datos
role-job-requirements-panel-infra = Infra
role-job-requirements-panel-security = Seguridad
role-job-requirements-panel-process = Procesos
role-job-requirements-panel-leadership = Liderazgo
role-job-requirements-panel-collaboration = Colaboración
role-job-requirements-panel-years = { $count ->
    [one] año
    [many] años
   *[other] años
}
role-job-requirements-panel-role-requirements-2 = Requisitos del puesto
role-job-requirements-panel-this-posting-has-no-stored = { $choice ->
    [yes] Analizando requisitos…
   *[no] Esta oferta no tiene texto guardado que analizar.
}
role-job-requirements-panel-preferred-2 = { $choice ->
    [yes] Obligatorio
   *[no] Deseable
}
role-job-requirements-panel-show-evidence = { $choice ->
    [yes] Ocultar evidencia
   *[no] Ver evidencia
}
role-job-requirements-panel-ways-of-working-evidence = Evidencia de formas de trabajo
role-job-requirements-panel-about-importance = Sobre la importancia
role-job-requirements-panel-important = { $choice ->
    [yes] Clave
   *[no] Importante
}
role-job-requirements-panel-skill-sources-show-evidence = { $count ->
    [one] { $display }, habilidad { $bandLabel } { $modality }, { $sources } fuente. Ver evidencia.
    [many] { $display }, habilidad { $bandLabel } { $modality }, { $sources } de fuentes. Ver evidencia.
   *[other] { $display }, habilidad { $bandLabel } { $modality }, { $sources } fuentes. Ver evidencia.
}
role-job-requirements-panel-requirement-sources = { $count ->
    [one] { $display }: requisito { $bandLabel }, { $modality }, { $sources } fuente
    [many] { $display }: requisito { $bandLabel }, { $modality }, { $sources } de fuentes
   *[other] { $display }: requisito { $bandLabel }, { $modality }, { $sources } fuentes
}
role-job-requirements-panel-importance-inline = { $band ->
    [core] clave
   *[other] importante
}
role-job-requirements-panel-modality-inline = { $modality ->
    [required] de carácter obligatorio
    [preferred] deseable
    [used_in_role] que se usa en el puesto
   *[context] que se menciona
}
role-job-requirements-panel-title = Título

## features/job-detail/LineageDiff.tsx
role-lineage-diff-not-disclosed = no publicado
role-lineage-diff-title-changed = Cambió el título
role-lineage-diff-level-changed = Cambió el nivel
role-lineage-diff-pay-band-newly-disclosed = { $choice ->
    [yes] El rango publicado cambió
   *[no] Rango publicado por primera vez
}
role-lineage-diff-pay-basis-changed = Cambió la base del rango publicado
role-lineage-diff-locations-changed = Cambiaron las ubicaciones
role-lineage-diff-estimate-changed = Cambió la estimación
role-lineage-diff-changes-since-the-previous-posting = Cambios desde la oferta anterior

## features/job-detail/LineageStack.tsx
role-lineage-stack-could-not-load-posting-history = No se pudo cargar el historial de ofertas. Inténtalo de nuevo.
role-lineage-stack-postings-of-this-role = { $size } ofertas de este puesto
role-lineage-stack-first-seen = vista por primera vez { $relDays }
role-lineage-stack-req = vacante { $req_id }
role-lineage-stack-locations = Ubicaciones
role-lineage-stack-comp-est = CT est.
role-lineage-stack-first-seen-2 = Vista por primera vez
role-lineage-stack-changes-from-the-previous-posting = Cambios respecto a la oferta anterior
role-lineage-stack-posting-history = Historial de ofertas
role-lineage-stack-previous-posting = Oferta anterior
role-lineage-stack-postings = Ofertas
role-lineage-stack-posting = { $choice ->
    [yes] Oferta { $seq }: { $role }
   *[no] Oferta { $seq }
}
role-lineage-stack-role = { $role ->
    [original] original
    [duplicate] duplicada
   *[repost] republicada
}
role-lineage-stack-badge = { $choice ->
    [yes] { $role } · #{ $seq }
   *[no] #{ $seq }
}
role-lineage-stack-next-posting = Oferta siguiente
role-lineage-stack-last-seen = { $choice ->
    [yes] Cerrada
   *[no] Vista por última vez
}

## features/job-detail/ListingAge.tsx
role-listing-age-reading-the-history = Leyendo el historial…
role-listing-age-couldn-t-read-the-history = No se pudo leer el historial.
role-listing-age-retry = Reintentar
role-listing-age-role-listed-for-across-postings = Puesto publicado durante { $days } en { $postings } ofertas.
role-listing-age-compare-the-postings = Comparar las ofertas
role-listing-age-possibly-the-same-role-not = Posiblemente el mismo puesto: { $value }, no se cuenta hasta confirmarlo.
role-listing-age-review = Revisar
role-listing-age-listed-for = Publicado durante
role-listing-age-since = desde { $listed_since }, { $bASIS }
role-listing-age-history = Historial
role-listing-age-listing-history = Historial de publicación
role-listing-age-role = Puesto
role-listing-age-first-listed-postings = Publicado por primera vez { $roleSince } · { $rolePostings } ofertas
role-listing-age-the-employer-s-date = la fecha del empleador
role-listing-age-when-roleband-first-saw-it = cuando se vio por primera vez
role-listing-age-title = Título
role-listing-age-stated-pay = Rango publicado
role-listing-age-level = Nivel
role-listing-age-discipline = Disciplina
role-listing-age-location = Ubicación
role-listing-age-posting = Oferta
role-listing-age-same-role-matched-automatically = { $choice ->
    [yes] mismo puesto, confirmado
   *[no] mismo puesto, emparejado automáticamente
}
role-listing-age-published-by-the-employer = Publicado por el empleador
role-listing-age-the-start = el inicio
role-listing-age-first-seen-by-roleband = Visto por primera vez
role-listing-age-gone-from-the-careers-page = Desapareció de la página de empleo
role-listing-age-came-back-same-requisition = Volvió, misma vacante
role-listing-age-employer-changed-its-date-to = El empleador cambió su fecha a { $to_at }
role-listing-age-never-the-start = nunca el inicio
role-listing-age-an-earlier-posting-was-listed = { $choice ->
        [yes] Se publicó la oferta anterior { $posting }
       *[no] Se publicó una oferta anterior
    }{ $choice2 ->
        [yes] , cerrada { $until }
       *[no] { "" }
    }
role-listing-age-reposted = { $choice ->
    [yes] Republicado como { $posting }
   *[no] Republicado
}
role-listing-age-still-listed-at-the-last = Seguía publicado en el último escaneo
role-listing-age-events = Eventos

## features/job-detail/PayFloorLine.tsx
role-pay-floor-line-clears-your-pay-floor = Supera tu base mínima de { $floor }
role-pay-floor-line-your-pay-floor-falls-inside = Tu base mínima de { $floor } está dentro de este rango
role-pay-floor-line-below-your-pay-floor = Por debajo de tu base mínima de { $floor }

## features/job-detail/PlaceSetSection.tsx
role-place-set-section-could-not-load-this-role = No se pudieron cargar los otros lugares de este puesto. Inténtalo de nuevo.
role-place-set-section-you-marked-this-posting-as = Marcaste esta oferta como un puesto distinto del mismo texto en otros lugares.
role-place-set-section-undo = Deshacer
role-place-set-section-same-title-and-the-same = Mismo título y misma descripción en cada lugar, salvo el lugar y lo que conlleva (compensación local, beneficios o texto legal) o unas pocas palabras cambiadas, así que cuenta como un solo puesto.
role-place-set-section-different-roles = Puestos distintos
role-place-set-section-marked-as-a-different-role = Marcado como un puesto distinto
role-place-set-section-undo-2 = Deshacer
role-place-set-section-could-not-record-the-verdict = No se pudo registrar la decisión: { $message }
role-place-set-section-also-listed-in = También publicado en
role-place-set-section-same-place = Mismo lugar
role-place-set-section-place-not-stated = Lugar no indicado
role-place-set-section-listed = · publicado { $listed_since }
role-place-set-section-a-second-posting-at-the = Una segunda oferta en el mismo lugar es el puesto publicado de nuevo.
role-place-set-section-the-employer-files-them-all = El empleador los agrupa todos en { $employer_label }.
role-place-set-section-other-places = { $count ->
    [one] 1 lugar más
    [many] { $otherPlaces } de lugares más
   *[other] { $otherPlaces } lugares más
}
role-place-set-section-times-here = { $value } veces aquí
role-place-set-section-also-listed-in-and = También publicado en { $places } y { $times }
role-place-set-section-listed-2 = Publicado { $times }
role-place-set-section-also-listed-in-2 = También publicado en { $places }

## features/job-detail/PostingReality.tsx
role-posting-reality-of-signs = { $length } de { $criteria_total } señales · { $sTANDING_HEDGE }

## features/job-detail/TwinDeck.tsx
role-twin-deck-could-not-load-twin-postings = No se pudieron cargar las ofertas gemelas de este puesto. Inténtalo de nuevo.
role-twin-deck-separate-roles-with-closely-related = Puestos distintos con trabajo muy relacionado
role-twin-deck-req = vacante { $req_id } · { $value }
role-twin-deck-via-a-related-group-not = Por un grupo relacionado · sin relación directa
role-twin-deck-req-2 = { $title } · vacante { $req_id }
role-twin-deck-compare-with-related-roles = Comparar con puestos relacionados
role-twin-deck-related-roles = Puestos relacionados
role-twin-deck-has-related-roles = { $count ->
    [one] Tiene un puesto relacionado
    [many] Tiene { $length } de puestos relacionados
   *[other] Tiene { $length } puestos relacionados
}
role-twin-deck-location-not-listed = ubicación no indicada

## features/job-detail/applyAsk.ts
role-apply-ask-nothing-beyond-your-resume = Nada más allá de tu currículum
role-apply-ask-questions = { $count ->
    [one] { $count } pregunta
    [many] { $count } de preguntas
   *[other] { $count } preguntas
}
role-apply-ask-written-answers = { $count ->
    [one] { $count } respuesta escrita
    [many] { $count } de respuestas escritas
   *[other] { $count } respuestas escritas
}
role-apply-ask-asks-your-expected-pay = pregunta tu compensación esperada

## features/job-detail/JobRequirementsPanel.tsx
role-job-requirements-panel-evidence = Evidencia de { $display }

## features/job-detail/LineageDiff.tsx
role-lineage-diff-added = añadido { $join }
role-lineage-diff-removed = eliminado { $join }

## features/job-detail/ListingAge.tsx
role-listing-age-changed = { $choice ->
    [yes] { $field } cambió { $count } veces
   *[no] { $field } cambió
}

## features/job-detail/JobCompPanel.tsx
role-job-comp-panel-the-posted-band-does-not = { $sPLIT_TITLE }. El rango publicado no coincide con ese nivel, así que trata el reparto como provisional

## Estado de una oferta, dicho en palabras (antes, el código sin más).
role-job-status-open = abierto
role-job-status-closed = cerrado

## Quién aportó el reparto.
role-job-comp-panel-split-from-roleband = { $choice ->
    [yes] Reparto según los datos integrados, a fecha de { $date }.
   *[no] Reparto según los datos integrados.
}
role-job-comp-panel-split-from-plugin = { $choice ->
    [yes] Reparto según { $plugin }, a fecha de { $date }.
   *[no] Reparto según { $plugin }.
}

## Lo que un anuncio hermano indica de otro modo.
role-place-set-section-states-pay = · publica { $range }
role-place-set-section-states-no-pay = · no publica rango

## Qué hace elegir una etapa.
role-job-detail-tracking-explainer = Elige una etapa para seguir este puesto: queda guardado, Guardados muestra su etapa y una fecha de seguimiento que fijes después te avisa cuando llegue.
role-job-comp-panel-estimate-of-total = Compensación total estimada: { $range }
role-job-comp-panel-split-not-reported = reparto no disponible
role-job-comp-panel-the-plugin-reports-no-split = El plugin que aporta la compensación da una cifra para este nivel, pero no cómo se reparte entre base, bonus y equity, así que no se divide.
role-job-comp-panel-roleband-splits-us-pay-only = La compensación se divide en base, bonus y acciones solo con datos de EE. UU. Este puesto está fuera de EE. UU. o en varios países, así que no se divide.
role-job-comp-panel-not-read-yet = aún sin leer
role-job-comp-panel-estimated-base = Salario base estimado
role-job-comp-panel-from-roleband-data = De los datos integrados.
