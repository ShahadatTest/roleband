## Casos de prueba del compilador, sin pantalla (docs/copy.md).

spike-role-count = { $count ->
    [one] { $count } { -role(num: "one") }
    [many] { $count } de { -role(num: "other") }
   *[other] { $count } { -role(num: "other") }
}
spike-saved-closed = { $company } cerró un puesto que guardaste
spike-saved-closed-count = { $count ->
    [one] { $company } cerró { $count } { -role(num: "one") } que guardaste
    [many] { $company } cerró { $count } de { -role(num: "other") } que guardaste
   *[other] { $company } cerró { $count } { -role(num: "other") } que guardaste
}
