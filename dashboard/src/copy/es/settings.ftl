## Ajustes > Idioma y región (docs/copy.md)

settings-language-title = Idioma y región
settings-language-intro = Elige el idioma de la aplicación y cómo se escriben los números y las fechas. El cambio es inmediato y no se recarga nada de lo que tengas abierto.
settings-language-label = Idioma
settings-language-description = Los nombres de empresas, los títulos y las ofertas se muestran tal como los escribieron las empresas.
settings-language-partial = { $name }, traducido en parte
settings-language-check = { $name }, para revisar textos
settings-region-label = Números y fechas
settings-region-description = Cómo se escriben los números y las fechas: { $number }, { $date }.
settings-region-automatic = Como tu sistema
settings-region-option = { $country }: { $number }, { $date }
settings-save-failed = No se pudo guardar. Inténtalo de nuevo.

## features/settings/ChronographDial.tsx
settings-chronograph-dial-night = NOCHE
settings-chronograph-dial-full-scan = Escaneo completo
settings-chronograph-dial-quick-scan = Escaneo rápido
settings-chronograph-dial-usually-off = Normalmente apagado
settings-chronograph-dial-a-time-you-set = Una hora fijada por ti
settings-chronograph-dial-reconciliation-orbit = Escaneos completos
settings-chronograph-dial-discovery-orbit = Escaneos rápidos
settings-chronograph-dial-authoritative-cycle = Franja del escaneo completo
settings-chronograph-dial-scan-clock = Reloj de escaneo
settings-chronograph-dial-draggable-schedule-marks = Marcas de horario arrastrables
settings-chronograph-dial-scan-running = { $kind ->
    [full] Escaneo completo en curso desde { $time }
   *[quick] Escaneo rápido en curso desde { $time }
}
settings-chronograph-dial-move-planned-scan = { $kind ->
    [full] { $start ->
        [wake] Mover escaneo completo, al encenderlo, hacia las { $time }
       *[clock] Mover escaneo completo, a las { $time }
    }
   *[quick] { $start ->
        [wake] Mover escaneo rápido, al encenderlo, hacia las { $time }
       *[clock] Mover escaneo rápido, a las { $time }
    }
}
settings-chronograph-dial-move-company = Mover { $company } { $scan }, ahora a las { $time }
settings-chronograph-dial-stack-movable = { $stack } { $state ->
        [overdue] pendiente ahora
       *[scheduled] a las { $time }
    }, abre para ver todo, arrastra para separar { $company }
settings-chronograph-dial-stack-locked = { $stack } { $state ->
        [overdue] pendiente ahora
       *[scheduled] a las { $time }
    }, abre para ver todo
settings-chronograph-dial-still-at = { $stack } aún a las { $time }
settings-chronograph-dial-schedule-clock-legend = Leyenda del reloj de horario

## features/settings/ChronographInspector.tsx
settings-chronograph-inspector-share = { $count } comparten { $time }
settings-chronograph-inspector-due-now = Pendiente ahora
settings-chronograph-inspector-scheduled = Programado
settings-chronograph-inspector-closes-roles = Cierra puestos
settings-chronograph-inspector-held-until = Retenido hasta
settings-chronograph-inspector-locked = Bloqueado
settings-chronograph-inspector-scan-schedule-inspector = Inspector del horario de escaneo
settings-chronograph-inspector-stack-movable = Dale a cualquiera su propia hora aquí, o arrastra la marca para separar primero { $company }.
settings-chronograph-inspector-stack-locked = Todas las marcas de este grupo están bloqueadas.
settings-chronograph-inspector-pass = { $mode ->
    [discovery] Escaneo rápido
   *[reconcile] Escaneo completo
}
settings-chronograph-inspector-runs-at = Se ejecuta a las

## features/settings/PlanRunInspector.tsx
settings-plan-run-inspector-scanning-now = Escaneando ahora
settings-plan-run-inspector-when-you-turn-it-on = Al encenderlo
settings-plan-run-inspector-planned = Planificado
settings-plan-run-inspector-companies = Empresas
settings-plan-run-inspector-takes = Duración
settings-plan-run-inspector-starts = Empieza
settings-plan-run-inspector-yes = sí
settings-plan-run-inspector-repeats = Se repite
settings-plan-run-inspector-every = Cada
settings-plan-run-inspector-count-from-the-last-scan = Contar desde el último escaneo
settings-plan-run-inspector-use-my-usual-start = Usar mi hora de inicio habitual
settings-plan-run-inspector-it-also-runs-when-you = También se ejecuta cuando enciendes el equipo tras dos horas o más apagado.
settings-plan-run-inspector-scan-inspector = Inspector de escaneo
settings-plan-run-inspector-repeats-every = { $anchor ->
    [fixed] cada { $hours } h a horas fijas
   *[last] cada { $hours } h después del último escaneo
}
settings-plan-run-inspector-quick-time = { $state ->
    [planned] Escaneos rápidos a las
   *[running] Iniciado
}
settings-plan-run-inspector-quick-scan-time = Hora del escaneo rápido
settings-plan-run-inspector-quick-scan-every = Escaneo rápido cada
settings-plan-run-inspector-a-quick-scan-every-hours = Un escaneo rápido cada { $hours } horas.
settings-plan-run-inspector-quick-scans-every-hours-after = Escaneos rápidos cada { $repeat_hours } horas después del último escaneo.
settings-plan-run-inspector-full-time = { $state ->
    [planned] Terminado a las
   *[running] Iniciado
}
settings-plan-run-inspector-full-scan-done-by = Escaneo completo terminado a las
settings-plan-run-inspector-full-scan-back-to-your = Escaneo completo de vuelta a tu hora de inicio habitual.

## features/settings/RecipesSection.tsx
settings-recipes-section-the-recipe-has-problems = { $count ->
    [one] La receta tiene un problema:
    [many] La receta tiene { $length } de problemas:
   *[other] La receta tiene { $length } problemas:
}
settings-recipes-section-this-careers-page-asks-not = Esta página de empleo pide no ser leída automáticamente, así que no se escaneará.
settings-recipes-section-no-roles-found-on-the = No se encontraron puestos en las primeras páginas.
settings-recipes-section-no-recipes-yet-write-one = Aún no hay recetas. Escribe una abajo y previsualízala.
settings-recipes-section-open = Abrir
settings-recipes-section-recipe-json = Receta (JSON)
settings-recipes-section-save-draft = Guardar borrador
settings-recipes-section-edit = Editar
settings-recipes-section-check-the-whole-page = Comprobar la página completa
settings-recipes-section-use-this-version = Usar esta versión
settings-recipes-section-scan-with-it = Escanear con ella
settings-recipes-section-a-recipe-is-one-json = Una receta es un objeto JSON.
settings-recipes-section-not-valid-json = JSON no válido: { $caught }
settings-recipes-section-could-not-read-it = no se pudo leer
settings-recipes-section-whole-page-check-result = { $choice ->
    [yes] Resultado de la vista previa
   *[no] Resultado de la comprobación completa
}
settings-recipes-section-not-checked-the-whole-page = { $choice ->
    [yes] Comprobada: leyó la página completa, { $found } puestos en { $pages } páginas.
   *[no] Sin comprobar: la página completa no se leyó hasta el final.
}
settings-recipes-section-no-place-stated = sin lugar indicado
settings-recipes-section-in-use = en uso
settings-recipes-section-not-checked = { $choice ->
    [yes] comprobada { $validated_at }
   *[no] sin comprobar
}
settings-recipes-section-couldn-t-preview-the-recipe = No se pudo previsualizar la receta.
settings-recipes-section-saved-version-of = Versión { $version } de { $slug } guardada.
settings-recipes-section-couldn-t-save-the-recipe = No se pudo guardar la receta.
settings-recipes-section-couldn-t-check-the-whole = No se pudo comprobar la página completa.
settings-recipes-section-version-is-now-the-one = La versión { $version } es ahora la que se usa para escanear empresas nuevas.
settings-recipes-section-couldn-t-switch-versions = No se pudo cambiar de versión.
settings-recipes-section-is-now-scanned-with-its = { $company } ahora se escanea con { $slug }. Sus puestos que faltan solo se cierran cuando una versión comprobada lee su página completa.
settings-recipes-section-couldn-t-scan-that-company = No se pudo escanear esa empresa con esta receta.
settings-recipes-section-recipes = Recetas
settings-recipes-section-a-recipe-tells-roleband-how = Una receta indica cómo leer una página de empleo que aún no es compatible.
settings-loading = Cargando…
settings-recipes-section-draft-only = { $choice ->
    [yes] versión { $active_version } en uso
   *[no] solo borrador
}
settings-recipes-section-not-checked-2 = { $choice ->
    [yes] comprobada
   *[no] sin comprobar
}
settings-recipes-section-scans-no-company = { $choice ->
    [yes] escanea { $join }
   *[no] no escanea ninguna empresa
}
settings-recipes-section-new-recipe = Nueva receta
settings-recipes-section-preview = { $choice ->
    [yes] Previsualizando…
   *[no] Vista previa
}
settings-recipes-section-versions = Versiones
settings-recipes-section-versions-2 = Versiones
settings-recipes-section-version = Versión { $version }
settings-recipes-section-scan-a-company-with-it = Escanear una empresa con ella
settings-recipes-section-no-company-is-scanned-with = { $choice ->
    [yes] Escanea { $join }.
   *[no] Aún no se escanea ninguna empresa con ella.
}
settings-company = Empresa
settings-recipes-section-choose-a-company = Elige una empresa

## features/settings/RetentionSection.tsx
settings-retention-section-kept = { $stored } conservadas
settings-retention-section-remove-after = Eliminar tras { $choiceLabel }
settings-cancel = Cancelar
settings-retention-section-1-year = 1 año
settings-retention-section-never = Nunca
settings-retention-section-makes-postings-due-they-are = Con { $days }, { $due } ofertas quedan pendientes de eliminar. Se eliminan durante los próximos escaneos.
settings-retention-section-none-yet = Ninguna todavía
settings-retention-section-text = { $choice ->
    [yes] { " " }· se eliminan más en el próximo escaneo
   *[no] { "" }
}
settings-retention-section-removed = { $at } · { $removed } eliminadas{ $more }
settings-retention-section-data-retention = Conservación de datos
settings-retention-section-roleband-keeps-every-posting-its = Se conserva cada oferta que encuentra un escaneo, así que un cambio en lo que buscas puede poner puestos en tu radar al instante.
settings-retention-section-remove-postings-after = Eliminar ofertas tras
settings-retention-section-a-posting-stops-being-read = Una oferta deja de escanearse cuando ya no está publicada o cuando dejas de seguir a su empresa. Cuando ningún escaneo la ha visto durante este tiempo, se elimina. Los puestos de tu radar, lo que guardaste y su historial nunca se eliminan.
settings-retention-section-no-longer-listed = · { $no_longer_listed } ya no publicadas
settings-retention-section-from-companies-you-stopped-following = · { $stopped_following } de empresas que dejaste de seguir
settings-retention-section-remove-postings-after-2 = Eliminar ofertas tras
settings-retention-section-last-removal = Última eliminación
settings-retention-section-due-for-removal = Pendientes de eliminar
settings-retention-section-due-count = { $count ->
    [one] { $due } { -posting(num: "one") }
    [many] { $due } de { -posting(num: "other") }
   *[other] { $due } { -posting(num: "other") }
}
settings-retention-section-due-detail = { $state ->
    [never] No se elimina nada mientras esto esté en Nunca.
   *[set] Las ofertas pendientes se eliminan durante los escaneos, nunca al guardar.
}
settings-retention-section-saved = Guardado.

## features/settings/ScheduleChronograph.tsx
settings-schedule-chronograph-on-wake = { $kind ->
        [full] Escaneo completo
       *[quick] Escaneo rápido
    } al encender
settings-schedule-chronograph-due = pendiente · { $name }
settings-schedule-chronograph-waiting = { $waiting ->
    [paused] En pausa
    [day_off] Día libre
   *[mains] Esperando corriente
}
settings-schedule-chronograph-waiting-status = { $waiting ->
    [paused] en pausa
    [day_off] sin escaneos hoy
   *[mains] con batería
}
settings-schedule-chronograph-the-next-scan-runs-once = el próximo escaneo se ejecuta cuando se conecte a la corriente
settings-schedule-chronograph-next-scan = próximo escaneo { $time }
settings-schedule-chronograph-hub-title = { $state ->
    [running] Escaneando ahora
   *[next] Próximo escaneo
}
settings-schedule-chronograph-due-now = pendiente ahora
settings-schedule-chronograph-on-wake-2 = al encender
settings-schedule-chronograph-when-you-turn-it-on = al encenderlo, hacia las { $time }
settings-schedule-chronograph-next-dispatch = Próximo escaneo
settings-schedule-chronograph-hub-stack = { $mode ->
    [reconcile] { $count } escaneos completos
   *[discovery] { $count } escaneos rápidos
}
settings-schedule-chronograph-hub-company = { $mode ->
    [reconcile] { $company } · escaneo completo
   *[discovery] { $company } · escaneo rápido
}
settings-schedule-chronograph-projected-through = proyectado hasta { $time }
settings-schedule-chronograph-stack-movable = { $count } marcas comparten { $time }: elige cualquier hora abajo, o arrastra la marca para separar { $company }.
settings-schedule-chronograph-stack-locked = { $count } marcas comparten { $time }. Todas están bloqueadas.
settings-schedule-chronograph-saving-schedule = Guardando horario…
settings-schedule-chronograph-drag-a-scan-to-move = Arrastra un escaneo para moverlo · haz clic para fijar la hora exacta

## features/settings/ScheduleSection.tsx
settings-schedule-section-how-scanning-works = Cómo funciona el escaneo
settings-schedule-section-reads-every-company-s-whole = Lee la página de empleo completa de cada empresa que sigues, así que también puede cerrar un puesto que ya no existe. Se ejecuta cuando enciendes el equipo y al menos una vez al día.
settings-schedule-section-looks-for-new-and-changed = Busca puestos nuevos y modificados en cada empresa que sigues, cada { $repeat_hours } horas mientras el equipo está encendido. Nunca cierra un puesto.
settings-schedule-section-when-the-computer-is-off = Cuando el equipo está apagado
settings-schedule-section-nothing-runs-and-missed-scans = No se ejecuta nada y los escaneos perdidos no se repiten: el siguiente se ejecuta cuando lo enciendes. La programación sigue las horas en que sueles usar el equipo, así que no hay nada que configurar.
settings-schedule-section-times-you-set = Horas fijadas por ti
settings-schedule-section-a-company-with-a-time = Una empresa con hora propia la conserva. Arrastra su marca o haz clic en ella para escribir una hora.
settings-schedule-section-outer-orbit-is-the-full = La órbita exterior es el escaneo completo y la interior, el escaneo rápido; cada arco dura lo que tarda el escaneo. Las horas sombreadas son cuando el equipo suele estar apagado, y la aguja marca la hora actual.
settings-schedule-section-discovery = Escaneo rápido
settings-schedule-section-probes-a-company-s-board = Revisa la página de empleo de una empresa en busca de puestos nuevos y modificados. Puede añadir o actualizar un puesto, pero nunca cierra ninguno.
settings-schedule-section-reconciliation = Escaneo completo
settings-schedule-section-the-authoritative-cycle-only-this = Solo un escaneo completo puede cerrar un puesto que ha desaparecido, y solo tras leer completa la página de empleo de la empresa.
settings-schedule-section-the-cycle = Escaneos simultáneos
settings-schedule-section-marks-coming-due-together-dispatch = Los escaneos que vencen a la vez se ejecutan juntos, hasta { $maxParallel } sitios a la vez, así que el arco muestra cuánto duran, no solo cuándo empiezan.
settings-schedule-section-editing = Edición
settings-schedule-section-drag-a-mark-around-the = Arrastra una marca por el dial o haz clic en ella para escribir una hora. Las horas se ajustan a intervalos de 10 minutos. Las marcas que bloquea una política del proveedor siguen bloqueadas.
settings-schedule-section-outer-orbit-is-reconciliation-inner = La órbita exterior son los escaneos completos y la interior, los rápidos; las horas sombreadas son la noche, y la aguja marca la hora local actual.
settings-schedule-section-first-scan-of-the-day = Primer escaneo del día
settings-schedule-section-full-scan-done-by = Escaneo completo, terminado a las
settings-schedule-section-then-while-it-is-on = Después, mientras está encendido
settings-schedule-section-a-quick-scan-every-hours = un escaneo rápido cada { $repeat_hours } horas
settings-schedule-section-days = Días
settings-schedule-section-power = Alimentación
settings-schedule-section-only-when-plugged-in = Solo conectado a la corriente
settings-schedule-section-pause = Pausa
settings-schedule-section-paused-until = En pausa hasta
settings-schedule-section-resume = Reanudar
settings-schedule-section-after-two-hours-or-more = { $learned } Tras dos horas o más apagado, se ejecuta un escaneo completo cuando vuelves; los escaneos perdidos no se repiten.
settings-schedule-section-need-attention = { $count ->
    [one] { $count } requiere atención
    [many] { $count } requieren atención
   *[other] { $count } requieren atención
}
settings-schedule-section-scan-clock = Reloj de escaneo
settings-schedule-section-next-scans = Próximos escaneos
settings-schedule-section-companies = { $companies } empresas · { $duration }
settings-schedule-section-companies-keep-a-time-you = { $count ->
    [one] { $count } empresa conserva una hora fijada por ti
    [many] { $count } de empresas conservan una hora fijada por ti
   *[other] { $count } empresas conservan una hora fijada por ti
}
settings-schedule-section-upcoming = Próximos
settings-schedule-section-bindings-projected-through = { $count ->
    [one] Escaneo completo · proyectado hasta ~{ $end }
    [many] { $count } de escaneos · proyectados hasta ~{ $end }
   *[other] { $count } escaneos · proyectados hasta ~{ $end }
}
settings-schedule-section-more-see-all-deadlines = +{ $count } más · ver todos los plazos
settings-schedule-section-discovery-cadence = Intervalo de escaneo rápido
settings-schedule-section-adapts-to-8-12-24h = se adapta a 8 / 12 / 24 h tras escaneos rápidos vacíos
settings-schedule-section-only-this-cycle-can-close = solo los escaneos completos pueden cerrar puestos que faltan
settings-schedule-section-provider-pressure = Carga por proveedor
settings-schedule-section-max = { $max_parallel_providers } máx.
settings-schedule-section-one-binding-per-provider-in = una vinculación por proveedor en cada fragmento
settings-schedule-section-plan-roster = { $companies } empresas · { $roster } en cada escaneo completo
settings-schedule-section-plan-roster-pinned = { $companies } empresas · { $roster } en cada escaneo completo · { $pinned } a una hora fijada por ti
settings-schedule-section-plan-roster-excepted = { $companies } empresas · { $roster } en cada escaneo completo · { $excepted } exceptuadas
settings-schedule-section-plan-roster-pinned-excepted = { $companies } empresas · { $roster } en cada escaneo completo · { $pinned } a una hora fijada por ti · { $excepted } exceptuadas
settings-schedule-section-timers-roster = { $companies } empresas · { $scheduled } programadas
settings-schedule-section-timers-roster-excepted = { $companies } empresas · { $scheduled } programadas · { $excepted } exceptuadas
settings-schedule-section-timers-roster-reconcile-only = { $companies } empresas · { $scheduled } programadas · { $reconcileOnly } solo escaneo completo
settings-schedule-section-timers-roster-excepted-reconcile-only = { $companies } empresas · { $scheduled } programadas · { $excepted } exceptuadas · { $reconcileOnly } solo escaneo completo
settings-schedule-section-every-company-s-scans = Escaneos de cada empresa
settings-schedule-section-a-full-scan-reads-a = Un escaneo completo lee toda la página de empleo de una empresa y puede cerrar un puesto que ya no existe. Un escaneo rápido busca puestos nuevos y modificados y nunca cierra ninguno.
settings-schedule-section-last-full-scan = Último escaneo completo
settings-schedule-section-last-quick-scan = Último escaneo rápido
settings-schedule-section-how-it-is-scanned = Cómo se escanea
settings-schedule-section-not-yet = Todavía no
settings-schedule-section-not-available = No disponible
settings-schedule-section-until = hasta { $cooldown_until }
settings-schedule-section-persisted-deadlines = Plazos guardados
settings-schedule-section-discovery-can-add-or-update = Los escaneos rápidos pueden añadir o actualizar puestos, pero nunca cierran un puesto que falta. Un escaneo completo cierra puestos solo tras leer completa la página de empleo. La espera del proveedor mueve la hora permitida sin sobrescribir el plazo natural de la empresa.
settings-schedule-section-provider-state = Estado del proveedor
settings-schedule-section-reconciliation-only = Solo escaneos completos
settings-schedule-section-non-authoritative = no puede cerrar puestos
settings-schedule-section-not-scheduled = Sin programar
settings-schedule-section-only-when-you-press-scan = Solo cuando pulsas Escanear ahora
settings-schedule-section-only-after-you-allow-it = Solo después de que lo permitas
settings-schedule-section-full-scan-at = escaneo completo a las { $reconcile_anchor_minute }
settings-schedule-section-quick-scan-at = escaneo rápido a las { $discovery_anchor_minute }
settings-schedule-section-its-own-time = Hora propia: { $times }
settings-schedule-section-planned-scans = { $scans ->
    [all] Todos los escaneos planificados
   *[full] Solo escaneos completos
}
settings-schedule-section-only-when-you-scan = Solo cuando escaneas
settings-schedule-section-needs-your-ok = Necesita tu permiso
settings-schedule-section-policy-denied = Denegado por política
settings-schedule-section-cooling-down = En espera
settings-schedule-section-unscheduled = Sin programar
settings-schedule-section-manual-priority = Prioridad manual
settings-schedule-section-paused = En pausa
settings-schedule-section-provider-policy-denies-scheduled-collection = su sitio no permite escaneos programados
settings-schedule-section-provider-scheduling-is-paused = la programación del proveedor está en pausa
settings-schedule-section-setting-scan-times = { $count ->
    [one] Asignando horarios de escaneo a { $count } empresa nueva.
    [many] Asignando horarios de escaneo a { $count } empresas nuevas.
   *[other] Asignando horarios de escaneo a { $count } empresas nuevas.
}
settings-schedule-section-cooling-down-until = en espera hasta { $cooldown_until }
settings-schedule-section-how-scanning-works-2 = Cómo funciona el escaneo
settings-schedule-section-how-scanning-works-3 = Cómo funciona el escaneo
settings-schedule-section-1-hour = 1 hora
settings-schedule-section-3-hours = 3 horas
settings-schedule-section-until-tomorrow = Hasta mañana
settings-schedule-section-couldn-t-save-that-change = No se pudo guardar ese cambio. Inténtalo de nuevo.
settings-schedule-section-plan-settings = Ajustes del plan
settings-schedule-section-starts-about = { $source ->
    [usual] Tu hora de inicio habitual, aprendida. Empieza hacia las { $time } · { $companies } empresas
   *[set] Empieza hacia las { $time } · { $companies } empresas
}
settings-schedule-section-starts-about-duration = { $source ->
    [usual] Tu hora de inicio habitual, aprendida. Empieza hacia las { $time } · { $companies } empresas · { $duration }
   *[set] Empieza hacia las { $time } · { $companies } empresas · { $duration }
}
settings-schedule-section-no-time-set = Sin hora fijada: se ejecuta cuando enciendes el equipo y al menos una vez al día · { $companies } empresas
settings-schedule-section-no-time-set-duration = Sin hora fijada: se ejecuta cuando enciendes el equipo y al menos una vez al día · { $companies } empresas · { $duration }
settings-schedule-section-clear-ready-by = { $fallback ->
    [usual] Usar mi hora de inicio habitual
   *[none] Borrar
}
settings-schedule-section-scan-days = Días de escaneo
settings-schedule-section-days-a-week = { $count ->
    [7] Todos los días
    [one] { $count } día a la semana
    [many] { $count } días a la semana
   *[other] { $count } días a la semana
}
settings-schedule-section-power-note = { $power ->
    [waiting] Con batería ahora: el próximo escaneo espera a la corriente.
    [mains] Los escaneos esperan mientras el equipo funciona con batería.
   *[any] Los escaneos también se ejecutan con batería.
}
settings-schedule-section-pause-scans = Pausar escaneos
settings-schedule-section-when-roleband-scans = Cuándo se escanea
settings-schedule-section-next-scans-2 = Próximos escaneos
settings-schedule-section-run-title = { $state ->
    [running] { $kind ->
            [full] Escaneo completo
           *[quick] Escaneo rápido
        } · escaneando
    [ready] { $kind ->
            [full] Escaneo completo
           *[quick] Escaneo rápido
        } · listo a las { $time }
    [wake] { $kind ->
            [full] Escaneo completo
           *[quick] Escaneo rápido
        } · al encenderlo
   *[planned] { $kind ->
            [full] Escaneo completo
           *[quick] Escaneo rápido
        }
}
settings-schedule-section-times-you-set-2 = Horas fijadas por ti
settings-schedule-section-scan-at-a-time-you-set = { $mode ->
    [reconcile] Escaneo completo a una hora fijada por ti
   *[discovery] Escaneo rápido a una hora fijada por ti
}
settings-schedule-section-upcoming-scans = Próximos escaneos
settings-schedule-section-title-due-now = { $title } · pendiente ahora
settings-schedule-section-pass-provider = { $mode ->
    [reconcile] Escaneo completo · { $provider }
   *[discovery] Escaneo rápido · { $provider }
}
settings-schedule-section-scheduler-policy = Política del programador
settings-schedule-section-deadlines-link = { $schedule ->
    [plan] Escaneos de cada empresa
   *[timers] Todos los plazos guardados
}
settings-schedule-section-every-company-s-scans-2 = Escaneos de cada empresa
settings-schedule-section-what-the-columns-mean = Qué significan las columnas
settings-schedule-section-all-persisted-deadlines-2 = Todos los plazos guardados
settings-schedule-section-how-scheduling-safety-works = Cómo funciona la seguridad de la programación
settings-schedule-section-schedule = Horario

## features/settings/charts/plan.ts
settings-plan-hours-minutes = { $hours } h { $minutes } min
settings-plan-hours = { $hours } h
settings-plan-still-learning-when-your-computer = Aún aprendiendo cuándo está encendido tu equipo: { $observed_days } de { $needed_days } días observados.
settings-plan-learned-every-day = Aprendido de los últimos { $days } días: tu equipo está { $usual ->
        [all] encendido todo el día
        [off] normalmente apagado
       *[set] encendido { $times }
    } todos los días.
settings-plan-learned-weekdays-weekends = Aprendido de los últimos { $days } días: tu equipo está { $weekdays ->
        [all] encendido todo el día
        [off] normalmente apagado
       *[set] encendido { $weekdayTimes }
    } entre semana y { $weekends ->
        [all] encendido todo el día
        [off] normalmente apagado
       *[set] encendido { $weekendTimes }
    } los fines de semana.
settings-plan-learned = Aprendido de los últimos { $days } días: tu equipo está { $usual ->
        [all] encendido todo el día
        [off] normalmente apagado
       *[set] encendido { $times }
    }.
settings-plan-learned-unseen = Aprendido de los últimos { $days } días: tu equipo está aún no visto encendido.
settings-plan-companies = { $kind ->
        [full] Escaneo completo
       *[quick] Escaneo rápido
    } · { $companies } empresas
settings-plan-scan-kind = { $kind ->
    [full] Escaneo completo
   *[quick] Escaneo rápido
}

## features/settings/charts/schedule.ts
settings-schedule-24-hour-scan-clock-planned = Reloj de escaneo de 24 horas: { $runs } { $runs ->
        [one] escaneo planificado
        [many] escaneos planificados
       *[other] escaneos planificados
    }, y { $pinned } { $pinned ->
        [one] empresa
        [many] empresas
       *[other] empresas
    } a una hora fijada por ti.
settings-schedule-24-hour-scan-clock-planned-next = Reloj de escaneo de 24 horas: { $runs } { $runs ->
        [one] escaneo planificado
        [many] escaneos planificados
       *[other] escaneos planificados
    }, el siguiente un { $kind ->
        [full] escaneo completo
       *[quick] escaneo rápido
    } de { $companies } empresas, y { $pinned } { $pinned ->
        [one] empresa
        [many] empresas
       *[other] empresas
    } a una hora fijada por ti.
settings-schedule-24-hour-chronograph-discovery-probes = Reloj de escaneos de 24 horas: { $probes } escaneos rápidos, { $reconciliations } escaneos completos y { $excluded } empresas excluidas o sin programar.
settings-schedule-stack = { $count } { $schedule ->
        [plan] { $mode ->
            [reconcile] escaneos completos
           *[discovery] escaneos rápidos
        }
       *[timers] { $mode ->
            [reconcile] escaneos completos
           *[discovery] escaneos rápidos
        }
    }
settings-schedule-mode-name = { $schedule ->
    [plan] { $mode ->
        [discovery] escaneo rápido
       *[reconcile] escaneo completo
    }
   *[timers] { $mode ->
        [discovery] escaneo rápido
       *[reconcile] escaneo completo
    }
}
settings-schedule-provider-policy-denies-scheduled-collection = La política del proveedor deniega la recopilación programada.
settings-schedule-provider-scheduling-is-paused = La programación del proveedor está en pausa.
settings-schedule-scan-schedule-is-not-set = El horario de escaneo aún no está configurado.
settings-schedule-cancel-the-queued-manual-scan = Cancela el escaneo manual en cola antes de cambiar esta hora.

## features/settings/useDialDrag.ts
settings-use-dial-drag-drag-a-mark-to-reschedule = Arrastra una marca para reprogramarla · haz clic para fijar una hora exacta
settings-use-dial-drag-moved-to = { $company } { $scan } movido a las { $time }.
settings-use-dial-drag-couldn-t-move-that-scan = No se pudo mover ese escaneo. Inténtalo de nuevo.

## features/settings/usePlanDrag.ts
settings-use-plan-drag-quick-scans-moved-one-at = Escaneos rápidos movidos: uno a las { $time }.
settings-use-plan-drag-full-scan-moved-to-done = Escaneo completo movido a las { $start }, terminado a las { $doneBy }.

## routes/SettingsRoute.tsx
settings-route-settings-sections = Secciones de ajustes

## features/settings/charts/plan.ts (by hand)
settings-plan-usually-off = Normalmente apagado
settings-plan-all-day = Todo el día

## features/settings/ChronographInspector.tsx
settings-chronograph-inspector-every = { $unit ->
    [day] cada { $count } d
   *[hour] cada { $count } h
}
settings-chronograph-inspector-no-cadence = -
settings-chronograph-inspector-time = { $company } { $scan }: hora
settings-chronograph-inspector-no = no

## features/settings/RecipesSection.tsx
settings-recipes-section-saved = guardada { $created_at }
settings-recipes-section-load-failed = No se pudieron cargar las recetas
settings-recipes-section-refresh-failed = No se pudieron actualizar las recetas. Se muestra el último resultado.
settings-recipes-section-versions-load-failed = No se pudieron cargar las versiones de esta receta
settings-recipes-section-versions-refresh-failed = No se pudieron actualizar las versiones de esta receta. Se muestra el último resultado.

## features/settings/RetentionSection.tsx
settings-retention-section-days = { $days } días
settings-retention-section-due = { $days } ({ $due } pendientes)
settings-retention-section-load-failed = No se pudo cargar la conservación de datos

## features/settings/ScheduleChronograph.tsx
settings-schedule-chronograph-companies = { $count } empresas
settings-schedule-chronograph-in-hours-minutes = en { $hours } h { $minutes } min
settings-schedule-chronograph-in-minutes = en { $minutes } min
settings-schedule-chronograph-since = desde { $time }

## features/settings/ScheduleSection.tsx
settings-schedule-section-every = cada { $cadence }
settings-schedule-section-loading = Cargando el horario de escaneo…
settings-schedule-section-load-failed = No se pudo cargar el horario de escaneo
settings-schedule-section-empty = Aún no hay horario de escaneo
settings-schedule-section-now = ahora

## features/settings/charts/plan.ts
settings-plan-min = { $minutes } min
settings-plan-to = de { $start } a { $end }
settings-plan-about = alrededor de { $duration }

## Frecuencia de un horario e intervalo del escaneo rápido, en horas o días.
settings-schedule-hours = { $hours } h
settings-schedule-days = { $days } d

settings-plugins-section-coming-soon = Próximamente
settings-plugins-section-coming-soon-note = Activar y gestionar plugins aquí llegará en una versión posterior.
settings-plugins-section-title = Plugins
settings-plugins-section-intro = Complementos opcionales que aportan más datos y funciones.
settings-plugins-section-search = Buscar plugins
settings-plugins-section-on-count = { $on } de { $total } activados
settings-plugins-section-none = Aún no hay plugins instalados.
settings-price-feed-title = Precios de la acción
settings-price-feed-intro = Precios de cierre diarios de las empresas cotizadas, mostrados en sus perfiles y actualizados una vez al día.
settings-price-feed-source = Tiingo
settings-price-feed-source-terms = Gratis para uso personal con tu propia clave.
settings-price-feed-key-state =
    { $origin ->
        [settings] Clave guardada
        [environment] Clave definida fuera de la app
       *[none] Aún no hay clave
    }
settings-price-feed-priced =
    { $count ->
        [one] { $count } empresa · último cierre { $date }
        [many] { $count } de empresas · último cierre { $date }
       *[other] { $count } empresas · último cierre { $date }
    }
settings-price-feed-updated = actualizado { $ago }
settings-price-feed-add = Añadir clave
settings-price-feed-replace = Cambiar clave
settings-price-feed-remove = Quitar clave
settings-price-feed-dialog-title = Clave de Tiingo
settings-price-feed-dialog-note = Pega la clave de tu cuenta de Tiingo. Se queda en este ordenador y solo se envía a Tiingo.
settings-price-feed-dialog-field = Clave
settings-price-feed-dialog-save =
    { $choice ->
        [yes] Guardando
       *[no] Guardar clave
    }
settings-price-feed-unauthorized = Tiingo rechazó la clave en la última actualización. Revísala en tu cuenta de Tiingo y vuelve a guardarla.
settings-price-feed-rate-limited = Se alcanzó el límite por hora de Tiingo. Los precios que faltan llegan cuando se reinicie.
settings-price-feed-saved =
    { $check ->
        [ok] Guardada, y Tiingo respondió. Los demás precios llegan según lo permitan sus límites.
       *[other] Guardada. Tiingo aún no pudo comprobar la clave; los precios llegan cuando responda.
    }
settings-price-feed-waiting =
    { $count ->
        [one] { $count } más { $time }
        [many] { $count } más { $time }
       *[other] { $count } más { $time }
    }
settings-price-feed-updating = Actualizando precios…
settings-price-feed-update-now = Actualizar ahora
settings-price-feed-removed = Quitada. Los precios ya mostrados se mantienen.
settings-price-feed-load-failed = No se pudo cargar la configuración de precios de la acción
settings-plugins-section-no-match = Ningún plugin instalado coincide con tu búsqueda.
settings-plugins-section-state =
    { $state ->
        [needs_approval] Necesita aprobación
        [enabled] Activado
        [disabled] Desactivado
        [paused] En pausa
        [updating] Actualizando
        [removed] Desinstalado
       *[other] Instalado
    }
settings-plugins-section-slot = { $slot ->
        [pay_levels] bandas de compensación
        [pay_observations] estimaciones de compensación
        [company_facts] datos de la empresa
        [company_benefits] beneficios
       *[other] otros datos
    }
settings-plugins-section-answers = Responde a { $slots }
settings-plugins-section-brings = Aporta { $slots }
settings-plugins-section-waiting = Esperando su primera actualización
settings-plugins-section-read =
    { $companies ->
        [one] { $read } de { $companies } { -company(num: "one") } leída
        [many] { $read } de { $companies } de { -company(num: "other") } leídas
       *[other] { $read } de { $companies } { -company(num: "other") } leídas
    }
settings-plugins-section-next-update = próxima actualización { $when }
settings-plugins-section-paused = en pausa
settings-plugins-section-use = Usar { $name }
settings-plugins-section-open-settings = Ajustes de { $name }
settings-plugins-section-start = Iniciar
settings-plugins-section-start-name = Iniciar { $name }
settings-plugins-section-pause = Pausar
settings-plugins-section-resume = Reanudar
settings-plugins-section-turn-on-first = Actívalo primero
settings-plugins-section-approve-first = Apruébalo primero
settings-plugins-section-more = Más plugins
settings-plugins-section-more-note = Pronto podrás buscar y añadir plugins aquí. Por ahora, instala uno desde la línea de comandos, en la carpeta RoleBand:
settings-plugins-section-waiting-wake = La actualización empieza cuando este Mac se despierte del todo.
settings-plugins-section-moved =
    { $moved ->
        [one] Cambiaron las estimaciones de { $moved } puesto
        [many] Cambiaron las estimaciones de { $moved } de puestos
       *[other] Cambiaron las estimaciones de { $moved } puestos
    } en { $companies ->
        [one] { $companies } empresa
        [many] { $companies } de empresas
       *[other] { $companies } empresas
    } { $when }.
settings-plugins-section-pending =
    { $pending ->
        [one] Actualizando estimaciones: falta { $pending } puesto.
        [many] Actualizando estimaciones: faltan { $pending } de puestos.
       *[other] Actualizando estimaciones: faltan { $pending } puestos.
    }
settings-plugins-section-review = Revisar y aprobar
settings-plugins-section-approve-title = ¿Aprobar este plugin?
settings-plugins-section-robots-heading = Reglas del sitio
settings-plugins-section-robots-reading = Leyendo las reglas de cada sitio
settings-plugins-section-robots-failed = No se pudieron leer las reglas de los sitios ahora mismo. Las sigue a medida que las encuentra en cada actualización.
settings-plugins-section-robots-site =
    { $state ->
        [none] no fija ninguna regla contra RoleBand.
        [refused] no muestra sus reglas, así que RoleBand lo trata como cerrado.
        [failed] no se pudo contactar; sus reglas se leen en cada actualización.
       *[rules] pide a RoleBand que omita estas páginas:
    }
settings-plugins-section-robots-more = y { $count } más
settings-plugins-section-robots-allow = Saltarse estas reglas
settings-plugins-section-robots-allow-note = Estas reglas se respetan salvo que lo permitas, y los sitios pueden ralentizar o bloquear este equipo por ello. Si un sitio cambia sus reglas, se te preguntará de nuevo.
settings-plugins-section-robots-title = ¿Leer pese a las reglas de los sitios?
settings-plugins-section-robots-nothing = Ahora mismo ninguno de sus sitios fija una regla contra RoleBand.
settings-plugins-section-robots-allow-button = Permitir
settings-plugins-section-robots-close = Cerrar
settings-plugins-section-turn-on-title = ¿Activar este plugin?
settings-plugins-section-turn-on-lead = Mientras está activado, lo que aporta sustituye a los datos integrados en todas las empresas.
settings-plugins-section-turn-on = Activar
settings-plugins-section-approve-lead = Aprobarlo le permite ejecutarse en este Mac. Mientras está activado, lo que aporta sustituye a los datos integrados en todas las empresas. Se ejecuta por su cuenta, solo lee los sitios de abajo y nunca cambia tus niveles.
settings-plugins-section-approve-gap = Hasta que lea una empresa, esa empresa no muestra nada de lo que aporta, ni tampoco datos integrados en su lugar.
settings-plugins-section-approve-read = Leído hasta ahora: { $slots }.
settings-plugins-section-approve-slot = { $slot }: { $count }
settings-plugins-section-approve-left = Leer el resto lleva unas { $duration } de actualizaciones, a unos { $pace } por empresa.
settings-plugins-section-approve-reads = Lee
settings-plugins-section-approve-updates = Actualizaciones
settings-plugins-section-approve-licence = Licencia
settings-plugins-section-credit = Crédito
settings-plugins-section-approve-code = Código
settings-plugins-section-approve-identity =
    { $identity ->
        [identified] Los visita abiertamente, como RoleBand.
        [browser_identity] Los visita como si fuera un navegador web.
        [tls_fingerprint] Los visita como si fuera un navegador web, hasta en la conexión.
        [headless] Los visita en un navegador web oculto.
        [proxy] Los visita a través de otra red.
       *[other] Los visita de una forma que esta versión no sabe describir.
    }
settings-plugins-section-approve-needs =
    { $need ->
        [followed_companies] Recibe la lista de empresas que sigues.
       *[other] Recibe otros datos guardados aquí.
    }
settings-plugins-section-approve-facts = Puede indicar de cada empresa: { $fields }.
settings-plugins-section-fact-field =
    { $field ->
        [display_name] nombre
        [ticker] símbolo bursátil
        [is_public] si cotiza en bolsa
        [headcount] plantilla
        [hq_city] ciudad de la sede
        [website] sitio web
        [year_founded] año de fundación
        [logo_url] logotipo
        [brand_color] color de marca
       *[other] otro dato
    }
settings-plugins-section-approve-fact-rank = Mientras está activado, se muestran en lugar de los integrados, nunca a su lado.
settings-plugins-section-approve-still-on = Sigue activado. Cambió desde que lo aprobaste, así que te espera antes de ejecutarse o responder de nuevo.
settings-plugins-section-schedule =
    { $schedule ->
        [daily] A diario, enchufado
        [weekly] Cada semana, enchufado
        [monthly] Cada mes, enchufado
        [manual] Solo cuando lo pidas
       *[other] Con su propio calendario
    }
settings-plugins-section-approve = Aprobar
settings-plugins-section-approve-and-turn-on = Aprobar y activar
settings-plugins-section-approve-and-use = Aprobar y reanudar
settings-plugins-section-remove-title = ¿Eliminar los datos de este plugin?
settings-plugins-section-remove-lead = { $what ->
        [rows] Esto elimina los { $kinds } que añadió, y las estimaciones y el historial de compensación calculados a partir de ellos. Las estimaciones vuelven a los datos integrados. Lo que registró como historial se queda, sin leer.
       *[history] Esto elimina las estimaciones calculadas a partir de él y lo que anotó sobre su propia lectura. Los { $kinds } que registró se quedan como historial, sin leer mientras está desactivado.
    }
settings-plugins-section-remove-confirm = Escribe { $name } para confirmar
settings-plugins-section-remove = Eliminar datos
settings-plugins-section-removed =
    { $rows ->
        [0] Se eliminaron sus datos.
        [one] Se eliminó { $rows } fila.
        [many] Se eliminaron { $rows } de filas.
       *[other] Se eliminaron { $rows } filas.
    }
settings-plugins-section-failed =
    { $action ->
        [review] No se pudo cargar lo que pide hacer. Inténtalo de nuevo.
        [approve] No se pudo aprobar. Inténtalo de nuevo.
        [on_after_approve] Aprobado, pero no se pudo activar. Inténtalo de nuevo.
        [on] No se pudo activar. Inténtalo de nuevo.
        [off] No se pudo desactivar. Inténtalo de nuevo.
        [update] No se pudo iniciar la actualización. Inténtalo de nuevo.
        [pause] No se pudo pausar. Inténtalo de nuevo.
        [resume] No se pudo reanudar. Inténtalo de nuevo.
        [schedule] No se pudo cambiar la frecuencia de actualización. Inténtalo de nuevo.
        [uninstall] No se pudo desinstalar. Inténtalo de nuevo.
        [remove] No se pudieron eliminar sus datos. Inténtalo de nuevo.
        [robots] No se pudo guardar tu elección sobre las reglas de los sitios. Inténtalo de nuevo.
       *[other] Eso no funcionó. Inténtalo de nuevo.
    }
settings-plugins-section-loading = Cargando los plugins…
settings-plugins-section-load-failed = No se pudieron cargar los plugins
settings-plugins-section-refresh-failed = No se pudieron actualizar los plugins. Se muestra el último resultado.
settings-plugin-settings-back = Todos los plugins
settings-plugin-settings-not-found = Este plugin no está instalado.
settings-plugin-settings-needs-approval = Necesita tu aprobación para poder ejecutarse: es nuevo, o cambió desde que lo aprobaste.
settings-plugin-settings-updates = Actualizaciones
settings-plugin-settings-how-often = Frecuencia
settings-plugin-settings-option =
    { $schedule ->
        [daily] Diaria
        [weekly] Semanal
        [monthly] Mensual
        [manual] Cuando lo pidas
       *[other] Otra
    }
settings-plugin-settings-suggests =
    { $schedule ->
        [daily] El plugin sugiere a diario. Las actualizaciones programadas esperan a que este Mac esté enchufado.
        [weekly] El plugin sugiere cada semana. Las actualizaciones programadas esperan a que este Mac esté enchufado.
        [monthly] El plugin sugiere cada mes. Las actualizaciones programadas esperan a que este Mac esté enchufado.
        [manual] El plugin sugiere actualizar solo cuando lo pidas. Las actualizaciones programadas esperan a que este Mac esté enchufado.
       *[other] Las actualizaciones programadas esperan a que este Mac esté enchufado.
    }
settings-plugin-settings-next = Próxima actualización
settings-plugin-settings-next-value =
    { $state ->
        [paused] En pausa. Nada se actualiza por su cuenta hasta que lo reanudes.
        [manual] Solo cuando pulses Iniciar
        [off] Ninguna mientras está desactivado
        [first] En el próximo escaneo
        [approval] Ninguna hasta que lo apruebes
        [continues] Pronto, para terminar la última actualización
       *[due] { $when }
    }
settings-plugin-settings-last = Última actualización
settings-plugin-settings-run =
    { $outcome ->
        [clean] Actualizado { $when }
        [partial] Actualizado en parte { $when }
        [continues] Actualizado en parte { $when }, continúa pronto
        [running] Actualizando ahora
        [stopped] Detenido { $when }
        [bounded] Se quedó sin tiempo { $when }
        [error] No se pudo actualizar { $when }
       *[other] Última ejecución { $when }
    }
settings-plugin-settings-run-progress =
    { $outcome ->
        [running] Actualizando { $read }
        [partial] Actualizado en parte { $when }: { $read }
        [continues] Actualizado en parte { $when }: { $read }, continúa pronto
        [stopped] Detenido { $when } tras { $read }
        [bounded] Se quedó sin tiempo { $when } tras { $read }
        [error] No se pudo actualizar { $when } tras { $read }
       *[other] Última ejecución { $when }: { $read }
    }
settings-plugin-settings-run-summary = { $run }: { $summary }
settings-plugin-settings-never = Aún sin actualizar
settings-plugin-settings-outcome =
    { $outcome ->
        [clean] Actualizado
        [partial] Actualizado en parte
        [continues] Actualizado en parte
        [running] Actualizando ahora
        [stopped] Detenido
        [bounded] Se quedó sin tiempo
        [error] No se pudo actualizar
       *[other] Ejecutado
    }
settings-plugin-settings-brings = Lo que aporta
settings-plugin-settings-slot-state =
    { $state ->
        [approval] Sin usar hasta que lo apruebes
       *[off] Sin usar mientras está desactivado
    }
settings-plugin-settings-slot-none = { $slot ->
        [pay_levels] ninguna estimación
        [pay_observations] ninguna estimación de compensación
        [company_facts] ningún tamaño de empresa
        [company_benefits] ningún beneficio
       *[other] nada de ello
    }
settings-plugin-settings-slot-gap =
    { $read ->
        [0] Hasta que lea una empresa, esa empresa muestra { $none }.
        [one]
            { $left ->
                [one] La otra empresa muestra { $none } hasta que se lea.
                [many] Las otras { $left } de empresas muestran { $none } hasta que se lean.
               *[other] Las otras { $left } muestran { $none } hasta que se lean.
            }
        [many]
            { $left ->
                [one] La otra empresa muestra { $none } hasta que se lea.
                [many] Las otras { $left } de empresas muestran { $none } hasta que se lean.
               *[other] Las otras { $left } muestran { $none } hasta que se lean.
            }
       *[other]
            { $left ->
                [one] La otra empresa muestra { $none } hasta que se lea.
                [many] Las otras { $left } de empresas muestran { $none } hasta que se lean.
               *[other] Las otras { $left } muestran { $none } hasta que se lean.
            }
    }
settings-plugin-settings-left = Por leer
settings-plugin-settings-left-value = Unas { $duration } de actualizaciones, a unos { $pace } por empresa
settings-plugin-settings-reports = El plugin dice
settings-plugin-settings-report = { $value } { $label }
settings-plugin-settings-report-at = A fecha de { $when }
settings-plugin-settings-robots-state =
    { $state ->
        [lapsed] { $hosts } cambió sus reglas desde que lo permitiste; esas páginas se omiten hasta que las revises
        [allowed] Lee pese a las reglas de sus sitios, como permitiste el { $when }
       *[follows] Sigue las reglas de cada sitio
    }
settings-plugin-settings-robots-review = Revisar
settings-plugin-settings-robots-stop = Seguir las reglas
settings-plugin-settings-version = Versión
settings-plugin-settings-history = Actualizaciones recientes
settings-plugin-settings-no-history = Aún no hay actualizaciones.
settings-plugin-settings-published =
    { $rows ->
        [one] { $rows } fila
        [many] { $rows } de filas
       *[other] { $rows } filas
    }
settings-plugin-settings-remove-heading = Eliminar
settings-plugin-settings-remove-note =
    { $what ->
        [rows] Eliminar sus datos borra los { $kinds } que añadió; desactívalo primero.
       *[history] Eliminar sus datos borra lo que se calculó a partir de él; los { $kinds } que registró se quedan como historial.
    } Desinstalarlo quita su código de este Mac y mantiene sus datos, sin leer, hasta que los elimines.
settings-plugin-settings-remove-waiting = Las estimaciones aún leen sus datos. Eliminar datos espera hasta que se actualicen.
settings-plugin-settings-uninstall = Desinstalar
settings-plugin-settings-uninstall-title = ¿Desinstalar este plugin?
settings-plugin-settings-uninstall-lead = Esto lo desactiva y quita su código de este Mac. Los datos que añadió se quedan, sin leer, hasta que los elimines. Instalarlo de nuevo necesita tu aprobación.
settings-plugin-settings-loading = Cargando este plugin…
settings-plugin-settings-load-failed = No se pudo cargar este plugin
settings-plugin-settings-refresh-failed = No se pudo actualizar este plugin. Se muestra el último resultado.
