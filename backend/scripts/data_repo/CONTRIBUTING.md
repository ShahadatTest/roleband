# Contributing data

Corrections and additions are welcome: a company's ladder, a rung's titles, a
pay policy, a benefit an employer states.

1. Read the data card of the dataset you change (`atlas/README.md` or
   `benefits/README.md`). It says what each column means, what evidence a row
   needs, and which files are built by the app rather than edited by hand.
2. Edit the file in place. Keep the columns, their order and the row order, and
   keep a stable id when you correct a record.
3. Say in the pull request where the evidence comes from, by its kind (an
   employer's posting, its careers page, a public filing). Never name a
   commercial pay site, and never paste a URL into a data file.
4. CI checks the change against the app's rules. A failure names the file,
   line and column.

By contributing you agree that your contribution is licensed under this
repository's licence, CC-BY-4.0.

A change that needs the app to change too (a new column, a new table, a rule
the loaders must learn) starts as an issue in
[roleband/roleband](https://github.com/roleband/roleband/issues), so the code and
the data can land together.
