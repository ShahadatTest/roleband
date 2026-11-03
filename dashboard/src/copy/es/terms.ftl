## Los sustantivos del glosario (docs/copy.md). Un mensaje elige el
## número y lo pasa aquí; la palabra vive una sola vez. `.gender` concuerda los
## adjetivos y participios de la frase (un puesto guardado, una oferta guardada).

-role = { $num ->
    [one] puesto
   *[other] puestos
}
    .gender = masculine

-posting = { $num ->
    [one] oferta
   *[other] ofertas
}
    .gender = feminine

-company = { $num ->
    [one] empresa
   *[other] empresas
}
    .gender = feminine
