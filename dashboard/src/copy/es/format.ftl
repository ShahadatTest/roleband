### eager: el shell importa este archivo, así que cada mensaje viaja en el shell
### (docs/copy.md sección 3). El compilador numera primero sus mensajes.

## Palabras que escriben las funciones de formato (src/format.ts)

format-days-today = hoy
format-days = { $count ->
    [one] { $count } día
    [many] { $count } de días
   *[other] { $count } días
}
format-age-never = nunca
format-age-just-now = ahora mismo
format-age-hours = hace { $count } h
format-age-days = hace { $count } d
format-fresh = Reciente
format-stale = Antiguo
format-freshness = { $word } · { $age }
format-age-minutes = hace { $count } min
