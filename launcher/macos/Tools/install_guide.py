import argparse
import html
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "Resources/InstallGuide"
LANGUAGES = {"en": "English", "es": "Español", "zh-Hans": "简体中文"}
GUIDE_NAME = "Start here.html"
SECURITY_URL = "x-apple.systempreferences:com.apple.preference.security"


def messages(locale):
    if locale not in LANGUAGES:
        raise ValueError(f"Unsupported installer language: {locale}")
    path = ROOT / "Sources/LauncherCore/Resources" / f"copy.{locale}.json"
    return json.loads(path.read_text()), path


def guide(copy, locale, *, main=False, assets=""):
    if locale not in LANGUAGES:
        raise ValueError("Unsupported guide language")

    def text(key, tag="span", extra=""):
        return f'<{tag} data-copy="{key}" {extra}>{html.escape(copy[key])}</{tag}>'

    def button(key, destination, primary=False):
        return text(key, "button", f'type="button" data-go="{destination}" class="flow-action {"primary" if primary else "secondary"}"')

    def example(file, key, kind):
        return f'''<figure class="{kind}"><div class="capture"><img src="{assets}{file}" data-alt="{key}" alt="{html.escape(copy[key], quote=True)}"><span class="highlight" aria-hidden="true"></span></div>{text("guide-example", "figcaption")}</figure>'''

    prefix = assets if main else ""
    links = " · ".join(f'<a href="{prefix}{code}.html" lang="{code}">{name}</a>' for code, name in LANGUAGES.items())
    keys = {key for key in copy if key.startswith("guide-")} | {
        "installer-language", "installer-title", "installer-privacy",
        "installer-security", "installer-help", "installer-first-open", "back",
    }
    tables = {code: {key: messages(code)[0][key] for key in keys} for code in LANGUAGES}
    tables[locale] = {key: copy[key] for key in keys}
    payload = json.dumps({"initial": locale, "tables": tables}, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    options = "".join(f'<option value="{code}" {"selected" if code == locale else ""}>{name}</option>' for code, name in LANGUAGES.items())
    steps = [("copy", "guide-copy"), ("open", "guide-open"), ("approve", "guide-approve"), ("setup", "guide-setup")]
    navigation = "".join(f'<li><a href="#{step}" data-go="{step}"><span class="number" aria-hidden="true">{index}</span>{text(key)}</a></li>' for index, (step, key) in enumerate(steps, 1))
    return f'''<!doctype html>
<html lang="{locale}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>{html.escape(copy['guide-title'])} · RoleBand</title>
<link rel="icon" type="image/svg+xml" href="{assets}radar.svg"><link rel="stylesheet" href="{assets}guide.css"><script defer src="{assets}guide.js"></script></head>
<body><div class="shell">
<header><a class="brand" href="#copy" data-go="copy"><img src="{assets}radar.svg" alt="">RoleBand</a>
<label class="language"><span aria-hidden="true">🌐</span>{text("installer-language")}<select id="language">{options}</select></label></header>
<noscript><p>{html.escape(copy['guide-static'])}</p><nav>{links}</nav></noscript>
<nav class="steps" data-label="guide-progress" aria-label="{html.escape(copy['guide-progress'], quote=True)}"><ol>{navigation}</ol></nav>
<main>
<section id="copy" data-step="copy" aria-labelledby="copy-title">
{text('guide-title', 'h1', 'id="copy-title" tabindex="-1"')}{text('guide-copy-body', 'p', 'class="lead"')}{text('guide-requirements', 'p', 'class="requirements"')}
<div class="copy-visual" aria-hidden="true"><div><img class="app-icon" src="{assets}radar.svg">{text('guide-app')}</div><span class="arrow">→</span><div><svg class="folder" viewBox="0 0 100 80"><path d="M4 14Q4 6 12 6H40L49 17H88Q96 17 96 25V68Q96 76 88 76H12Q4 76 4 68Z"/></svg><span>Applications</span></div></div>
<div class="actions">{button('guide-copied','open', True)}</div>
</section>
<section id="open" data-step="open" aria-labelledby="open-title">
{text('guide-open-title','h1','id="open-title" tabindex="-1"')}{text('guide-open-body','p','class="lead"')}
{text('guide-warning-body','p')}{example('warning.png','guide-warning-alt','warning')}
<div class="actions">{button('guide-opened','setup')}{button('guide-blocked','approve',True)}</div>
<details>{text('guide-different','summary')}{text('guide-different-body','p')}<a href="https://support.apple.com/en-us/102445">{text('installer-help')}</a></details>
</section>
<section id="approve" data-step="approve" aria-labelledby="approve-title">
{text('installer-first-open','h1','id="approve-title" tabindex="-1"')}{text('guide-approve-body','p','class="lead"')}
<div class="actions"><a class="primary settings" href="{SECURITY_URL}">{text('installer-security')}</a></div>
{text('installer-privacy','p','class="path"')}{text('guide-confirm','p')}
{example('security.png','guide-security-alt','security')}
<details>{text('guide-missing','summary')}{text('guide-missing-body','p')}</details>
<details>{text('guide-settings-label','summary')}{text('guide-settings-fallback','p')}</details>
<div class="actions">{button('guide-allowed','setup',True)}</div>
</section>
<section id="setup" data-step="setup" aria-labelledby="setup-title">
<div class="ready-mark" aria-hidden="true">✓</div>{text('guide-setup-title','h1','id="setup-title" tabindex="-1"')}
{text('guide-setup-body','p','class="lead"')}
<div class="actions">{text('guide-welcome','button','type="button" class="flow-action primary" id="finish-guide"')}</div>
{text('guide-finished','p','id="finished" role="status" hidden')}
</section>
</main><footer><button id="back" class="flow-action secondary" type="button">{text('back')}</button>{text('guide-manual','p')}</footer>
</div><script id="guide-data" type="application/json">{payload}</script></body></html>'''


def write_guide(directory, locale="en", *, for_image=False):
    directory = Path(directory)
    name = ".guide" if for_image else "assets"
    assets = directory / name
    shutil.copytree(ASSETS, assets)
    copy, _ = messages(locale)
    entry = directory / (GUIDE_NAME if for_image else "index.html")
    entry.write_text(guide(copy, locale, main=True, assets=name + "/"))
    for code in LANGUAGES:
        copy, _ = messages(code)
        (assets / f"{code}.html").write_text(guide(copy, code))
    return entry, assets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--language", choices=LANGUAGES, default="en")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    print(write_guide(args.output, args.language)[0])


if __name__ == "__main__":
    main()
