## profile: traducción al español (borrador de IA, pendiente de revisión)

## features/scope/ExperiencePage.tsx
profile-experience-page-back-to-summary = Volver al resumen
profile-experience-page-your-experience = Tu experiencia
profile-experience-page-coming-soon = Próximamente
profile-experience-page-cv-upload-isn-t-available = Todavía no puedes subir tu CV. Podrás añadirlo aquí y confirmar la experiencia que se usa para comprobar los requisitos de cada puesto.

## features/scope/NewMark.tsx
profile-new-mark-new = Nuevo
profile-new-mark-added-since-you-last-saved = Añadido desde la última vez que guardaste

## features/scope/PersonaRail.tsx
profile-persona-rail-level = Nivel
profile-persona-rail-tuned-for = Ajustado para

## features/scope/ProfileSuggestions.tsx
profile-suggestions-you-marked-there-not-for = marcaste { $dismissed_wrong_domain } de ahí como No es para mí: ámbito equivocado
profile-suggestions-more-not-for-me-with = { $dismissed_other } más marcados como No es para mí sin motivo
profile-suggestions-in-progress = { $pursued } en curso
profile-suggestions-role-there-is = puesto de ahí está
profile-suggestions-roles-there-are = puestos de ahí están
profile-suggestions-you-saved-there = guardaste { $favorited } de ahí
profile-suggestions-followed-company-sector-points = sector de empresas seguidas apunta
profile-suggestions-followed-company-sectors-point = sectores de empresas seguidas apuntan
profile-suggestions-your-aim-names-it = tu objetivo lo menciona
profile-suggestions-turned-on-on-your-radar = { $choice ->
    [yes] { $display } desactivado · { $in_scope_changed } actualizados en tu radar
   *[no] { $display } activado · { $in_scope_changed } actualizados en tu radar
}
profile-suggestions-could-not-apply-the-suggestion = No se pudo aplicar la sugerencia. Sigue pendiente.
profile-suggestions-could-not-dismiss-the-suggestion = No se pudo descartar la sugerencia. Inténtalo de nuevo.
profile-suggestions-could-not-load = No se pudieron cargar tus ajustes sugeridos. Inténtalo de nuevo.
profile-suggestions-suggested-adjustments = Ajustes sugeridos
profile-suggestions-turn-on = { $choice ->
    [yes] ¿Desactivar { $display }?
   *[no] ¿Activar { $display2 }?
}
profile-suggestions-inferred-from-your-recent-activity = { $choice ->
    [yes] Porque { $join }.
   *[no] Deducido de tu actividad reciente.
}
profile-suggestions-accept-turn-on = { $choice ->
    [yes] Aceptar: desactivar { $display }
   *[no] Aceptar: activar { $display }
}
profile-suggestions-turn-it-on = { $choice ->
    [yes] Desactivarlo
   *[no] Activarlo
}
profile-suggestions-dismiss-suggestion-about = Descartar la sugerencia sobre { $display }
profile-suggestions-no-thanks = { $choice ->
    [yes] Mantenerlo activado
   *[no] No, gracias
}

## features/scope/ScopeGuide.tsx
profile-scope-guide-how-your-radar-works = Cómo funciona tu radar
profile-scope-guide-radar-guide = Guía del radar
profile-scope-guide-how-your-radar-works-2 = Cómo funciona tu radar
profile-scope-guide-five-answers-decide-what-reaches = Cinco respuestas deciden qué llega a tu radar. Un puesto aparece solo cuando encaja con todas.
profile-scope-guide-decide = Decide
profile-scope-guide-sharpen-optional = Afina, opcional
profile-scope-guide-your-radar = Tu radar
profile-scope-guide-when-changes-apply = Cuándo se aplican los cambios
profile-scope-guide-save-applies-your-answers-to = Al guardar, tus respuestas se aplican al momento a los puestos ya recopilados. Los puestos que solo alcanzan tus nuevas respuestas llegan con el próximo escaneo.
profile-scope-guide-about-the-counts = Sobre los recuentos
profile-scope-guide-progress-shows-how-many-of = El progreso muestra cuántos de los puestos de tus empresas conserva cada respuesta, según el último recuento. Hasta que se haga uno, indica Sin recuento aún, y Contar ahora inicia uno.
profile-scope-guide-nothing-hidden-by-a-guess = Nada oculto por una suposición
profile-scope-guide-a-role-we-haven-t = Un puesto que aún no está en ningún ámbito siempre se queda en tu radar.
profile-scope-guide-career-track-level-discipline-and = La trayectoria, el nivel, la disciplina y la ubicación deben coincidir antes de que un puesto aparezca en tu radar.
profile-scope-guide-opportunity-radar = Radar de oportunidades
profile-scope-guide-saving-applies-to-roles-already = Al guardar, el cambio se aplica al momento a los puestos que ya están en tu radar. Las disciplinas recién incluidas llegan tras el próximo escaneo completo.
profile-scope-guide-how-your-radar-works-3 = Cómo funciona tu radar
profile-scope-guide-close-guide = Cerrar la guía
profile-scope-guide-career-track = Trayectoria
profile-scope-guide-how-you-contribute = Cómo contribuyes
profile-scope-guide-where-you-are-and-aim = Dónde estás y adónde apuntas
profile-scope-guide-discipline = Disciplina
profile-scope-guide-the-work-you-want = El trabajo que quieres
profile-scope-guide-location = Ubicación
profile-scope-guide-where-it-can-be-based = Dónde puede estar

## features/scope/ScopeSection.tsx
profile-scope-section-company-exclusions = Exclusiones por empresa
profile-scope-section-matching-teams-and-departments-stay = Los equipos y departamentos que coincidan se quedan fuera de tu radar.
profile-scope-section-remove = Quitar
profile-scope-section-business-functions = Funciones de negocio
profile-scope-section-industries = Industrias
profile-scope-section-roles = { $count ->
    [one] { $count2 } puesto
    [many] { $count2 } de puestos
   *[other] { $count2 } puestos
}
profile-scope-section-could-not-restore-that-exclusion = No se pudo restaurar esa exclusión. Inténtalo de nuevo.
profile-scope-section-exclusion-restored-left-your-radar = Exclusión restaurada · { $in_scope_changed } salieron de nuevo de tu radar.
profile-scope-section-exclusion-removed-back-on-your = Exclusión quitada · { $in_scope_changed } de vuelta en tu radar.
profile-scope-section-undo = Deshacer
profile-scope-section-could-not-remove-that-exclusion = No se pudo quitar esa exclusión. Inténtalo de nuevo.
profile-scope-section-company-exclusions-2 = Exclusiones por empresa
profile-scope-section-remove-exclusion-at = Quitar la exclusión { $value } en { $company }

## features/scope/StageDimmer.tsx
profile-stage-dimmer-you-are-here = estás aquí
profile-stage-dimmer-aiming-for = tu meta
profile-stage-dimmer-roles = { $slug } puestos
profile-stage-dimmer-what-this-means-at-each = Qué significa en cada empresa
profile-stage-dimmer-this-kind-of-role-tops = { $choice ->
    [yes] Este tipo de puesto empieza más arriba aquí
   *[no] Este tipo de puesto llega menos alto aquí
}
profile-stage-dimmer-gated = { $range ->
    [from] Este tipo de puesto empieza en { $from }.
    [to] Este tipo de puesto llega hasta { $to }.
   *[both] Este tipo de puesto va de { $from } a { $to }.
}
profile-stage-dimmer-click-your-level-today = { $choice ->
    [v1] Ahora elige el nivel al que aspiras
    [v2] Elige cualquier nivel para empezar de nuevo
   *[v3] Elige tu nivel actual
}
profile-stage-dimmer-level-range = Rango de niveles
profile-stage-dimmer-your-level-today = Tu nivel actual
profile-stage-dimmer-level-you-re-aiming-for = Nivel al que aspiras
profile-stage-dimmer-companies = { $count ->
    [one] empresa
    [many] empresas
   *[other] empresas
}

## features/scope/WelcomeWizard.tsx
profile-welcome-wizard-back = Atrás

## features/scope/useScopeDraft.ts
profile-use-scope-draft-couldn-t-load-your-radar = No se pudo cargar tu radar. Inténtalo de nuevo.
profile-use-scope-draft-couldn-t-save-your-radar = No se pudo guardar tu radar. Inténtalo de nuevo.
profile-use-scope-draft-refreshing-role-counts-this-reads = Volviendo a contar los puestos. Solo se leen las páginas de empleo; los puestos de tu radar no cambian.
profile-use-scope-draft-that-refresh-was-deferred-because = Ese recuento espera a que termine el escaneo o recuento en curso.
profile-use-scope-draft-couldn-t-count-roles-at = No se pudieron contar los puestos de tus empresas. Inténtalo de nuevo.

## features/scope/walk/PayFloorRow.tsx
profile-pay-floor-row-pay-floor = Base mínima
profile-pay-floor-row-a-year-base = al año
profile-pay-floor-row-cancel = Cancelar
profile-pay-floor-row-checking = Comprobando…
profile-pay-floor-row-couldn-t-read-your-pay = No se pudo leer tu base mínima.
profile-pay-floor-row-retry = Reintentar
profile-pay-floor-row-compared-where-pay-is-stated = Se compara con el salario base publicado, cuando la oferta lo tiene.
profile-pay-floor-row-no-roles-are-hidden = No se oculta ningún puesto.
profile-pay-floor-row-enter-a-yearly-amount-like = Introduce un importe anual, como 250,000 o 250k.
profile-pay-floor-row-could-not-save-the-pay = No se pudo guardar la base mínima. Inténtalo de nuevo.
profile-pay-floor-row-pay-floor-2 = Base mínima
profile-pay-floor-row-lowest-yearly-base-pay = Salario base anual más bajo
profile-pay-floor-row-currency = Moneda
profile-pay-floor-row-save-floor = { $choice ->
    [yes] Guardando…
   *[no] Guardar base mínima
}
profile-pay-floor-row-set-floor = Fijar base mínima
profile-pay-floor-row-could-not-remove-the-pay = No se pudo quitar la base mínima. Inténtalo de nuevo.
profile-pay-floor-row-retry-reading-the-pay-floor = Volver a leer la base mínima
profile-pay-floor-row-add-a-pay-floor = { $choice ->
    [yes] Ajustar la base mínima
   *[no] Añadir una base mínima
}
profile-pay-floor-row-set-your-pay-floor = { $choice ->
    [yes] { $amount } al año
   *[no] Define tu base mínima
}
profile-pay-floor-row-minimum-yearly-base-pay = { $choice ->
    [yes] Ajustar
   *[no] Salario base anual mínimo
}

## features/scope/walk/ProgressRail.tsx
profile-progress-rail-focus-your-radar = Enfoca tu radar
profile-progress-rail-all-roles = Todos los puestos
profile-progress-rail-no-count-yet = Sin recuento aún.
profile-progress-rail-of-all-roles = de todos los puestos
profile-progress-rail-choose-your-role-level-and = Elige tu trayectoria, nivel y ubicación para ver qué encaja.
profile-progress-rail-review-changes = Revisar los cambios
profile-progress-rail-more-are-added-when-the = { $choice ->
    [yes] Hasta { $arriving } más llegan cuando termine el escaneo actual, o a medida que se vuelva a escanear cada empresa.
   *[no] Se añaden más cuando termine el escaneo actual.
}
profile-progress-rail-text = { $choice ->
    [yes] { " " }Hasta { $arriving } más llegan a medida que se vuelva a escanear cada empresa.
   *[no] { "" }
}
profile-progress-rail-text-2 = { $choice ->
    [yes] , como { $joinAnd }
   *[no] { "" }
}
profile-progress-rail-your-board-goes-from-to = { $choice ->
    [yes] Tu radar mantiene sus { $now }.
   *[no] Tu radar pasa de { $now2 } a { $after }.
}
profile-progress-rail-of-them-from-earlier-scans = { $adds } de ellos de escaneos anteriores{ $like }.
profile-progress-rail-a-scan-is-running-from = Hay un escaneo en curso: { $later } de escaneos anteriores se suman cuando termine{ $like }.
profile-progress-rail-more-join-as-each-company = Se suman más a medida que se vuelva a escanear cada empresa.
profile-progress-rail-your-progress = Tu progreso
profile-progress-rail-count-now = { $choice ->
    [yes] Iniciando…
   *[no] Contar ahora
}
profile-progress-rail-save-to-count-the-roles = { $choice ->
    [yes] Contando los puestos en { $pendingPlaces }…
   *[no] Guarda para contar los puestos en { $pendingPlaces2 }.
}
profile-progress-rail-roles-match = { $count ->
    [one] puesto coincide
    [many] puestos coinciden
   *[other] puestos coinciden
}
profile-progress-rail-roles-when-you-save = { $choice ->
    [yes] Sin cambios al guardar
   *[no] puestos al guardar
}
profile-progress-rail-we-ll-know-after-the = { $choice ->
    [v1] Se actualiza al guardar
    [v2] Sin cambios al guardar
    [v3] puestos al guardar
   *[v4] Se sabrá tras el próximo recuento
}
profile-progress-rail-save = { $choice ->
    [yes] Guardando…
   *[no] Guardar
}
profile-progress-rail-roles = { $count ->
    [one] puesto
    [many] puestos
   *[other] puestos
}
profile-progress-rail-roles-are = { $count ->
    [one] puesto está
    [many] puestos están
   *[other] puestos están
}
profile-progress-rail-text-3 = { $choice ->
    [yes] , { $promoted } de ellos de escaneos anteriores.
   *[no] .
}
profile-progress-rail-saved-on-your-board-now = { $choice ->
    [yes] Guardado. { $changed } { $value } cambiaron en tu radar.
   *[no] Guardado. { $onBoard } { $value2 } en tu radar ahora{ $value3 }{ $arriving }
}

## features/scope/walk/RadarPyramid.tsx
profile-radar-pyramid-illustrative-funnel-each-percentage-is = Embudo ilustrativo. Cada porcentaje es la parte que queda tras esa respuesta.
profile-radar-pyramid-after-the-first-three-answers = Tras las tres primeras respuestas
profile-radar-pyramid-locked = Bloqueado
profile-radar-pyramid-not-answered-yet = { $choice ->
    [yes] Cualquiera, sin acotar
   *[no] Sin responder aún
}
profile-radar-pyramid-choose = { $choice ->
    [yes] Cualquiera
   *[no] Elegir
}
profile-radar-pyramid-answered-no-count-yet = Respondida, sin recuento aún
profile-radar-pyramid-no-count = Sin recuento
profile-radar-pyramid-counting = Contando
profile-radar-pyramid-counted-after-you-save = Se cuenta al guardar
profile-radar-pyramid-save-first = Guarda primero
profile-radar-pyramid-keeps = Conserva { $kept }, { $kept2 }
profile-radar-pyramid-what-each-answer-keeps = Lo que conserva cada respuesta
profile-radar-pyramid-url-fill = url(#{ $id }-fill)

## features/scope/walk/RolesStep.tsx
profile-roles-step-pick-a-kind-of-role = Elige primero una trayectoria.
profile-roles-step-nothing-called-under = No hay nada llamado “{ $query }” en { $label }.
profile-roles-step-filter-roles = Filtrar puestos
profile-roles-step-filter-roles-2 = Filtrar puestos…
profile-roles-step-craft-for = Oficio para { $label }
profile-roles-step-roles = { $count ->
    [one] { $count2 } puesto · { $examples }
    [many] { $count2 } de puestos · { $examples }
   *[other] { $count2 } puestos · { $examples }
}

## features/scope/walk/SubjectsStep.tsx
profile-subjects-step-choose-a-list-then-tick = Elige una lista y marca lo que va en ella
profile-subjects-step-nothing-called = No hay nada llamado “{ $query }”.
profile-subjects-step-removes-of-the-roles-you = { $avoid } { $subject } quita { $dropped } de los { $of } puestos que elegiste en { $label }. Desmarca uno si no era tu intención.
profile-subjects-step-of-your-roles-aren-t = { $untagged } de tus { $of } puestos aún no están clasificados en un ámbito. Se quedan en tu radar, elijas lo que elijas.
profile-subjects-step-technologies = Tecnologías
profile-subjects-step-you-ll-see-roles-about = Verás puestos de estos ámbitos, además de los puestos que aún no están en ninguno.
profile-subjects-step-roles-about-these-drop-off = Los puestos sobre estos temas desaparecen, aunque también coincidan con un interés.
profile-subjects-step-switch-to-this = { $choice ->
    [yes] Eligiendo ahora
   *[no] Cambiar a esta
}
profile-subjects-step-picked = { $choice ->
    [yes] Ninguno aún
   *[no] { $picked } elegidos
}
profile-subjects-step-filter-interests = Filtrar ámbitos
profile-subjects-step-filter-interests-2 = Filtrar ámbitos…

## features/scope/walk/SummaryStep.tsx
profile-summary-step-summary = Resumen
profile-summary-step-adjust = Ajustar
profile-summary-step-what-it-keeps = Lo que conserva
profile-summary-step-no-count-yet-once-a = Sin recuento aún. Cuando se haya hecho un escaneo, aquí verás cuántos puestos conserva cada respuesta.
profile-summary-step-counting-the-roles-in = Contando los puestos en { $pendingPlaces }…
profile-summary-step-save-to-count-the-roles = Guarda para contar los puestos en { $pendingPlaces }.
profile-summary-step-add-your-cv = Añade tu CV
profile-summary-step-role = Trayectoria
profile-summary-step-where = Ubicación
profile-summary-step-which-roles = Disciplina
profile-summary-step-interests = Ámbito
profile-setup-unfinished = La configuración no está terminada, así que tu radar usa ajustes iniciales.
profile-setup-finish = Terminar la configuración
profile-setup-later = Configurar más tarde
profile-setup-title = Configura tu radar
profile-setup-step = Configuración, paso { $step } de { $count }
profile-setup-companies-tab = Empresas
profile-setup-companies-title = ¿Dónde debe buscar tu radar?
profile-setup-companies-note = Empiezas con empresas conocidas. Sigue más ahora o cuando quieras.
profile-setup-summary-later = Puedes cambiar cualquier respuesta más adelante en Perfil.
profile-summary-step-nothing-picked-yet = Nada elegido aún
profile-summary-step-any-role-that-fits = Cualquier puesto que encaje
profile-summary-step-none-yet = Cualquier ámbito
profile-summary-step-not-set = Sin definir
profile-summary-step-adjust-2 = Ajustar { $label }
profile-summary-step-after-you-save = { $choice ->
    [yes] contando
   *[no] al guardar
}
profile-summary-step-see-your-radar = { $choice ->
    [v1] Guardando…
    [v2] Guardar y ver tu radar
   *[v3] Ver tu radar
}

## features/scope/walk/Walk.tsx
profile-walk-locked-reason = Los demás pasos se abren cuando respondas las tres primeras preguntas.
profile-walk-optional = Opcional
profile-walk-skip = Omitir
profile-walk-summary = Resumen
profile-walk-what-your-radar-looks-for = Lo que busca tu radar
profile-walk-steps = Pasos
profile-walk-continue-reason-accountable = Elige al menos una trayectoria para continuar.
profile-walk-continue-reason-level = Elige tu nivel actual y el nivel al que aspiras para continuar.
profile-walk-continue-reason-where = Añade al menos un lugar para continuar.
profile-walk-continue = { $choice ->
    [yes] Listo
   *[no] Continuar
}

## features/scope/walk/WhereStep.tsx
profile-where-step-go-worldwide = Todo el mundo
profile-where-step-nothing-called-try-a-city = No hay nada llamado “{ $query }”. Prueba con una ciudad o un país.
profile-where-step-include-all = Incluir todo
profile-where-step-nothing-called-in = No hay nada llamado “{ $inside }” en { $display }.
profile-where-step-haven-t-been-scanned-for = { $count ->
    [one] { $companies } aún no se ha escaneado para { $few }.
    [many] { $companies } aún no se han escaneado para { $few }.
   *[other] { $companies } aún no se han escaneado para { $few }.
}
profile-where-step-replaces-the-places-you-ve = Sustituye los lugares que añadiste por cualquier lugar
profile-where-step-in-choose-to-narrow-to = { $choice ->
    [yes] ya añadido
   *[no] en { $display }, elige para acotar a este lugar
}
profile-where-step-add-back = Volver a añadir { $name }
profile-where-step-excepted-add-it-back = excluido, vuelve a añadirlo
profile-where-step-add = { $choice ->
    [yes] Acotar { $display } a { $name }
   *[no] Añadir { $name2 }
}
profile-where-step-add-2 = Añadir { $display }
profile-where-step-all-member-countries = { $choice ->
    [yes] ya añadido
   *[no] Los { $length } países miembros
}
profile-where-step-add-another-place = { $choice ->
    [v1] ¿Dónde vives?
    [v2] Indica un lugar
   *[v3] Añadir otro lugar
}
profile-where-step-add-another-place-2 = { $choice ->
    [v1] Ciudad, país o región
    [v2] Indica un lugar
   *[v3] Añadir otro lugar
}
profile-where-step-places = Lugares
profile-where-step-your-bases = Tus bases
profile-where-step-any-country-any-city = Cualquier país, cualquier ciudad.
profile-where-step-include-all-of = Incluir todo { $display }
profile-where-step-choose-in = { $choice ->
    [yes] Terminar de elegir { $noun } en { $display }
   *[no] Elegir { $noun2 } en { $display2 }
}
profile-where-step-choose = { $choice ->
    [yes] Listo
   *[no] Elegir { $noun }
}
profile-where-step-how-far-from = A qué distancia de { $display }
profile-where-step-remove = Quitar { $display }
profile-where-step-filter-in = Filtrar { $noun } en { $display }
profile-where-step-filter = Filtrar { $noun }
profile-where-step-and-more = { $join } y { $value } más
profile-where-step-careers-sites-cant-be-searched = { $count ->
    [one] Todavía no se puede buscar en { $places } en el sitio de empleo de { $companies }, así que sus { -role(num: "other") } de allí no llegarán a tu radar.
   *[other] Todavía no se puede buscar en { $places } en los sitios de empleo de { $companies }, así que sus { -role(num: "other") } de allí no llegarán a tu radar.
}

## features/scope/walk/walkModel.ts
profile-walk-model-leading-a-team = Liderar un equipo
profile-walk-model-people-managers-and-directors-any = Mánagers y directores
profile-walk-model-leading-a-team-2 = liderar un equipo
profile-walk-model-owning-a-product-or-program = Dirigir un producto
profile-walk-model-product-program-or-project-management = Producto, programa, proyecto
profile-walk-model-owning-a-product-or-program-2 = dirigir un producto
profile-walk-model-hands-on-as-the-expert = En primera línea, como experto
profile-walk-model-engineer-scientist-designer-analyst = Ingeniería, ciencia, diseño
profile-walk-model-working-with-customers = Trabajar con clientes
profile-walk-model-sales-partnerships-customer-success = Ventas, éxito del cliente
profile-walk-model-working-with-customers-2 = trabajar con clientes
profile-walk-model-anywhere = Cualquier lugar
profile-walk-model-no-chosen-yet = Aún no hay { $locations } elegidos
profile-walk-model-only = Solo { $names }
profile-walk-model-everywhere = { $choice ->
    [v1] Todos los países
    [v2] Todas las ciudades
   *[v3] En todas partes
}
profile-walk-model-anywhere-in = Cualquier lugar de { $display }
profile-walk-model-anywhere-in-2 = cualquier lugar de { $wide }
profile-walk-model-interested-in = Me interesa
profile-walk-model-not-interested-in = No me interesa
profile-walk-model-or = { $join } o { $parts }
profile-walk-model-not = Excepto: { $off }
profile-walk-model-from-to = { $choice ->
    [yes] en { $first }
   *[no] de { $first2 } a { $last }
}
profile-walk-model-from-to-2 = { $count ->
    [one] en { $display }
    [many] de { $display2 } a { $display3 }
   *[other] de { $display2 } a { $display3 }
}

## features/scope/walk/walkSteps.ts
profile-walk-steps-what-kind-of-role-are = ¿Qué tipo de puesto buscas?
profile-walk-steps-pick-one-or-more = Elige uno o más.
profile-walk-steps-the-kind-of-work-you = El tipo de trabajo del que eres responsable
profile-walk-steps-your-level = Tu nivel
profile-walk-steps-today-and-the-one-you = El actual y al que aspiras.
profile-walk-steps-where-you-are-today-up = Desde donde estás hoy hasta donde aspiras
profile-walk-steps-where-do-you-want-to = ¿Dónde quieres trabajar?
profile-walk-steps-where-you-re-based-and = Dónde vives y hasta dónde irías por el puesto adecuado.
profile-walk-steps-your-bases-and-how-far = Tus bases y hasta dónde irías
profile-walk-steps-any-particular-roles = ¿Algún puesto en concreto?
profile-walk-steps-every-role-of-each-kind = Todos los puestos de cada tipo, o solo los que elijas. Omítelo para quedarte con todos.
profile-walk-steps-particular-roles-or-any-that = Puestos concretos, o cualquiera que encaje
profile-walk-steps-anything-you-care-about-or = ¿Algo que te importe o que quieras evitar?
profile-walk-steps-the-fields-and-industries-the = Campos e industrias que buscar o evitar. Omítelo para no descartar nada.
profile-walk-steps-topics-to-look-for-and = Ámbitos que buscar y ámbitos que descartar

## features/scope/walk/walkModel.ts (by hand)
profile-walk-model-the-place = { $place }

## features/scope/ProfileSuggestions.tsx
profile-suggestions-there = { $length } ahí

## features/scope/walk/ProgressRail.tsx
profile-progress-rail-at = { $title } en { $company_display }

## features/scope/walk/WhereStep.tsx
profile-where-step-in = { $noun }{ $slice } en { $display }

## features/scope/walk/walkModel.ts
profile-walk-model-except = excepto { $names }
profile-walk-model-except-2 = { $every } excepto { $joinAnd }
profile-walk-model-and = { $join } y { $parts }
profile-walk-model-only-2 = Solo { $display }
profile-walk-model-in = en { $display }
profile-walk-model-or-3 = { $parts } o { $parts2 }
profile-walk-model-more = { $said }{ $comma } { $word } { $value } más

## Una lectura fallida, dicha.
profile-scope-section-rules-load-failed = No se pudieron cargar tus exclusiones de empresas
