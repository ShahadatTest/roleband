## duplicates: trasladado tal como estaba (wording=as-is)

## features/review/ComparisonLedger.tsx
duplicates-comparison-ledger-field = Campo
duplicates-comparison-ledger-earlier-posting = Oferta anterior
duplicates-comparison-ledger-newer-posting = Oferta más reciente
duplicates-comparison-ledger-fields = campos
duplicates-comparison-ledger-same = Igual
duplicates-comparison-ledger-different = Distinto
duplicates-comparison-ledger-side-by-side = Lado a lado
duplicates-comparison-ledger-show-matching-fields = { $choice ->
    [yes] Ocultar { $length } campos iguales
   *[no] Mostrar { $length } campos iguales
}
duplicates-comparison-ledger-show = { $choice ->
    [yes] Ocultar
   *[no] Mostrar
}
duplicates-comparison-ledger-title = Título
duplicates-comparison-ledger-status = Estado
duplicates-comparison-ledger-level = Nivel
duplicates-comparison-ledger-family = Disciplina
duplicates-comparison-ledger-locations = Ubicaciones
duplicates-comparison-ledger-workplace = Modalidad
duplicates-comparison-ledger-department = Departamento
duplicates-comparison-ledger-team = Equipo
duplicates-comparison-ledger-comp-est = CT est.
duplicates-comparison-ledger-disclosed-band = Rango publicado
duplicates-comparison-ledger-first-seen = Visto por primera vez
duplicates-comparison-ledger-last-observed = Visto por última vez
duplicates-comparison-ledger-age = Antigüedad
duplicates-comparison-ledger-links = Enlaces
duplicates-comparison-ledger-role-details = Detalles del puesto
duplicates-comparison-ledger-role-details-of = { $side ->
    [earlier] Detalles del puesto, oferta anterior
   *[newer] Detalles del puesto, oferta más reciente
}
duplicates-comparison-ledger-careers-page = Página de empleo
duplicates-comparison-ledger-careers-page-of = { $side ->
    [earlier] Página de empleo, oferta anterior
   *[newer] Página de empleo, oferta más reciente
}
duplicates-comparison-ledger-not-disclosed = no publicado

## features/review/DecisionConsole.tsx
duplicates-decision-console-ai-judgment-unavailable = Valoración de IA no disponible
duplicates-decision-console-ai = IA
duplicates-decision-console-ai-judgment = Valoración de IA
duplicates-decision-console-tokens-ms = { $model } · { $value } tokens · { $wall_time_ms } ms
duplicates-decision-console-current = Actual
duplicates-decision-console-make-a-decision = Tomar una decisión
duplicates-decision-console-ask-the-model = Preguntar al modelo
duplicates-decision-console-get-an-optional-independent-assessment = Obtén una valoración independiente opcional
duplicates-decision-console-ask-ai = { $choice ->
    [v1] Analizando…
    [v2] Volver a preguntar
   *[v3] Preguntar a la IA
}
duplicates-decision-console-uncertain = { $choice ->
    [v1] Probablemente el mismo puesto
    [v2] Probablemente puestos distintos
   *[v3] Incierto
}
duplicates-decision-console-local-model-assessment = Valoración del modelo local
duplicates-decision-console-make-a-decision-2 = { $choice ->
    [yes] Cambiar decisión
   *[no] Tomar una decisión
}
duplicates-decision-console-your-judgment = { $choice ->
    [yes] Cambia tu decisión
   *[no] Tu valoración
}
duplicates-decision-console-what-is-the-relationship = { $choice ->
    [yes] Reclasifica este par
   *[no] ¿Qué relación tienen?
}

## features/review/DescriptionComparison.tsx
duplicates-description-comparison-descriptions = Descripciones
duplicates-description-comparison-no-differing-passages = No hay pasajes distintos.
duplicates-description-comparison-changed-passage = Pasaje cambiado
duplicates-description-comparison-description-comparison = Comparación de descripciones
duplicates-description-comparison-differences = { $choice ->
    [same] No se detectaron diferencias entre pasajes.
   *[differ] { $count ->
        [one] { $count } pasaje difiere. Los pasajes en ámbar solo aparecen en esa { -posting(num: "one") }.
        [many] { $count } de pasajes difieren. Los pasajes en ámbar solo aparecen en esa { -posting(num: "one") }.
       *[other] { $count } pasajes difieren. Los pasajes en ámbar solo aparecen en esa { -posting(num: "one") }.
    }
}
duplicates-description-comparison-show-differences-only = { $choice ->
    [yes] Mostrar descripciones completas
   *[no] Mostrar solo diferencias
}
duplicates-description-comparison-description = Descripción

## features/review/ReviewHistory.tsx
duplicates-review-history-decided = Decididos
duplicates-review-history-every-judgment-ready-to-revisit = Cada valoración, lista para revisarla
duplicates-review-history-of = { $length } de { $value }
duplicates-review-history-try-another-title-requisition-id = Prueba con otro título, ID de vacante o filtro.
duplicates-review-history-system-score = puntuación del sistema
duplicates-proposed-as = { $kind ->
    [twin] Propuesto como puestos relacionados
   *[duplicate] Propuesto como el mismo puesto
}
duplicates-review-history-reviewed = Revisado
duplicates-review-history-revised = { $count ->
    [one] Modificado una vez
    [many] Modificado { $count } de veces
   *[other] Modificado { $count } veces
}
duplicates-review-history-decided-2 = Decididos
duplicates-review-history-search-decisions = Buscar decisiones
duplicates-review-history-search-title-or-requisition-id = Buscar título o ID de vacante
duplicates-review-history-filter-decisions = Filtrar decisiones
duplicates-review-history-all-decisions = Todas las decisiones
duplicates-review-history-no-matching-decisions = Ninguna decisión coincide
duplicates-review-history-loading = Cargando las decisiones…
duplicates-review-history-load-failed = No se pudieron cargar las decisiones

## features/review/ReviewScreen.tsx
duplicates-review-screen-every-pair-matched-automatically-has = Se han revisado todos los pares emparejados automáticamente. Puedes volver a cualquiera en Decididos.
duplicates-review-screen-open-decided = Abrir decididos
duplicates-review-screen-every-close-pair-on-your = Todos los pares parecidos de tu radar tienen una decisión. Puedes volver a cualquiera en Decididos.
duplicates-review-screen-pairs-left-in-the-queue = { $total } { $count ->
        [one] par
        [many] pares
       *[other] pares
    } { $choice ->
        [yes] con coincidencia automática, sin revisar
       *[no] en la cola
    }
duplicates-review-screen-system-similarity = Similitud del sistema
duplicates-review-screen-undone-your-later-decision-on = Deshecho. Tu decisión posterior sobre estas ofertas se mantiene.
duplicates-review-screen-could-not-undo = No se pudo deshacer: { $message }
duplicates-review-screen-marked-as = { $decision ->
    [duplicate] Marcado como mismo puesto
    [twin] Marcado como puestos relacionados
   *[different] Marcado como puestos distintos
}
duplicates-review-screen-undo = Deshacer
duplicates-review-screen-could-not-record-the-verdict = No se pudo guardar el veredicto: { $message }
duplicates-review-screen-duplicate-review-views = Vistas de revisión de duplicados
duplicates-review-screen-queue = Cola
duplicates-review-screen-matched-automatically = Emparejados automáticamente
duplicates-review-screen-nothing-to-check = Nada que revisar
duplicates-review-screen-queue-clear = Cola vacía
duplicates-review-screen-none-found = Aún no hay duplicados
duplicates-review-screen-none-found-why = Una empresa a menudo publica un mismo { -role(num: "one") } más de una vez: en varias ciudades, o de nuevo pasado un tiempo. Cuando un escaneo encuentra dos { -posting(num: "other") } que se parecen, esperan aquí a que digas si son el mismo puesto, puestos relacionados o puestos distintos.
duplicates-review-screen-none-found-yet = Aún no hay nada que decidir. Los pares nuevos aparecen aquí a medida que los escaneos los encuentran.
duplicates-review-screen-candidate-pair = Par candidato
duplicates-review-screen-system-similarity-2 = Similitud del sistema { $score }
duplicates-review-screen-about-system-similarity = Acerca de la similitud del sistema
duplicates-review-screen-loading = Cargando la cola…
duplicates-review-screen-load-failed = No se pudo cargar la cola

## features/review/decision.ts
duplicates-decision-different-roles = Puestos distintos
duplicates-decision-two-different-roles-keep-both = Dos puestos distintos. Conserva ambos.
duplicates-decision-related-roles = Puestos relacionados
duplicates-decision-related = Relacionados
duplicates-decision-close-but-not-the-same = Parecidos, pero no iguales: puestos relacionados con diferencias reales.
duplicates-decision-same-role = Mismo puesto
duplicates-decision-duplicate = Duplicado
duplicates-decision-one-role-two-postings-listed = Un puesto, dos ofertas: publicado de nuevo con otro ID de vacante.

## features/review/DescriptionComparison.tsx
duplicates-description-comparison-description-2 = Descripción de { $label }
duplicates-reason-same-title = Mismo título
duplicates-reason-titles-alike = Títulos { $pct }% parecidos
duplicates-reason-descriptions-alike = Descripciones { $pct }% parecidas
duplicates-reason-listed-at-once = Publicadas a la vez
duplicates-reason-same-department = Mismo departamento
duplicates-reason-department-unknown = Una no indica departamento
duplicates-reason-passages-differ = { $earlier } pasajes solo en la anterior, { $later } solo en la más reciente
