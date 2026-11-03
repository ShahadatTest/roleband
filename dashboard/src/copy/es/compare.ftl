## compare: trasladado tal como estaba (wording=as-is)

## features/compare/CompareScreen.tsx
compare-screen-back = Atrás
compare-screen-clear = Vaciar
compare-screen-compare = Comparar
compare-screen-on-your-or-in-use = En tu { $radar } o en { $saved }, usa el botón { $icon } de una fila para añadirlo aquí.
compare-screen-radar = Radar
compare-screen-saved = Guardados
compare-screen-same = Igual
compare-screen-fields = campos
compare-screen-descriptions = Descripciones
compare-screen-no-description-for-this-role = Este puesto no tiene descripción.
compare-screen-shared-passages-hidden = { $count ->
    [one] { $hidden } pasaje común oculto
    [many] { $hidden } de pasajes comunes ocultos
   *[other] { $hidden } pasajes comunes ocultos
}
compare-screen-picking = { $needed ->
    [pair] { $picked } en comparación · elige dos
   *[another] { $picked } en comparación · elige uno más
}
compare-screen-comparing = { $capacity ->
    [full] Comparando { $count } puestos · completo
   *[open] Comparando { $count } puestos
}
compare-screen-back-aria = Atrás
compare-screen-comparison = Comparación
compare-screen-pick-at-least-two = Elige al menos dos
compare-screen-not-for-me = No es para mí: { $title }
compare-screen-not-for-me-hide-this = No es para mí
compare-screen-remove-from-comparison = Quitar { $title }
compare-screen-remove = Quitar
compare-screen-show-or-hide-matching-fields = { $fields ->
    [open] Ocultar { $count } campos iguales
   *[folded] Mostrar { $count } campos iguales
}
compare-screen-show-or-hide = { $fields ->
    [open] Ocultar
   *[folded] Mostrar
}
compare-screen-passages-legend = { $passages ->
    [shared] Los pasajes en ámbar no están en todas las ofertas.
   *[none] Estas ofertas no comparten ningún pasaje.
}
compare-screen-description-view = { $view ->
    [differences] Mostrar descripciones completas
   *[full] Mostrar solo diferencias
}
compare-screen-loading = Cargando la comparación…
compare-screen-load-failed = No se pudo cargar la comparación

## features/compare/attributes.tsx
compare-attributes-level = Nivel
compare-attributes-est-comp = CT est.
compare-attributes-locations = Ubicaciones
compare-attributes-regions = Regiones
compare-attributes-workplace = Modalidad
compare-attributes-listed-for = Antigüedad
compare-attributes-status = Estado
compare-attributes-reposts = Republicaciones

## features/compare/useCompareController.ts
compare-use-compare-controller-removed-from-compare = { $title } se quitó de la comparación
compare-use-compare-controller-undo = Deshacer
compare-use-compare-controller-could-not-unsave = { $direction ->
    [save] No se pudo guardar { $title }
   *[unsave] No se pudo quitar { $title } de guardados
}
compare-use-compare-controller-couldn-t-restore = No se pudo restaurar { $title }
compare-use-compare-controller-not-for-me = No es para mí · { $title }
compare-use-compare-controller-could-not-hide = No se pudo marcar { $title } como No es para mí

## Añadir un puesto desde la comparación.
compare-screen-add-another = Añadir otro
