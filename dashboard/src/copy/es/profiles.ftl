## profiles: traducción de en/profiles.ftl

## features/company-profiles/CompanyOffices.tsx
profiles-company-offices-no-office-matches-that-search = Ninguna oficina coincide con esa búsqueda.
profiles-company-offices-hq = Sede central
profiles-company-offices-open = { $open_count } abiertos
profiles-company-offices-location-not-mapped = Ubicación sin asignar
profiles-company-offices-search-cities = Buscar ciudades
profiles-company-offices-search-cities-2 = Buscar ciudades…
profiles-company-offices-country = País
profiles-company-offices-cities = { $count ->
    [one] ciudad
    [many] ciudades
   *[other] ciudades
}
profiles-company-offices-text = { $choice ->
    [yes] { $shownCities } de { $length } ciudades
   *[no] { $length2 } { $value }
}
profiles-company-offices-offices-in = Oficinas en { $label }
profiles-company-offices-show-fewer = { $choice ->
    [yes] Mostrar { $hidden } más en { $label }
   *[no] Mostrar menos
}

## features/company-profiles/CompanyProfilePanel.tsx
profiles-company-profile-panel-says = { $source_label } indica { $value }
profiles-company-profile-panel-conflicting-signal = Señal contradictoria:
profiles-company-profile-panel-no-level-in-this-company = Ningún nivel de la escala de esta empresa está asignado todavía a un nivel estándar.
profiles-company-profile-panel-no-comp-bands-yet = Aún no hay bandas de compensación
profiles-company-profile-panel-band = Nivel
profiles-company-profile-panel-level = Nivel en la empresa
profiles-company-profile-panel-total-comp = CT
profiles-company-profile-panel-composition = Composición
profiles-company-profile-panel-stock = Acciones
profiles-company-profile-panel-profile-unavailable = Perfil no disponible
profiles-company-profile-panel-retry = Reintentar
profiles-company-profile-panel-open = { $open_roles } abiertos
profiles-company-profile-panel-not-on-your-board = No está en tu radar
profiles-company-profile-panel-0-open = 0 abiertos
profiles-company-profile-panel-values-come-from-the-source = Los valores proceden de la fuente indicada al pie de este panel, salvo que una etiqueta diga otra cosa. Cuando las fuentes no coinciden, gana la más fiable y la discrepancia se marca para revisión.
profiles-company-profile-panel-offices-open-roles = Oficinas y puestos abiertos
profiles-company-profile-panel-countries = { $count ->
    [one] { $countryCount } país
    [many] { $countryCount } de países
   *[other] { $countryCount } países
}
profiles-company-profile-panel-where-this-company-is-hiring = Dónde contrata esta empresa ahora mismo, según sus ofertas abiertas.
profiles-company-profile-panel-comp-baseline = Bandas de compensación
profiles-company-profile-panel-base = Base
profiles-company-profile-panel-bonus = Bonus
profiles-company-profile-panel-what-a-role-at-each = Lo que paga un puesto en cada nivel, y qué parte son acciones en lugar de efectivo.
profiles-company-profile-panel-benefits = Beneficios
profiles-company-profile-panel-base-stock-bonus = base { $base_usd } · acciones { $stock_usd } · bonus { $bonus_usd }
profiles-company-profile-panel-see-open-roles = Ver puestos abiertos
profiles-company-profile-panel-see-open-roles-at = { $count ->
    [one] Ver { $open_roles } puesto abierto en { $display_name }
    [many] Ver { $open_roles } de puestos abiertos en { $display_name }
   *[other] Ver { $open_roles } puestos abiertos en { $display_name }
}
profiles-company-profile-panel-loading = Cargando el perfil de esta empresa…

## features/company-profiles/CompanyProfilesView.tsx
profiles-company-profiles-view-to-see = para ver{ $value }
profiles-company-profiles-view-show-all-companies = Mostrar todas las empresas
profiles-company-profiles-view-to-start-over = para empezar de nuevo.
profiles-company-profiles-view-clear-the-search = Borrar la búsqueda
profiles-company-profiles-view-companies-unavailable = Empresas no disponibles
profiles-company-profiles-view-could-not-load-companies = No se pudieron cargar tus empresas. Inténtalo de nuevo.
profiles-company-profiles-view-loading-companies = Cargando tus empresas…
profiles-company-profiles-view-track-one-in-and-its = Sigue una en { $link } y su perfil aparecerá aquí: bandas de compensación, tipo de acciones, plantilla y las fuentes de cada dato.
profiles-company-profiles-view-settings-companies = Ajustes › Empresas
profiles-company-profiles-view-all-profiles-current = todos los perfiles al día
profiles-company-profiles-view-show-all = Mostrar todo
profiles-company-profiles-view-needs-review-only = Solo los que requieren revisión
profiles-company-profiles-view-enrich-fields = Completar campos
profiles-company-profiles-view-no-companies-to-show = { $choice ->
    [v1] Ninguna empresa marcada coincide con “{ $query }”.
    [v2] Ninguna empresa coincide con “{ $query2 }”.
    [v3] No hay nada que revisar ahora mismo.
   *[v4] No hay empresas que mostrar.
}
profiles-company-profiles-view-match = { $count ->
    [one] coincide
    [many] coinciden
   *[other] coinciden
}
profiles-company-profiles-view-all = { $choice ->
    [yes] las { $released } que { $value }
   *[no] todas las { $released2 }
}
profiles-company-profiles-view-companies = Empresas
profiles-company-profiles-view-you-are-not-tracking-any = Aún no sigues ninguna empresa
profiles-company-profiles-view-search-companies = Buscar empresas
profiles-company-profiles-view-find-a-company-or-ticker = Busca una empresa o un símbolo bursátil
profiles-company-profiles-view-that-need-review = { $count ->
    [one] que requiere revisión
    [many] que requieren revisión
   *[other] que requieren revisión
}
profiles-company-profiles-view-need-review = { $count ->
    [one] requiere revisión
    [many] requieren revisión
   *[other] requieren revisión
}
profiles-company-profiles-view-back-to-every-company-profile = Volver a todos los perfiles de empresa

## features/company-profiles/FieldReview.tsx
profiles-field-review-suggested = Sugerido
profiles-field-review-save = Guardar
profiles-field-review-couldn-t-save-it-try = No se pudo guardar. Inténtalo de nuevo.
profiles-field-review-set-to-from = Fijar { $label } en { $field } según { $source_label }
profiles-field-review-or-enter-a-value = O introduce un valor…
profiles-field-review-custom-value-for = Valor personalizado para { $label }
profiles-field-review-or-choose-a-value = O elige un valor…
profiles-field-review-not-a-whole-number = Introduce un número entero, como { $example }.
profiles-field-review-pinned = Se fijó { $label } en { $value }
profiles-field-unpinned = { $label } vuelve a seguir sus fuentes
profiles-field-use-sources = Usar fuentes
profiles-field-use-sources-for = Usar fuentes para { $label }
profiles-field-could-not-use-sources = No se pudo volver a sus fuentes. Inténtalo de nuevo.
profiles-field-could-not-undo = No se pudo deshacer el cambio. Inténtalo de nuevo.

## features/company-profiles/StockPricePanel.tsx
profiles-stock-price-panel-stock-price = Precio de la acción
profiles-stock-price-panel-price-history-unavailable-right-now = El historial de precios no está disponible ahora mismo.
profiles-stock-price-panel-price-range = Rango de precios
profiles-stock-price-panel-stock-price-2 = Precio de la acción de { $slug }, { $range }
profiles-stock-price-panel-daily-closes-over-latest-unknown = { $choice ->
    [yes] { $length } cierres diarios en { $range }, último ${ $toFixed }.
   *[no] { $length } cierres diarios en { $range }, último desconocido.
}
profiles-stock-price-panel-loading = Cargando los precios de la acción…

## features/company-profiles/labels.ts
profiles-labels-current = Al día
profiles-labels-stale = Desactualizado
profiles-labels-conflicting-signals = Señales contradictorias
profiles-labels-incomplete = Incompleto
profiles-labels-senior = Sénior
profiles-labels-staff = Staff
profiles-labels-principal = Principal
profiles-labels-director = Director+
profiles-labels-listed = Cotiza
profiles-labels-ticker = Símbolo bursátil
profiles-labels-headcount = Plantilla
profiles-labels-website = Sitio web
profiles-labels-equity-vehicle = Tipo de acciones
profiles-labels-vesting = Consolidación
profiles-labels-options = Opciones
profiles-labels-none = Ninguno
profiles-labels-cash-election = Opción en efectivo
profiles-labels-sources-disagree = Las fuentes no coinciden
profiles-labels-not-checked-recently = Sin revisar recientemente
profiles-labels-nothing-on-record = Sin datos registrados
profiles-labels-no-value = ninguno
profiles-yes-no = { $answer ->
    [yes] Sí
   *[no] No
}
profiles-equity-policy = { $rule ->
    [none] Esta empresa no concede acciones, así que su compensación no se mueve con el precio de la acción.
   *[election] Cada empleado elige qué parte de su compensación recibe en acciones, así que cuánto se mueve con el precio de la acción depende de cada uno.
}
profiles-roster-dataset = Empresas investigadas
profiles-roster-dataset-hint = Niveles y condiciones de oferta, investigados empresa por empresa.
profiles-roster-no-sector = Sin sector
profiles-roster-other-hint = Seguida desde el mercado más amplio.
profiles-stock-price-panel-needs-key = Los precios de la acción vienen de la integración con Tiingo. { $key } para completar este gráfico.
profiles-stock-price-panel-waiting = Los precios llegan en breve, según lo permitan los límites de Tiingo.
profiles-stock-price-panel-empty-title = Aún no hay precios de la acción
profiles-stock-price-panel-range =
    { $range ->
        [m1] 1 M
        [m3] 3 M
        [m6] 6 M
       *[y1] 1 A
    }
profiles-stock-price-panel-day-move = { $money } ({ $percent })
profiles-stock-price-panel-close = Cierre { $date }
profiles-stock-price-panel-range-move =
    { $move } en { $range ->
        [m1] 1 mes
        [m3] 3 meses
        [m6] 6 meses
       *[y1] 1 año
    }
profiles-stock-price-panel-add-key = Añade tu clave
profiles-labels-one-year-grants = Concesiones a un año
profiles-labels-vested-at-grant = Consolidadas al concederse
profiles-benefits-category =
    { $category ->
        [health_wellbeing] Salud y bienestar
        [insurance_protection] Seguros y protección
        [retirement_financial] Jubilación y programas financieros
        [time_off] Tiempo libre
        [family_care] Familia y cuidados
        [work_flexibility_equipment] Flexibilidad laboral y equipo
        [learning_development] Formación y desarrollo
        [mobility_housing] Movilidad y vivienda
        [meals_workplace] Comidas y servicios en el lugar de trabajo
        [discounts_community] Descuentos y comunidad
        [company_specific] Otros beneficios de la empresa
       *[other] Otros
    }
profiles-benefits-type =
    { $type ->
        [medical_insurance] Seguro médico
        [dental_insurance] Seguro dental
        [vision_insurance] Seguro oftalmológico
        [health_savings_account] Cuenta de ahorro sanitario (HSA)
        [flexible_spending_account] Cuenta de gastos flexibles (FSA)
        [employee_assistance] Programa de asistencia al empleado
        [wellness_allowance] Reembolso de gimnasio y bienestar
        [onsite_gym] Gimnasio en la oficina
        [fitness_classes] Clases de ejercicio en la oficina
        [gym_discount] Descuento en gimnasio
        [onsite_clinic] Clínica en la oficina
        [life_insurance] Seguro de vida
        [disability_insurance] Seguro de incapacidad
        [accident_insurance] Seguro de muerte y desmembramiento accidental (AD&D)
        [travel_insurance] Seguro de viajes de trabajo
        [pet_insurance] Seguro para mascotas
        [retirement_plan] 401k
        [roth_retirement_option] Roth 401k
        [after_tax_retirement_option] Mega Backdoor Roth
        [employee_share_purchase] Plan de compra de acciones para empleados (ESPP)
        [student_loan_support] Plan de pago de préstamos estudiantiles
        [employee_credit] Crédito para empleados
        [vacation] Vacaciones y días personales
        [sick_leave] Baja por enfermedad
        [bereavement_leave] Permiso por duelo
        [sabbatical] Año sabático
        [military_leave] Permiso militar
        [volunteer_leave] Tiempo libre para voluntariado
        [maternity_leave] Permiso de maternidad
        [paternity_leave] Permiso de paternidad
        [fertility_support] Ayuda para fertilidad
        [adoption_support] Ayuda para adopción
        [surrogacy_support] Ayuda para gestación subrogada
        [nursing_facilities] Sala de lactancia en la oficina
        [remote_work] Teletrabajo
        [workstation_equipment] Puesto de trabajo a medida
        [phone_allowance] Reembolso de la factura del teléfono
        [company_phone] Teléfono de empresa
        [learning_support] Formación y desarrollo
        [tuition_support] Reembolso de matrícula
        [immigration_support] Ayuda con la inmigración
        [relocation_support] Bonificación por traslado
        [transport_allowance] Ayuda para transporte
        [company_shuttle] Lanzadera de empresa
        [campus_bikes] Bicicletas en el campus
        [public_transport] Transporte público regional
        [housing_support] Ayuda para vivienda
        [snacks] Tentempiés gratis
        [lunch] Almuerzo gratis
        [drinks] Bebidas gratis
        [breakfast] Desayuno gratis
        [dinner] Cena gratis
        [pet_friendly_workplace] Se admiten mascotas en el trabajo
        [inclusive_facilities] Baños de género neutro
        [onsite_laundry] Lavandería en la oficina
        [onsite_shops] Tienda para empleados en la oficina
        [vehicle_maintenance] Cambio de neumáticos en la oficina
        [vehicle_cleaning] Lavado de coches en la oficina
        [employee_discounts] Descuento para empleados
        [charitable_matching] Duplicación de donaciones
        [referral_bonus] Bonificación por recomendación
        [company_specific_perk] Ventaja exclusiva
        [pandemic_support] Beneficios relacionados con la COVID
        [parental_leave] Permiso parental
        [paid_holidays] Festivos pagados
        [flexible_hours] Horario flexible
        [hybrid_work] Trabajo híbrido
        [home_office_allowance] Ayuda para la oficina en casa
        [mental_health_support] Apoyo a la salud mental
        [childcare_support] Ayuda para el cuidado infantil
        [caregiver_leave] Permiso para cuidadores
        [food_allowance] Ayuda para comida
        [financial_advice] Asesoramiento financiero
       *[other] Otro
    }
profiles-benefits-in-country = En { $country }
profiles-offer-heading = Cómo se construyen las ofertas
profiles-offer-sub = Cómo compone esta empresa la compensación, según lo indica la empresa o lo cuentan sus empleados.
profiles-offer-not-researched = Aún no se ha investigado cómo construye sus ofertas esta empresa.
profiles-offer-searched-not-found = Buscado, no encontrado
profiles-offer-checked = Revisado { $date }
profiles-offer-fact =
    { $fact ->
        [equity_rule] Equity
        [bonus_rule] Bonus anual
        [annual_refresh] Concesiones de renovación
        [sign_on_bridges_vesting] Bonus de incorporación
       *[base_cap_usd] Tope del salario base
    }
profiles-offer-equity-rule = { $rule ->
        [dollar_grant_by_level] Dólares por nivel
        [tc_target_minus_base] Completa la compensación objetivo
        [employee_election] Tú eliges la mezcla
       *[none] Sin equity
    }
profiles-offer-bonus-rule =
    { $rule ->
        [pct_of_base] Porcentaje fijo de base
       *[none] Sin bonus anual
    }
profiles-offer-refresh =
    { $choice ->
        [yes] Anual, según desempeño
       *[no] Sin renovación anual
    }
profiles-offer-sign-on = Compensa la consolidación tardía
profiles-benefits-unreviewed = Recogidos tal como se encontraron y aún sin revisar.
profiles-benefits-unscoped = Dónde se aplica un beneficio no se registra salvo que se muestre un país.
profiles-level-base-sub =
    { $stock ->
        [yes] Base, bonus y acciones estimados en cada nivel de su escalera de ingeniería de software. Solo se muestra un total cuando se conocen todas las partes.
       *[no] Base y bonus estimados en cada nivel de su escalera de ingeniería de software. Las acciones aún no se conocen, así que no hay total.
    }
profiles-level-base-bonus =
    { $choice ->
        [pct] { $amount } (objetivo { $pct })
        [none] Sin bonus anual
       *[unknown] No se sabe
    }
profiles-level-base-below-lower = Bajo el nivel inferior
profiles-level-base-unknown = No se sabe
profiles-level-base-no-stock = Sin acciones
profiles-level-base-none = Aún no hay salarios base para los niveles de ingeniería de software de esta empresa.
profiles-benefits-estimate = { $value }/año, estimado
profiles-benefits-mentions =
    { $count ->
        [one] Una vez en ofertas
        [many] { $count } veces en ofertas
       *[other] { $count } veces en ofertas
    }
profiles-benefits-other-wordings =
    { $open ->
        [yes] Ocultar otras redacciones
       *[no]
            { $count ->
                [one] { $count } redacción más
                [many] { $count } redacciones más
               *[other] { $count } redacciones más
            }
    }
profiles-benefits-also-listed = También aparece: { $names }
profiles-benefits-shared = Dicho de varios beneficios en sus ofertas
profiles-benefits-not-collected = Los beneficios de esta empresa aún no se han recogido. Eso no significa que no ofrezca ninguno.
profiles-not-covered = { $plugin } aún no ha leído esta empresa. Desactívalo en Ajustes › Plugins para ver los datos integrados.
profiles-field-not-covered = Aún sin leer por { $plugin }
