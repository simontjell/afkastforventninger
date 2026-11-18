# afkastforventninger

Tallene fra [Rådet for Afkastforventninger](https://afkastforventninger.dk/afkastforventninger)
som decimaltal på faste adresser (GitHub Pages, ingen server).

```
https://simontjell.github.io/afkastforventninger/2026/h1/globale-aktier-developed-markets  →  0.067
```

Uofficielt. Regnearkene hos rådet er kilden; hvert halvårs `.json` linker til det regneark, tallene kommer fra.

## Adresser

| Sti | Indhold |
|---|---|
| `/{år}/h{1\|2}/{aktivklasse}` | afkast, horisont 1-10 år |
| `/{år}/h{1\|2}/{horisont}/{aktivklasse}` | afkast for horisonten |
| `/{år}/h{1\|2}/{horisont}/{nøgletal}/{aktivklasse}` | et bestemt nøgletal |
| `/{år}/h{1\|2}/inflation/{horisont}` | inflationsforventning |
| `/{år}/h{1\|2}/horisontafkast` | horisontafkast (fra 2021 h2) |
| `/{år}/h{1\|2}.json` | alt for halvåret, inkl. korrelationer |
| `/latest/…` | nyeste offentliggjorte halvår |
| `/current/…` | halvåret, der gælder i dag |
| `/index.json` | halvår, aktivklasser, horisonter, nøgletal |
| `/openapi.json` | OpenAPI 3.1-skema for alle adresser |

- **Horisonter:** `1-5`, `6-10`, `1-10`, `11-plus`
- **Aktivklasser:** `stats-og-realkreditobligationer`, `investment-grade-obligationer`,
  `high-yield-obligationer`, `emerging-markets-statsobligationer`,
  `globale-aktier-developed-markets`, `emerging-markets-aktier`, `private-equity`,
  `infrastruktur`, `ejendomme`, `hedgefonde`. På `11-plus`: `obligationer`, `aktier`,
  `illikvide-aktiver` (fra 2023).
- **Nøgletal:** `afkast`, `standardafvigelse`, `investeringsomkostninger`, og hvor rådet
  oplyser dem: `fees-i-fonde`, `afkast-unhedged`, `loebende-afkast`, `kursaendring`.

Svaret er tallet alene som JSON (`0.067` = 6,7 %), uden endelse på adressen. GitHub Pages
sender dog `Content-Type: text/html` for adresser uden endelse; indholdet kan læses som JSON
alligevel (`fetch(url).then(r => r.json())`).

```bash
curl https://simontjell.github.io/afkastforventninger/2027/h1/1-5/globale-aktier-developed-markets
```

```
=IMPORTDATA("https://simontjell.github.io/afkastforventninger/latest/globale-aktier-developed-markets")
```

## Sådan virker det

1. `python -m afkast.fetch` finder alle regneark på rådets side og gemmer nye i `kilder/`
   (`kilder/manifest.json` kobler halvår til fil og URL; rettede udgaver erstatter den gamle fil).
2. `python -m afkast.build` læser dem og skriver sitet til `_site/`.
3. `.github/workflows/pages.yml` gør begge dele dagligt og ved push og udgiver til Pages.

### Når regnearkene skifter format

`afkast/parse.py` bruger ingen faste celleadresser. Faner findes på navn, kolonner på
overskrift og rækker på aktivklassens navn, så flyttede tabeller, nye faner og nye kolonner
ikke betyder noget. De formatskift, der allerede er sket (standardafvigelser og korrelationer
flyttet til egen fane i 2022, ny aktivklasse på 11+ år i 2023, nye navne på inflationsrækkerne
i 2026, ny fane i 2027) håndteres af den samme kode.

Kan et nyt regneark ikke læses sikkert, fejler workflowet, og det udgivne site bliver stående
uændret. Det sker bl.a. hvis:

- en aktivklasse er ukendt → tilføj navnet til `ASSETS` i `afkast/parse.py` (peg det på den
  eksisterende slug, hvis det er en omdøbning, så adresserne ikke ændrer sig),
- en horisont, afkast eller standardafvigelse mangler,
- et tal ligger uden for et rimeligt interval (fx procent i stedet for decimaltal),
- halvåret ikke kan udledes af filnavn eller linktekst.

Kommer der en ny kolonne, der skal med, tilføjes overskriften til `METRICS`.

## Lokalt

```bash
pip install -r requirements.txt
python -m afkast.fetch
python -m pytest -q
python -m afkast.build
python -m http.server -d _site
```

## Opsætning på GitHub

Under *Settings → Pages* vælges **Source: GitHub Actions**. Derefter udgiver workflowet selv.
GitHub slår planlagte workflows fra efter 60 dage uden aktivitet i repoet; de slås til igen
under *Actions*.

Lavet af [Simple Systemer](https://simplesystemer.dk).
