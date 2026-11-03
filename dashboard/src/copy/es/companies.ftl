## companies: traducción de en/companies.ftl

## features/companies/AddMoreCompanies.tsx
companies-add-more-companies-add-more-companies = Añadir más empresas
companies-add-more-companies-add-by-link = Añadir por enlace
companies-add-more-companies-stop-scanning = Detener el escaneo
companies-add-more-companies-find-the-ones-hiring-for = Encontrar las que contratan para ti
companies-add-more-companies-add-a-company-by-link = Añadir una empresa por enlace
companies-add-more-companies-company-name = Nombre de la empresa
companies-add-more-companies-careers-page-link = Enlace a la página de empleo
companies-add-more-companies-cancel = Cancelar
companies-add-more-companies-a-specific-company = Una empresa concreta
companies-add-more-companies-added-by-its-careers-page = Añadida por su página de empleo
companies-add-more-companies-not-on-this-list-paste = ¿No está en esta lista? Pega el enlace y verás si se puede escanear.
companies-add-more-companies-the-wider-market = El mercado amplio
companies-add-more-companies-stop-scanning-the-wider-market = Dejar de escanear el mercado amplio
companies-add-more-companies-the-wider-market-heading = El mercado amplio
companies-add-more-companies-about-companies-on-the-same = Unas { $about } empresas en los mismos portales de empleo
companies-add-more-companies-each-one-is-checked-daily = Cada una se escanea a diario, y solo las que contratan para puestos de tu radar entran en tu lista.
companies-add-more-companies-first-scan-state = { $scan ->
    [paused] Unas { $about } empresas, primer escaneo en pausa con batería
   *[running] Unas { $about } empresas, primer escaneo en curso
}
companies-add-more-companies-first-scan-note = { $scan ->
    [paused] Continúa donde se quedó cuando conectes el cargador. Las coincidencias hasta ahora están en Otras empresas.
   *[running] Las coincidencias aparecen en Otras empresas a medida que surgen. El escaneo sigue si sales de esta página.
}
companies-add-more-companies-scanned-of-about = escaneadas de unas { $to_check }
companies-add-more-companies-hiring-for-you-so-far = contratan para ti hasta ahora
companies-add-more-companies-companies-scanned = Empresas escaneadas
companies-add-more-companies-about-companies-checked-daily = Unas { $about } empresas, escaneadas a diario
companies-add-more-companies-daily-check-note = { $scan ->
    [paused] En pausa con batería. Los escaneos diarios continúan cuando conectes el cargador.
   *[running] Las que no tienen novedades se escanean de nuevo mañana.
}
companies-add-more-companies-hiring-for-you = contratan para ti
companies-add-more-companies-quiet-today = sin novedades hoy
companies-add-more-companies-couldn-t-add-that-company = No se pudo añadir esa empresa. { $caught }
companies-add-more-companies-try-again = Inténtalo de nuevo.
companies-add-more-companies-add-by-link-dialog = Añadir una empresa por enlace
companies-add-more-companies-acme = Acme
companies-add-more-companies-careers-page-link-aria = Enlace a la página de empleo
companies-add-more-companies-add-company = { $state ->
    [adding] Añadiendo…
   *[idle] Añadir empresa
}

## features/companies/CompaniesData.tsx
companies-data-undo = Deshacer
companies-data-couldn-t-undo-that-change = No se pudo deshacer ese cambio.
companies-data-change-undone = Cambio deshecho.
companies-data-follow-failed = { $direction ->
    [follow] No se pudo seguir a { $name }.
   *[unfollow] No se pudo dejar de seguir a { $name }.
}
companies-data-unfollowed = Dejaste de seguir a { $display }.
companies-data-followed = { $coverage ->
    [covered] Siguiendo a { $company }.
   *[uncovered] Siguiendo a { $company }. El escaneo empieza en cuanto se pueda leer su página de empleo.
}
companies-data-sector-follow-result = { $direction ->
    [follow] Siguiendo todas las empresas que se muestran en { $sector }.{ $paused ->
        [0] { "" }
        [one] { " " }{ $paused } no se ha escaneado todavía.
        [many] { " " }{ $paused } no se han escaneado todavía.
       *[other] { " " }{ $paused } no se han escaneado todavía.
    }
   *[unfollow] Dejaste de seguir { $sector }.
}
companies-data-wider-market-result = { $state ->
    [waiting] Con batería: el escaneo de unas { $size } empresas más empieza cuando conectes el cargador.
    [scanning] Escaneando unas { $size } empresas más, primero las más conocidas.
   *[stopped] Escaneo detenido.{ $added ->
        [0] { "" }
        [one] { " " }Dejaste de seguir { $added } empresa que añadió.
        [many] { " " }Dejaste de seguir { $added } empresas que añadió.
       *[other] { " " }Dejaste de seguir { $added } empresas que añadió.
    }
}
companies-data-wider-market-failed = { $direction ->
    [start] No se pudo empezar a escanear el mercado amplio.
   *[stop] No se pudo dejar de escanear el mercado amplio.
}
companies-data-curated-follow-failed = { $direction ->
    [follow] Error al seguir { $count ->
        [one] empresa
        [many] empresas
       *[other] empresas
    }.
   *[unfollow] Error al dejar de seguir { $count ->
        [one] empresa
        [many] empresas
       *[other] empresas
    } fuera de tu { $curatedList }.
}
companies-data-curated-follow-result = { $direction ->
    [follow] Ahora sigues { $count } { $count ->
        [one] empresa
        [many] empresas
       *[other] empresas
    } más.
   *[unfollow] Dejaste de seguir { $count } { $count ->
        [one] empresa
        [many] empresas
       *[other] empresas
    } fuera de tu { $curatedList }.
}
companies-data-visibility-failed = { $visibility ->
    [shown] No se pudo volver a mostrar { $company } en tu radar.
   *[hidden] No se pudo ocultar { $company } de tu radar.
}
companies-data-visibility-changed = { $visibility ->
    [hidden] { $company } se ha ocultado de tu radar.
   *[shown] { $company } vuelve a estar en tu radar.
}
companies-data-company-added-to-your-roster = Empresa añadida a tu lista.

## features/companies/CompaniesIndex.tsx
companies-index-sectors = Sectores
companies-index-add-more-companies = Añadir más empresas
companies-index-sectors-aria = Sectores

## features/companies/CompaniesSection.tsx
companies-section-loading-companies = Cargando empresas…
companies-section-company = Empresa
companies-section-coverage = Cobertura
companies-section-open = Abiertos
companies-section-companies = Empresas
companies-section-load-failed = No se pudieron cargar las empresas
companies-section-refresh-failed = No se pudieron actualizar las empresas. Se muestra el último resultado.

## features/companies/CompanyRegisterRows.tsx
companies-company-register-rows-open-count = { $count } abiertos{ $mark }
companies-company-register-rows-aka = también llamada { $aliasHit }
companies-company-register-rows-limits-collection = limita la recogida
companies-company-register-rows-also = también { $name }
companies-company-register-rows-showing-of-matches-keep-typing = Se muestran { $shown } de { $matchCount } coincidencias. Sigue escribiendo para acotar la lista.
companies-company-register-rows-planned = Prevista
companies-company-register-rows-coverage-problem = { $cause ->
    [empty_listing] No publica puestos
    [board_missing] Página de empleo desaparecida
   *[other] No se pudo escanear
}
companies-company-register-rows-blocked = Bloqueada
companies-company-register-rows-needs-consent = Requiere consentimiento
companies-company-register-rows-live-or-ready = { $connector ->
    [ready] Lista
   *[other] Activa
}
companies-company-register-rows-scanned-ago = Escaneada hace { $scanned }.
companies-company-register-rows-label-scanned-ago = { $label } · escaneada hace { $scanned }
companies-company-register-rows-scanned-ago-roleband-scans-when = Escaneada hace { $scanned }. { $display } se escanea cuando eliges Escanear ahora.
companies-company-register-rows-not-counted-last-read-ago = { $label } · sin contar, último escaneo hace { $lastRead }
companies-company-register-rows-roleband-last-read-s-roles = { $display } se escaneó por última vez hace { $lastRead }, demasiado tiempo para el recuento de tu radar. Su próximo escaneo vuelve a sumar sus puestos.
companies-company-register-rows-partly-counted = { $label } · contada en parte
companies-company-register-rows-s-scans-have-not-read = Los escaneos de { $display } aún no han leído toda su página de empleo, así que algunos puestos no se cuentan. Su próximo escaneo completo los suma.
companies-company-register-rows-not-counted-yet = { $label } · aún sin contar
companies-company-register-rows-not-counted-why = { $reason ->
    [stale] Los puestos de { $company } se encontraron en un escaneo antiguo que el recuento de tu radar no puede usar. Su próximo escaneo completo los suma.
   *[other] Los puestos de { $company } aún no están en el recuento de tu radar. Su próximo escaneo los suma.
}
companies-company-register-rows-following-not-scanned-yet = Siguiendo · aún sin escanear
companies-company-register-rows-roleband-starts-scanning-as-soon = El escaneo de { $display } empieza en cuanto se pueda leer su página de empleo.
companies-company-register-rows-open-role-counts-are-unavailable = El recuento de puestos abiertos no está disponible
companies-company-register-rows-open-roles-loading = Cargando puestos abiertos
companies-company-register-rows-of-s-roles-name-a = { $unplaced } de los puestos de { $display } indican un lugar que no se reconoce, así que no aparecen con ningún lugar que elijas.
companies-company-register-rows-of-s-roles-fit-no = { $unsorted } de los puestos de { $display } no encajan en ninguna disciplina conocida, así que no aparecen con ninguna disciplina que elijas.
companies-company-register-rows-open-careers-page = Abrir la página de empleo de { $display }
companies-company-register-rows-careers-page = Página de empleo
companies-company-register-rows-show-or-hide-on-radar = { $visibility ->
    [shown] Ocultar { $company } en tu radar
   *[hidden] Mostrar { $company } en tu radar
}
companies-company-register-rows-radar-visibility = { $visibility ->
    [shown] En tu radar
   *[hidden] Oculta en tu radar
}
companies-company-register-rows-scan-now = Escanear { $display } ahora
companies-company-register-rows-scan-now-hint = { $scan ->
    [running] Añadir al escaneo en curso
    [waiting] Ya hay un escaneo en cola
   *[idle] Escanear esta empresa ahora
}
companies-company-register-rows-scan-joined = { $display } es la siguiente en el escaneo en curso.
companies-company-register-rows-scanning = Escaneando { $display }…
companies-company-register-rows-couldn-t-start-a-scan = No se pudo iniciar un escaneo de { $display }.
companies-company-register-rows-followed = { $followed }/{ $total } seguidas
companies-company-register-rows-covered-count = { $coverage ->
    [none] ninguna cubierta
   *[some] { $covered } cubiertas
}
companies-company-register-rows-planned-hidden = { $hiddenPlanned } previstas ocultas
companies-company-register-rows-sector-follow-all = { $direction ->
    [unfollow] Dejar de seguir todas las empresas de { $sector }
   *[follow] Seguir todas las empresas de { $sector }
}
companies-company-register-rows-nothing-to-follow-why = { $coverage ->
    [none] Aún no se puede escanear ninguna empresa de este sector
   *[some] Ninguna empresa coincide con tus filtros
}
companies-company-register-rows-sector-action = { $action ->
    [none] Nada que seguir
    [unfollow] Dejar de seguir todas
   *[follow] Seguir todas
}

## features/companies/CuratedList.tsx
companies-curated-list-confirm = Confirmar

## features/companies/RegisterChrome.tsx
companies-register-chrome-followed-companies-wait-for-your = { $count ->
    [one] { $count } empresa seguida espera tu consentimiento
    [many] { $count } de empresas seguidas esperan tu consentimiento
   *[other] { $count } empresas seguidas esperan tu consentimiento
}
companies-register-chrome-roleband-doesn-t-scan-them = { $count ->
    [one] No se escanea hasta que respondas.
    [many] No se escanean hasta que respondas.
   *[other] No se escanean hasta que respondas.
}
companies-register-chrome-review = Revisar { $display }
companies-register-chrome-companies-failed-the-last-scan = { $count ->
    [one] { $count } empresa falló en el último escaneo
    [many] { $count } de empresas fallaron en el último escaneo
   *[other] { $count } empresas fallaron en el último escaneo
}
companies-register-chrome-rescan = Volver a escanear { $count }
companies-register-chrome-toolbar-stats = { $followed } de { $total } seguidas { $sep } { $openRoles } puestos abiertos { $sep } { $live } activas { $sep } { $ready } listas
companies-register-chrome-following-only = Solo seguidas
companies-register-chrome-show-planned = Mostrar previstas
companies-register-chrome-follow-all = Seguir todas
companies-register-chrome-curated-list-only = Solo la lista seleccionada
companies-register-chrome-show-all-to-see = { $showAll } para ver las { $released } { $search ->
        [query] { $released ->
            [one] coincidencia
            [many] coincidencias
           *[other] coincidencias
        } que no sigues
       *[none] empresas
    }.
companies-register-chrome-show-all-companies = Mostrar todas las empresas
companies-register-chrome-show-planned-to-see = { $showPlanned } para ver { $released } más.
companies-register-chrome-show-planned-button = Mostrar previstas
companies-register-chrome-clear-search-to-see = { $clearSearch } para ver las { $catalogTotal }.
companies-register-chrome-clear-the-search = Borrar la búsqueda
companies-register-chrome-more = { $names } +{ $more } más
companies-register-chrome-followed-companies-are-blocked = { $count ->
    [one] { $count } empresa seguida está bloqueada
    [many] { $count } de empresas seguidas están bloqueadas
   *[other] { $count } empresas seguidas están bloqueadas
}
companies-register-chrome-followed-companies-are-not-scanned = { $count ->
    [one] { $count } empresa seguida aún no se ha escaneado
    [many] { $count } de empresas seguidas aún no se han escaneado
   *[other] { $count } empresas seguidas aún no se han escaneado
}
companies-register-chrome-followed-companies-are-hidden-from = { $count ->
    [one] { $count } empresa seguida está oculta en tu radar
    [many] { $count } de empresas seguidas están ocultas en tu radar
   *[other] { $count } empresas seguidas están ocultas en tu radar
}
companies-register-chrome-companies-needing-attention = Empresas que requieren atención
companies-register-chrome-a-scan-is-already-running = Ya hay un escaneo en curso
companies-register-chrome-rescanning-companies = { $count ->
    [one] Volviendo a escanear { $count } empresa…
    [many] Volviendo a escanear { $count } de empresas…
   *[other] Volviendo a escanear { $count } empresas…
}
companies-register-chrome-couldn-t-start-that-rescan = No se pudo iniciar ese nuevo escaneo.
companies-register-chrome-search-companies = Buscar empresas
companies-register-chrome-find-a-company-alias-or = Busca una empresa, alias o sector
companies-register-chrome-a-search-shows-planned-companies = La búsqueda también muestra empresas previstas
companies-register-chrome-register-empty = { $blamed ->
    [search-following] Ninguna empresa que sigues coincide con “{ $search }”.
    [search] Ninguna empresa coincide con “{ $search }”.
    [following-planned] Aún no sigues ninguna empresa cubierta.
    [following] Aún no sigues ninguna empresa.
    [planned] Todas las empresas de aquí están previstas, aún sin cubrir.
   *[none] Aún no hay empresas.
}

## features/companies/companiesModel.ts
companies-model-ready-to-enable = Lista: síguela para empezar a escanearla
companies-model-your-additions = Tus empresas añadidas
companies-model-other-companies = Otras empresas

## features/companies/followCopy.ts
companies-follow-copy-thousands-of-roles = miles de puestos
companies-follow-copy-hundreds-of-roles = cientos de puestos
companies-follow-copy-more-roles = más puestos
companies-follow-copy-following-all-will-likely-bring = Más empresas traen más puestos, y cada escaneo tarda más.
companies-follow-copy-follow-more = ¿Seguir toda la lista?
companies-follow-copy-roleband-starts-you-with-a = Tu radar empieza con una { $curatedList } de empresas conocidas, para que tus primeros puestos vengan de empleadores que conoces.
companies-follow-copy-you-can-unfollow-any-company = Puedes dejar de seguir cualquier empresa en Ajustes › Empresas seguidas.
companies-follow-copy-keep = Mantener la { $curatedList }
companies-follow-copy-follow-all = Seguir las { $count }
companies-follow-copy-unfollow-outside-your = ¿Dejar de seguir { $count } { $count ->
        [one] empresa
        [many] empresas
       *[other] empresas
    } fuera de tu { $curatedList }?
companies-follow-copy-roleband-stops-scanning-them-your = { $count ->
    [one] Deja de escanearse. Tu { $curatedList }, y cualquier empresa que hayas añadido tú, siguen en tu lista.
    [many] Dejan de escanearse. Tu { $curatedList }, y cualquier empresa que hayas añadido tú, siguen en tu lista.
   *[other] Dejan de escanearse. Tu { $curatedList }, y cualquier empresa que hayas añadido tú, siguen en tu lista.
}
companies-follow-copy-keep-following = Seguir siguiendo
companies-follow-copy-unfollow = Dejar de seguir { $count }
companies-follow-copy-follow-all-in = ¿Seguir las { $count } { $count ->
        [one] empresa
        [many] empresas
       *[other] empresas
    } de { $sector }?
companies-follow-copy-this-will-likely-add-to = Esto probablemente añadirá { $estimate } a tu radar y hará cada escaneo más largo. Puedes dejar de seguir cualquier empresa más tarde.
companies-follow-copy-cancel = Cancelar
companies-follow-copy-follow = ¿Seguir a { $display }?
companies-follow-copy-by-following-you-choose-to = Al seguirla, eliges recoger las ofertas de empleo públicas de { $display }. Puedes dejar de seguirla cuando quieras y la recogida se detiene.
companies-follow-copy-follow-company = Seguir a { $display }
companies-follow-copy-scan-about-more-companies = ¿Escanear unas { $about } empresas más?
companies-follow-copy-only-companies-hiring-for-roles = Solo las empresas que contratan para puestos de tu radar entran en tu lista de seguidas. El resto no se muestra.
companies-follow-copy-roleband-scans-the-best-known = El primer escaneo tarda unas horas, empezando por las empresas más conocidas. Después cada una se escanea a diario, así que un puesto que encaja contigo aparece el día en que se publica.
companies-follow-copy-you-can-stop-at-any = Puedes detenerlo cuando quieras.
companies-follow-copy-start-scanning = Empezar a escanear
companies-follow-copy-follow-every-company-question = ¿Seguir también las otras empresas?
companies-follow-copy-your-radar-covers-the-whole = Tu radar suma las otras empresas a las de la lista.
companies-follow-copy-with-more-companies-scans-take = Con más empresas, los escaneos tardan más.
companies-follow-copy-change-it-any-time-in = Cámbialo cuando quieras en Ajustes.
companies-follow-copy-follow-every-company = Seguirlas
companies-follow-copy-unfollow-company-question = ¿Dejar de seguir a { $display }?
companies-follow-copy-s-job-listings-stop-being = Las ofertas de empleo de { $display } dejan de recogerse. Puedes volver a seguirla cuando quieras.
companies-follow-copy-unfollow-company = Dejar de seguir a { $display }

## features/companies/CompaniesIndex.tsx
companies-index-match-count = { $count } coincidencias
companies-index-followed-of = { $followed }/{ $total }

## features/companies/CompanyRegisterRows.tsx
companies-company-register-rows-sector-open = { $openRoles } abiertos

## Estado de lectura de una empresa y, si está detenida, el motivo.
companies-connector-live = Se escanea automáticamente
companies-connector-family = Lista: se puede leer su página de empleo
companies-connector-active = Añadida por ti y escaneada
companies-connector-planned = Compatibilidad prevista
companies-connector-parked = Su sitio rechaza los escaneos
companies-parked-bot-protected = Su página de empleo bloquea la lectura automática
companies-parked-robots-disallow = { $company } pide que su página de empleo no se lea de forma automática
companies-parked-prohibits-collection = Su página de empleo prohíbe la recogida automática
companies-company-register-rows-board-found = { $reason ->
    [policy_refused] Usa { $family }; su recogida está desactivada
   *[board_silent] Usa { $family }, que no respondió
}
companies-company-register-rows-board-family = { $family ->
    [jibe] Jibe
    [radancy] Radancy TalentBrew
    [avature] Avature
   *[other] { $family }
}
companies-company-register-rows-waiting-to-scan = Esperando escaneo

companies-setup-followed-now = Seguidas ahora
companies-setup-and-more = y { $count } más
companies-setup-well-known = Empresas conocidas
companies-setup-well-known-detail = { $count ->
    [one] { $count } { -company(num: "one") }, primeros { -role(num: "other") } en minutos
    [many] { $count } de { -company(num: "other") }, primeros { -role(num: "other") } en minutos
   *[other] { $count } { -company(num: "other") }, primeros { -role(num: "other") } en minutos
}
companies-setup-every-listed = Todas las empresas listadas
companies-setup-every-listed-detail = { $count ->
    [one] { $count } { -company(num: "one") } de muchos sectores
    [many] { $count } de { -company(num: "other") } de muchos sectores
   *[other] { $count } { -company(num: "other") } de muchos sectores
}
companies-setup-everything = Y otras empresas
companies-setup-everything-detail = Unas { $about } más; el primer escaneo tarda unas horas
companies-setup-choice-aria = Qué empresas se escanean
companies-setup-later = Sigue o deja de seguir empresas una a una cuando quieras en Ajustes > Empresas que sigues.
companies-setup-load-failed = No se pudo cargar la lista de empresas. Las empresas conocidas siguen en seguimiento.
companies-setup-back = Atrás
companies-setup-start = { $choice ->
    [yes] Iniciando…
   *[no] Iniciar el radar
}
