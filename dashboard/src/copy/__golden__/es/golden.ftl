-thing = { $num ->
    [one] oferta
   *[other] ofertas
}
    .gender = feminine

plain = Guardado
exact-before-category = { $count ->
    [0] Nada todavía
    [one] { $count } { -thing(num: "one") }
    [many] { $count } de { -thing(num: "other") }
   *[other] { $count } { -thing(num: "other") }
}
by-string = { $stage ->
    [applied] Te postulaste
    [interviewing] Estás entrevistando
   *[other] { -thing.gender ->
        [feminine] La
       *[masculine] Lo
    } estás considerando
}
two-values = { $company }: { $count } abiertas
with-attributes = Buscar
    .placeholder = Buscar en títulos y descripciones
    .aria-label = Buscar puestos
escaped = Las llaves se quedan: {"{"}name{"}"} y «comillas».
