# ALV-kaudet ja Vero API – käyttöohje

**Moduuli:** `account_vat_periods` · **Versio:** 18.0.1.3.1 · **Odoo:** 18 Community

**Ohje päivitetty:** 5.10.2026

Ohje kattaa ALV-kausien perustamisen, raportoinnin, sulkemisen, ALV- ja EU-yhteenvetoilmoitukset, ilmoitusten korjaamisen sekä ALV-laskujen käsittelyn. Se kuvaa nykyistä toteutusta, mukaan lukien alkuperäisen kausimoduulin rajoitukset. Valikkojen nimet voivat näkyä suomeksi tai englanniksi; molemmat nimet on annettu tärkeimmissä kohdissa.

**Nykyinen käyttöönottotilanne:** `commu` on kehitys- ja testiympäristö. Varmenteellisen Vero-testiympäristön työnkulut on testattu erillisessä Community-testikannassa 5.10.2026. Tuotantokäyttöä ei ole hyväksymistestattu. Vero-testipalvelun kausikysely voi palauttaa valmiiksi käsiteltyä malliaineistoa: tästä tulee nyt varoitus jo esikatselussa. ALV-esikatselu tarkistaa kauden verkkokyselyllä, mutta ei lähetä ilmoitusta. Summat voi tarkistaa, vaikka kausikysely epäonnistuisi; vahvistus edellyttää onnistunutta tarkistusta.

## Sisältö

1. [Kokonaisuus ja tavallinen työjärjestys](#1-kokonaisuus-ja-tavallinen-työjärjestys)
2. [Oikeudet, yritys ja valikot](#2-oikeudet-yritys-ja-valikot)
3. [Yrityksen perusasetukset](#3-yrityksen-perusasetukset)
4. [Vero API -yhteys](#4-vero-api--yhteys)
5. [Tilikaudet ja ALV-kausien luominen](#5-tilikaudet-ja-alv-kausien-luominen)
6. [ALV-kausien listan käyttö](#6-alv-kausien-listan-käyttö)
7. [MIS-raportti ja summien tarkistus](#7-mis-raportti-ja-summien-tarkistus)
8. [Kauden sulkeminen](#8-kauden-sulkeminen)
9. [Tavallisen ALV-ilmoituksen lähettäminen](#9-tavallisen-alv-ilmoituksen-lähettäminen)
10. [Nollailmoitus ja palautettava ALV](#10-nollailmoitus-ja-palautettava-alv)
11. [EU-yhteenvetoilmoitus](#11-eu-yhteenvetoilmoitus)
12. [Tilat, vastaukset ja tilakysely](#12-tilat-vastaukset-ja-tilakysely)
13. [ALV-ilmoituksen korjaaminen](#13-alv-ilmoituksen-korjaaminen)
14. [EU-yhteenvetoilmoituksen korjaaminen](#14-eu-yhteenvetoilmoituksen-korjaaminen)
15. [ALV-lasku, maksaminen ja laskun oikaisu](#15-alv-lasku-maksaminen-ja-laskun-oikaisu)
16. [Aikakatkaisu ja epäselvän lähetyksen selvitys](#16-aikakatkaisu-ja-epäselvän-lähetyksen-selvitys)
17. [Tavallisimmat ongelmat](#17-tavallisimmat-ongelmat)
18. [Tarkistuslista ja nykyiset rajaukset](#18-tarkistuslista-ja-nykyiset-rajaukset)
19. [Liite: ilmoituskentät ja tiedon lähteet](#19-liite-ilmoituskentät-ja-tiedon-lähteet)

## 1. Kokonaisuus ja tavallinen työjärjestys

Moduulissa on neljä erillistä vaihetta:

| Vaihe | Mitä se tekee? | Mistä valmistuminen todetaan? |
|---|---|---|
| Kirjanpidon valmistelu | Laskut ja muut tositteet kirjataan oikealle kaudelle oikeilla veroilla. | MIS-raportin luvut täsmäävät tarkistettuun aineistoon. |
| Kauden sulkeminen | Muodostaa sulkukirjauksen, merkitsee kauden suljetuksi ja asettaa verolukituspäivän. | Kausirivillä näkyvät Suljettu, sulkemispäivämäärä ja kirjauslinkki. |
| Vero-ilmoitus | Tallentaa vahvistetun sisällön ja lähettää sen ajastetusti valittuun Vero-ympäristöön. | Lähetyksellä on Vastaanotettu-tila ja vastaanottokuitti. |
| Maksun käsittely | Vastaanotetusta maksettavasta ALV:sta muodostetaan ostolaskuluonnos, joka käsitellään kirjanpidossa. | Laskun kirjaus, maksu ja kohdistus ovat kunnossa. |

**Tavallinen ALV-kierros:** valitse yritys → tarkista kausi ja kirjanpito → avaa raportti → sulje kausi → laske ilmoituksen esikatselu → vahvista lähetys → tarkista kuitti → käsittele ALV-lasku.

EU-yhteenvetoilmoitus tehdään erikseen kuukausittain. Sen tekeminen ei edellytä ALV-kauden sulkemista tai ALV-ilmoituksen lähettämistä.

Suljettu kausi ei vielä tarkoita lähetettyä ilmoitusta. Vastaanotettu ilmoitus ei tarkoita maksettua ALV-laskua. Maksun tila ei puolestaan todista Vero-ilmoituksen vastaanottoa.

## 2. Oikeudet, yritys ja valikot

### Käyttöoikeudet

Vero-yhteyksien asetukset, ilmoitusten esikatselu, lähetys, korjaukset, tilakysely ja lähetyshistorian käsittely edellyttävät oikeutta **Show Full Accounting Features**. Tekninen ryhmä on `account.group_account_user`. **Show Full Accounting Features – Readonly** ei riitä näihin toimintoihin.

Yleisten asetusten muokkaus, tilikausien perustaminen, lukituspäivien muuttaminen ja kirjanpitotositteiden käsittely tarvitsevat lisäksi kyseisten Odoo-toimintojen normaalit oikeudet. Vero-oikeus ei itsessään anna kaikkia ylläpitäjän oikeuksia. Pyydä ylläpitäjää tarkistamaan oikeudet, jos valikko tai toiminto puuttuu.

### Yrityksen valinta

Valitse ennen aloittamista yläpalkista käsiteltävä yritys. Alkuperäisen kausimoduulin sulku- ja raporttitoiminnot käyttävät osin käyttäjän oletusyrityksen asetuksia. **Käsittele tässä versiossa yhtä yritystä kerrallaan ja varmista, että aktiivinen yritys, kausi, sulkupohja, raporttipohja ja Vero-yhteys kuuluvat samaan yritykseen.** Jos aktiivinen yritys ja käyttäjän oletusyritys poikkeavat toisistaan, pyydä ylläpitäjää varmistamaan sulun toiminta ennen käyttöä.

Vero API -ilmoituksen laskenta rajataan ilmoituksen yritykseen. Yhteyden valinnassa väärän yrityksen yhteys estetään. Nämä suojaukset eivät muuta alkuperäisen kausimoduulin kaikkia yritysvalintoja.

### Keskeiset valikot

| Toiminto | Sijainti |
|---|---|
| ALV-kaudet | Kirjanpito → Kauden Päättäminen / Period Closing → ALV-kaudet / VAT Periods |
| Vero-ilmoitusten yhteinen lista | Kirjanpito → Kauden Päättäminen → Vero API -ilmoitukset |
| Vero-yhteydet | Kirjanpito → Asetukset / Configuration → Vero API -yhteydet; Configuration-valikko edellyttää kirjanpidon ylläpitäjän oikeuksia. Aiempi Connector-valikon oikopolku säilyy. |
| Yrityskohtaiset ALV-oletukset | Kirjanpidon asetukset → ALV-kaudet / VAT Periods |
| Sulkupohjat | Kirjanpito → Account Period Closing |
| Tilikaudet | Kirjanpidon tilikausiasetukset; etsi Fiscal Years / Tilikaudet |
| MIS-raporttipohjat | Kirjanpidon asetukset → MIS Reporting → MIS Report Templates |

Odoo Communityssa sovelluksen nimi voi olla **Laskutus / Invoicing**, vaikka sen alla käytetään kirjanpidon toimintoja.

## 3. Yrityksen perusasetukset

Tee asetukset ennen ensimmäisen kauden sulkemista. Avaa kirjanpidon asetusten **ALV-kaudet / VAT Periods** -osio, tarkista yritys ja tallenna asetukset.

| Asetus | Käyttötarkoitus ja tarkistus |
|---|---|
| Oletusarvoinen ALV-kauden sulkemispohja / Default VAT Closing Template | Määrittää suljettavat tilit, sulun päiväkirjan ja vastatilit. Tarkista yrityksen oma tilikartta. |
| Oletusarvoinen ALV-raportin pohja / Default VAT Report Template | Valitsee MIS-raportti-instanssin. Sen varsinainen raporttipohja tuottaa myös API-ilmoituksen luvut. |
| Oletusarvoinen ALV-kauden pituus | Oletus tilikausien automaattista luomista varten. Tilikaudella on lisäksi oma kauden pituuden valinta. |
| Oletusarvoinen toimittaja ALV-maksatukselle | Kumppani, jolle Vero-laskuluonnos tehdään. Tarkista myös kumppanin maksamiseen tarvittavat tiedot. |
| Oletusarvoinen tili ALV-maksatukselle | Vastaanotetun ilmoituksen perusteella luotavan laskun rivitili. Käytä ALV-sulun maksettavan veron vastatiliä. Tilin tyyppi ei saa olla Ostovelat / Payable eikä Myyntisaamiset / Receivable. |
| Oletusarvoinen maksuviite ALV-maksatukselle | Kopioidaan uuteen ALV-laskuun. Tarkista yrityskohtainen viite. |
| Oletusarvoinen kuvaus ALV-maksatukselle | Alkuperäisen moduulin kenttä. Nykyinen Vero API -lasku käyttää kiinteää kuvausta `ALV <kauden päättymispäivä>`, joten tämän kentän muuttaminen ei muuta API-laskun kuvausta. |

Yrityksellä pitää olla suomalainen Y-tunnus tai FI-ALV-tunniste yrityksen **VAT / ALV-tunniste** -kentässä. Moduuli tarkistaa tunnisteen muodon ja Y-tunnuksen tarkistusnumeron. Yrityksen kirjanpitovaluutan on oltava EUR.

### Sulkupohjan tarkistus

Avaa **Account Period Closing** ja yrityksen ALV-sulkupohja. Tarkista yritys, päiväkirja, suljettavat tilit sekä debit- ja credit-vastatilit. ALV-sulku käyttää yleensä valittujen tilien sulkemista (**Selected**).

Moduulin mukana toimitetussa mallissa suljettavat tilit ovat 1763 ja 2930 sekä vastatilit 1764 ja 2939. Nämä ovat toimitetun mallin tiliviittauksia, eivät kaikille yrityksille annettu tilisuositus. Varmista yrityksen oma tilikartta ennen käyttöä. Asetus **Close debit and credit accounts** vaikuttaa myös vastatilien sulkemiseen; toimitetussa ALV-mallissa se on pois päältä.

Maksettavan ALV:n sulku ja ALV-ostolasku pitää kirjata samalle selvittelytilille, jotta velka siirtyy oikein ostoreskontraan. Testiympäristössä tämä on **2939**, jonka tyyppi on **Lyhytaikaiset velat / Current Liabilities** (`liability_current`). Toimittajan ostovelkatili määritetään erikseen Verohallinto-kumppanille. Ostovelka- tai myyntisaamistilin käyttäminen laskun rivitilinä aiheuttaa Odoossa virheellisen maksuehtorivin; moduuli estää tällaisen laskun muodostamisen. Korjaa tiliasetus ja käytä lähetyksen **Muodosta / tarkista lasku** -toimintoa. Vastaanotettua ilmoitusta ei tarvitse lähettää uudelleen.

Normaalissa ALV-kierrossa käytä ALV-kausirivin **Sulje**-painiketta. Sulkupohjan oma **Close Period** tekee sulkukirjauksen erillisenä toimintona eikä yksin hoida kaikkia ALV-kausirivin tilapäivityksiä ja verolukitusta.

## 4. Vero API -yhteys

1. Avaa **Vero API -yhteydet** ja luo yritykselle yhteys.
2. Anna selkeä nimi, josta yritys ja ympäristö tunnistetaan.
3. Valitse yritys ja ympäristö: **Sandbox**, **Test certificate** tai **Production**.
4. Anna **SAT API base URL**: ympäristön SAT-palvelun perusosoite ilman yksittäisen toiminnon nimeä.
5. Anna yhteyshenkilön nimi ja puhelinnumero. Molemmat ovat pakollisia ja enintään 35 merkkiä pitkiä.
6. Avaimet ja varmenne otetaan käyttöön tallennuksen jälkeen **Avaimet ja varmenne** -painikkeella. Palvelinpolkuja ei normaalisti tarvitse syöttää.
7. Valitse EU-yhteenvetoa varten tavara-, palvelu- ja tarvittaessa kolmikantamyynnin veroruudukot.
8. Tallenna yhteys.

### Avaimet ja varmenne Odoon kautta

Toiminto edellyttää **Show Full Accounting Features** -oikeutta, pääsyä kyseiseen yritykseen ja HTTPS-yhteyttä Odooseen. Moduulin asennus ja ensimmäinen päivitys ovat ylläpidon tehtäviä. Tämän jälkeen avainten normaali tallennus ja tilatun varmenteen nouto onnistuvat selaimessa ilman SSH-yhteyttä tai Odoon restartia.

Palvelimen tiedostopolkujen käsin muuttaminen on rajattu tekniselle ylläpitäjälle. Näin kirjanpitokäyttäjä ei voi osoittaa omaa yhteyttään toisen yrityksen avaintiedostoihin. Ohjelmistoavaimen syöttö, varmenteen nouto ja käyttöönotto onnistuvat normaalilla yllä mainitulla kirjanpito-oikeudella.

**Ohjelmistoavain:** avaa tallennettu Vero API -yhteys → **Avaimet ja varmenne**. Liitä Verohallinnolta saatu ohjelmiston API-avain kenttään **Uusi API-avain** ja paina **Tallenna API-avain**. Sandboxissa syötetään sen oma subscription key. Avainkenttä tyhjennetään lähetyksen yhteydessä; tallennettua avainta ei näytetä uudelleen. Odoo muodostaa suojatun tiedoston ja tallentaa sen polun automaattisesti. Ohjelmistoavainta ei luoda tyhjästä: sen hankkiminen ja ohjelmistorekisteröinti hoidetaan edelleen Verohallinnossa.

**Testi- tai tuotantovarmenteen nouto:**

1. Tilaa oikean ympäristön Vero API -varmenne Verohallinnon varmennepalvelussa. Tilaus ja tarvittavat rajapintaoikeudet eivät synny Odoossa.
2. Tarkista Odoon yrityksen ALV-tunniste/Y-tunnus. Tässä toiminnossa varmenteen haltijan pitää olla sama yritys. Testivarmenteeseen käytetään tilauksen testitunnistetta.
3. Avaa oikean yrityksen ja ympäristön **Avaimet ja varmenne**. Syötä Verohallinnon turvasähköpostista siirtotunnus ja kertakäyttösalasana.
4. Paina **Aloita tilatun varmenteen nouto** kerran. Odoo luo yksityisen avaimen palvelimella ja lähettää varmennepyynnön. Siirtotunnusta ja kertakäyttösalasanaa ei tallenneta Odoon tietokantaan tai levylle.
5. Kun tila on `waiting`, odota vähintään 30 sekuntia. Paina **Nouda ja tarkista varmenne**. Odoo tarkistaa vastauksen allekirjoituksen, varmenneketjun, ympäristön, voimassaolon, yritystunnisteen ja avainparin vastaavuuden.
6. Kun tila on `ready`, tarkista tiedot ja paina **Ota noudettu varmenne käyttöön**. Mahdollinen aiempi varmenne pysyy käytössä tähän saakka. Käyttöönotto päivittää varmenteen ja yksityisen avaimen polut yhdessä.
7. Paina **Testaa API-yhteys**. Se tekee kuluvan vuoden ALV-kausikyselyn eikä lähetä veroilmoitusta. Onnistunut kysely varmistaa yhteyden kyseiseen palveluun; ilmoitusten sisältö ja muut rajapintaoikeudet testataan erikseen.

Jos selain tai yhteys katkeaa, avaa sama yhteys ja paina **Päivitä tila**. Tila `uncertain` tarkoittaa, että kertakäyttötunnusten lähettämisen tulos ei ole varmistunut. Moduuli säilyttää avaimen ja estää uuden pyynnön. Jos vastaanotettu allekirjoitettu vastaus on tallessa, tila palautetaan siitä automaattisesti; muussa tapauksessa selvitä pyyntö Verohallinnolta. Älä tilaa tai lähetä uutta varmennetta vain aikakatkaisun vuoksi. Tila `rejected` tarkoittaa varmennettua hylkäystä: korjaa tunnukset tai tilaus ennen uutta yritystä. Keskeneräinen ilmoitus estää käytössä olevan avaimen tai varmenteen vaihtamisen.

Varmenteen viimeinen voimassaolopäivä näkyy näkymässä. **RenewCertificate-rajapintaa käyttävä automaattinen uusiminen ei sisälly tähän versioon.** Uuden erikseen tilatun varmenteen nouto ja hallittu vaihto onnistuvat samoilla painikkeilla. Jo käyttöönotettua toimivaa varmennetta ei tarvitse noutaa uudelleen.

### Salaisuuksien säilytys ja varmuuskopiointi

Yksityinen avain ja ohjelmistoavain säilyvät Odoon `data_dir`-hakemiston alla olevassa erillisessä `vero_credentials`-hakemistossa. Tiedostot on eroteltu tietokannan, yrityksen, yhteyden ja ympäristön mukaan. Hakemistojen oikeudet ovat 0700 ja tiedostojen 0600. Odoon tietokantaan tallentuvat tiedostopolut; avaimet eivät ole liitteitä, raporttikenttiä tai tavallisia wizard-tietueita. Odoo-yhteyden kopiointi ei kopioi sen avainpolkuja.

Ylläpidon pitää varmuuskopioida avainhakemisto suojatusti erikseen: tavallinen tietokanta-/filestore-varmistus ei välttämättä sisällä sitä. Avainta ei voi palauttaa Verohallinnolta. Palvelimen pääkäyttäjä ja Odoo-palveluprosessi voivat käyttää avaimia; tiedosto-oikeudet eivät suojaa kaapattua palvelinta vastaan. HTTPS, palvelimen päivitykset ja vain luotetut Odoo-lisämoduulit ovat osa kokonaisuutta. Avaintoimintoihin oikeutettu käyttäjä voi vaihtaa yhteyden tunnukset, joten tätä oikeutta ei pidä antaa tarpeettomasti.

### Ympäristöjen ero

| Ympäristö | Tunnistautuminen tässä moduulissa | Käyttötarkoitus |
|---|---|---|
| Sandbox | Sandboxin tilausavain tiedostossa; ei asiakasvarmennetta | Rajapinnan mallivastauksiin perustuvat kokeet keinotekoisella aineistolla |
| Test certificate | Ohjelmistoavain, testivarmenne ja yksityinen avain | Varmenteellisen testiympäristön kokeet |
| Production | Tuotannon ohjelmistoavain, varmenne ja yksityinen avain | Tuotannon ilmoitukset, kun käyttöönotto on hyväksytty |

Sandboxin perusosoite on `https://api-sandbox.vero.fi/Return/SAT`. Muissa ympäristöissä ylläpitäjä antaa Vero-palvelusta tarkistetun perusosoitteen. Moduuli hyväksyy ympäristön mukaisen virallisen HTTPS-palvelimen.

**Software Key File** sisältää avaintiedoston polun. Sandboxissa kyseessä on tilausavain; varmenteellisissa ympäristöissä ohjelmistoavain. **Certificate File** ja **Private Key File** osoittavat PEM-tiedostoihin. **Software ID** on erillinen valinnainen tunniste. **Authorization Token File** on tarvittaessa käytettävän puolesta-asioinnin tokenin polku; automaattinen uusiminen ei kuulu toteutukseen.

Avainten sisältöä ei syötetä ilmoituksen esikatseluun. Uusi **Avaimet ja varmenne** -toiminto huolehtii tiedostoista ja oikeuksista automaattisesti. Lisäasetusten tiedostopolut säilyvät aiempien asennusten ja erikseen ylläpidettyjen salaisuuksien käyttöä varten.

Yrityksellä voi olla yksi yhteys kutakin ympäristöä kohti. Päivitä avaimet olemassa olevaan yhteyteen. Yritystä ja ympäristöä ei voi vaihtaa, kun yhteydelle on luotu ilmoitus. Perusosoitteen vaihtaminen estyy, jos yhteydellä on jonossa oleva, lähettävä, epäselvä tai vastaanotettu lähetys.

### EU-veroruudukot

Valitse **verottomien myyntiperusteiden** tunnisteet, ei veron määrän tunnisteita. Tavara- ja palvelutunnisteet vaaditaan yhteenvetolaskentaan, vaikka kyseisen kuukauden myyntiä olisi vain toisessa ryhmässä. Kolmikantamyynnin tunnisteet valitaan, jos sitä raportoidaan. Sama tunniste ei voi kuulua kahteen myyntilajiin. Ota mukaan yrityksen käytössä olevat lasku- ja hyvityspuolen tunnisteet.

`commu`-testiyhteydessä tavaroille on käytetty `±fi_311`- ja palveluille `±fi_312`-tunnisteita. Tarkista valinnat aina yrityksen todellisilta veroilta ja kirjauksilta.

## 5. Tilikaudet ja ALV-kausien luominen

ALV-kaudet syntyvät tilikauden luomisen yhteydessä. ALV-kausien listassa ei ole tavallista uuden rivin luontia tai rivien muokkausta.

1. Avaa **Tilikaudet / Fiscal Years**.
2. Valitse oikea yritys ja perusta tilikausi.
3. Tarkista alku- ja loppupäivä.
4. Valitse **ALV-kauden pituus / VAT Period Duration**: yksi kuukausi, kolme kuukautta tai vuosi.
5. Tallenna tilikausi.
6. Avaa ALV-kaudet ja tarkista syntyneiden kausien alku- ja loppupäivät sekä yritys.

Nykyinen generaattori tekee tilikauden alusta 12 kuukauden kokonaisuuden: 12 kuukausikautta, neljä kolmen kuukauden kautta tai yhden vuosikauden. Se ei sovita kausimäärää automaattisesti poikkeavan pituisen tilikauden loppupäivään. Lyhennetty tai pidennetty tilikausi sekä kalenterivuodesta poikkeavat ilmoitusjaksot tarvitsevat erillisen tarkistuksen ennen käyttöä.

**Tilikauden kauden pituuden muuttaminen jälkikäteen ei muodosta olemassa olevia ALV-kausia uudelleen.** Älä luo samaa tilikautta tai kausistoa uudelleen puuttuvan näkymän korjaamiseksi. Tarkista ensin listan suodatin. Tilikausien automaattisen jatkoluonnin toiminta on myös tarkistettava erikseen tässä versiossa; varmennettu työjärjestys on tarkistaa jokaisen uuden tilikauden kaudet ennen käyttöä.

### Jos kaudet eivät näy

Listan oletussuodatin on **Nykyinen tilikausi / This Fiscal Year**. Poista se hakupalkista, jos etsimäsi kausi ei näy. Suodatin perustuu moduulin tilikausitietoon, eikä puuttuva rivi välttämättä tarkoita, ettei kautta olisi luotu. Tämä tuli vastaan myös `commu`-ympäristön vuoden 2026 kausissa.

## 6. ALV-kausien listan käyttö

| Painike tai sarake | Merkitys |
|---|---|
| ALV-kausi / VAT Period | Käsiteltävä päivämääräväli. Tarkista tämä ennen jokaista toimenpidettä. |
| Sulje / Close | Muodostaa kauden sulkukirjauksen ja verolukituksen. Harmaa painike voi tarkoittaa, että aiempi kausi pitää sulkea ensin. |
| Suljettu / Closed | Kertoo suljetusta kaudesta. Painike on myös toiminto, joka poistaa kausirivin sulkemismerkinnän; älä paina sitä vain tilan tarkistamiseksi. |
| Avaa Raportti / Open Report | Avaa yrityksen MIS-raportin kauden alun perusteella. Ei lähetä mitään. |
| ALV-ilmoitus ja EU-yhteenveto | Erilliset tilat. Teksti kertoo SANDBOX-, TESTI- tai TUOTANTO-ympäristön sekä ilmoituksen kuukauden. |
| Tee ALV-ilmoitus / Tee EU-ilmoitus | Aloittaa ilmoituksen valmistelun. Jos valitulla yhteydellä ja kuukaudella on jo lähetys, avautuu sen tila. |
| ALV/EU: lähetyksen tila | Jonossa tai lähetyksessä oleva ilmoitus. Uutta lähetystä ei tarjota. |
| Näytä ALV/EU-ilmoitus | Vastaanotettu ilmoitus, lähetysaika, kuitti, lähetetty sisältö ja vastaus. Korjaus aloitetaan erillisellä **Tee korjaus** -painikkeella. |
| ALV/EU: näytä virhe | Viimeisimmän yrityksen virhe ja lähetyshistoria. **Valmistele ilmoitus** avaa uuden esikatselun. |
| ALV/EU: selvitä tila | Epäselvä vastaanotto. Uusi lähetys on estetty, kunnes tulos on selvitetty. |
| ALV/EU: ilmoitukset | Kaudella on useita eri tiloja tai selvitetty epäonnistunut lähetys. Avaa ilmoituskohtaiset tiedot. |
| Kalenteri-plus-kuvake | Valitse EU-ilmoituksen toinen kuukausi tai yhteys. Tärkeä neljännesvuoden ALV-kaudella. |
| Vaihtonuolikuvake | Valitse ALV-ilmoituksen toinen yhteys / ympäristö. Testi-ilmoitus ei ole tuotantoilmoitus. |
| Historiakuvake | Kauden kaikki ALV- ja EU-ilmoitukset. |
| Kirjaus / Journal Entry | Linkki sulkukirjaukseen. |
| Sulkemispäivämäärä | Päivä, jolloin kausi suljettiin. Sulkukirjauksen päivä on kauden loppupäivä. |
| Maksun tyyppi | Alkuperäisen moduulin sulkukirjauksesta päättelemä maksettavaa/saatavaa-merkintä. Tarkista euromäärä raportilta ja laskulta. |
| Ostolasku / Vendor Bill | Linkki kauteen tällä hetkellä liitettyyn ALV-laskuun tai oikaisun hyvitykseen. |
| Maksun tila | Liitetyn kirjanpitotositteen tila, kuten Luonnos, Maksamatta, Maksussa, Osittain maksettu tai Maksettu. |

Kausilista ja ilmoituslista päivittyvät noin 10 sekunnin välein, kun ne ovat näkyvissä eikä dialogia tai rivivalintaa ole auki. Avoin esikatselu säilyy muuttumattomana. Tiladialogissa käytä **Päivitä lähetyksen tila** -painiketta.

Vanha lähetysmerkintä ja VAT Reported OK -sarake on poistettu tästä näkymästä. Vihreä **Vastaanotettu Verohallinnossa** tarkoittaa tallennettua vastaanottokuittausta, ei lopullista verotuspäätöstä. EU-tilassa mainitut kuukaudet ovat juuri ne, joille ilmoitus on luotu; tila ei väitä kaikkia kauden kuukausia ilmoitetuiksi.

## 7. MIS-raportti ja summien tarkistus

### Raportin avaaminen

1. Paina kausiriviltä **Avaa Raportti**.
2. Tarkista raportin yritys ja näkyvä ajanjakso.
3. Tarkista, että käsittelet kirjattuja tapahtumia. API-ilmoitus käyttää vain kirjattuja tositteita.
4. Vertaa myynnin veroja, ostojen veroja ja vähennettävää veroa kirjanpidon aineistoon.
5. Selvitä puuttuvat tai virheelliset luvut ennen sulkemista ja lähettämistä.

Raportilla on moduulin lisäämä **Filter by VAT Period** -kausivalinta. Valinta vaihtaa raportin ankkuripäivän valitun päivämäärävälin alkuun. Se ei yksin takaa, että raporttipohjan suhteellinen sarake kattaa juuri saman loppupäivän. Tarkista aina raportin näkyvät päivämäärät, erityisesti neljännesvuosi- ja vuosiraporteilla.

MIS-raportin asetuksessa **Show Date Range Filter / Näytä Date Range -suodatin** voidaan ottaa kausivalinta käyttöön. Se ja tavallinen ankkuripäivän valinta (**Show Pivot Date**) vaihtuvat toistensa vaihtoehdoiksi.

### Mistä Vero-ilmoituksen luvut tulevat?

API-esikatselu laskee saman varsinaisen MIS-raporttipohjan tiedot erikseen ilmoituksen tarkalla alku- ja loppupäivällä. Se käyttää vain ilmoituksen yrityksen kirjattuja tapahtumia. Käyttäjän väliaikaista analyyttistä suodatusta ei oteta veroilmoituksen rajaukseksi. ALV-luvut eivät tule sulkukirjauksen loppusumman erittelystä.

Lähetettävän ilmoituksen viimeinen tarkistus tehdään **Vero API -esikatselussa**. Jos tavallinen MIS-näkymä ja API-esikatselu eroavat, tarkista ensin yritys, päivämääräväli, tositteiden tila ja raportin suodattimet.

### Veroruudukkojen vastaavuus

Kirjauksen veroruudukon ja MIS-kaavan pitää käyttää samaa tunnistetta. `commu`-ympäristössä korjattiin 17.9.2026 seuraavat kaavat:

| MIS-rivi | Käytettävät tunnisteet |
|---|---|
| `vero_25_5` | `+fi_301` ja `-fi_301` |
| `vero_13_5` | `+fi_302` ja `-fi_302` |
| `vero_10` | `+fi_303` ja `-fi_303` |

Tunnisteiden korjaus ei muuta veroprosenttia. Veron prosentti ja voimassa oleva käyttö on tarkistettava erikseen veron asetuksista. Testikopiossa 1 000 euron myyntilasku ja 200 euron hyvitys 25,5 %:n verolla tuottivat korjauksen jälkeen kirjanpitoon ja MIS-riville 204 euroa. Alempien kantojen korjaukset tarkistettiin asetustasolla.

## 8. Kauden sulkeminen

Ennen sulkemista kirjaa kauden laskut, hyvitykset ja muut ilmoitukseen kuuluvat tositteet. Tarkista niiden kirjanpitopäivämäärät. Luonnokset eivät tule API-ilmoitukseen.

1. Tarkista yritys ja kausi.
2. Tarkista MIS-raportti.
3. Sulje aiemmat kaudet aikajärjestyksessä.
4. Paina **Sulje / Close** ja hyväksy sulkemisen vahvistus.
5. Avaa syntynyt **Kirjaus / Journal Entry** ja tarkista sulkukirjaus.
6. Varmista, että kausi näkyy suljettuna ja verolukituspäivä on oikein.

Sulku laskee sulkupohjan tilien kirjattujen tapahtumien kausisaldot, muodostaa vastakirjaukset ja nettomäärän vastatilille sekä kirjaa tositteen kauden loppupäivälle. Tämän jälkeen moduuli merkitsee kauden suljetuksi ja asettaa verolukituspäiväksi kauden loppupäivän.

Sulku ei tee Vero-lähetystä eikä ALV-maksua. Ilmoitus voidaan esikatsella ennen sulkua, mutta ALV-lähetyksen vahvistaminen edellyttää suljettua kautta.

### Mitä Suljettu-painike tekee?

**Suljettu / Closed** poistaa kausirivin suljettu-merkinnän, sulkemispäivämäärän ja linkin sulkukirjaukseen. Se **ei peru alkuperäistä sulkukirjausta eikä palauta verolukituspäivää**. Alkuperäinen kirjaus jää kirjanpitoon, vaikka linkki poistuu kausiriviltä.

Tallenna sulkukirjauksen numero ennen mahdollista avaamista. Käytä lukitun kauden korjaamiseen luvun 13 työjärjestystä. Pelkkä avaaminen ja uusi sulkeminen eivät muodosta automaattista alkuperäisen sulun peruutusta.

## 9. Tavallisen ALV-ilmoituksen lähettäminen

### Esikatselu

1. Avaa oikean kauden **Tee ALV-ilmoitus**. Aiemmin käsitellyllä kaudella avaa tilan mukainen painike. Se näyttää olemassa olevan lähetyksen; valitse tarvittaessa **Valmistele ilmoitus** tai vastaanotetun ilmoituksen **Tee korjaus**.
2. Valitse yrityksen **Vero-yhteys**. Yksi aktiivinen yhteys valitaan oletuksena; useasta yhteydestä valinta tehdään itse.
3. Jätä **Ei toimintaa** pois, jos kaudella on ilmoitettavia tapahtumia.
4. Ensimmäisessä tavallisessa ilmoituksessa jätä **Korvaa aiemmin muualla annettu ALV-ilmoitus** pois. Korjauksen syytä ei silloin tarvita.
5. Paina **Laske / päivitä esikatselu**.
6. Tarkista valittu ympäristö, yrityksen tunniste ja kauden päättymispäivä.
7. Tarkista **Lähetettävät tiedot** ja **Muutokset edelliseen vastaanotettuun ilmoitukseen**.

Esikatselu näyttää JSON-muotoisen sisällön. Tämä on nykyisen version varsinainen lähetettävien tietojen näkymä. Kenttien merkitykset on selitetty luvussa 19. Ensimmäisessä ilmoituksessa vertailu tehdään tyhjään lähtötilanteeseen, joten siinä näkyy lisäyksiä; se ei tarkoita, että ilmoitus olisi korjaus.

Esikatselun laskeminen luo tarvittaessa ilmoituksen tietueen, mutta ei lähetä sitä Verohallintoon. ALV-esikatselu yrittää samalla tarkistaa Verohallinnon kauden. Puuttuva yhteys tai kaudella jo oleva ilmoitus näkyy varoituksena ja estää vahvistamisen. Summat jäävät silti tarkistettaviksi. Korvausvalinnan tai syyn muuttamisen jälkeen laske esikatselu uudelleen.

### Vahvistaminen ja lähetyksen seuranta

1. Varmista, että kausi on suljettu ja esikatselu on tarkistettu.
2. Paina **Vahvista ja lähetä**.
3. Tarkista vahvistusikkunassa, että lähetys tehdään tarkoittamaasi ympäristöön, ja hyväksy.
4. Lähetys tallentuu tilaan **Jonossa**. Dialogin voi sulkea.
5. Näet kuittauksen **Ilmoitus lisätty lähetysjonoon**. Voit sulkea dialogin: kausilista päivittyy automaattisesti. Avoimessa dialogissa käytä **Päivitä lähetyksen tila**.
6. Avaa lähetys ja varmista **Vastaanotettu**, vastaanottotunniste ja vastaanottoaika.
7. Tarkista myös mahdollinen laskuvaiheen viesti.

Ajastettu työ on määritelty kerran minuutissa ajettavaksi. Jonotus ei siksi välttämättä muutu vastaanotoksi saman tien. Lähetys tehdään vahvistaneen käyttäjän oikeuksilla; käyttäjän tai yhteyden poistaminen käytöstä ennen käsittelyä voi estää sen.

Ennen ALV:n lähettämistä moduuli kysyy Verolta kauden tiedot. Valitun jakson on vastattava Veron palauttamaa jaksoa. Moduuli tarkistaa myös, onko kyse ensimmäisestä vai korvaavasta ilmoituksesta, ja tallentaa kausikyselystä saatavan eräpäivän.

Jos kirjanpidon sisältö tai korjauksen valinnat ovat muuttuneet esikatselun jälkeen, vahvistaminen pysähtyy. Paina uudelleen **Laske / päivitä esikatselu**, tarkista muutokset ja vahvista vasta sitten. Vahvistettua lähetyssisältöä ei myöhemmin päivitetä kirjanpidon muutosten mukana.

## 10. Nollailmoitus ja palautettava ALV

### Ei toimintaa -ilmoitus

1. Tarkista, ettei kaudella ole ilmoitettavia lukuja.
2. Sulje kausi normaalin työjärjestyksen mukaan.
3. Avaa ALV-esikatselu ja valitse **Ei toimintaa**.
4. Laske esikatselu uudelleen ja tarkista `NoActivity: true`.
5. Vahvista ja seuraa vastaanottoa.

Moduuli estää **Ei toimintaa** -valinnan, jos yksikin ilmoitukseen kartoitettu MIS-luku on nollasta poikkeava. Pelkkä maksettavan nettomäärän nolla ei tarkoita toimettomuutta: myynnin ja vähennysten summat voivat olla yhtä suuret. Tällöin käytetään normaalia ilmoitusta erittelyineen.

### Palautettava ALV

Palautettava kausi käsitellään normaalina ALV-ilmoituksena. Tarkista vähennettävä vero ja muut ilmoituskentät. Kun ilmoituksen laskettu nettomäärä on nolla tai negatiivinen, moduuli ei luo uutta maksettavaa ostolaskua.

Palautussaatavan kirjanpito tarkistetaan sulkukirjaukselta ja palautuksen toteutuminen käsitellään kirjanpidon normaaleilla pankki- ja täsmäytystoiminnoilla. Moduuli ei tee erillistä palautushakemusta eikä kirjaa pankkiin saapunutta palautusta automaattisesti.

## 11. EU-yhteenvetoilmoitus

1. Tarkista, että EU-myynnit ja hyvitykset on kirjattu oikeille päiville ja niillä on oikeat myyntiperusteen veroruudukot.
2. Tarkista ostajayritysten ALV-tunnisteet. Laskenta käyttää kaupallisen pääkumppanin tunnistetta, joten pelkän alayhteystiedon tunniste ei aina riitä.
3. Paina ALV-kausirivillä **Tee EU-ilmoitus**. Jos kaudella on aiempia EU-ilmoituksia, valitse uusi kuukausi kalenteri-plus-kuvakkeesta.
4. Valitse Vero-yhteys.
5. Valitse **Yhteenvetoilmoituksen kuukausi**. Päivämäärästä käytetään koko kyseistä kalenterikuukautta, ja valitun päivän pitää kuulua kausirivin jaksoon.
6. Paina **Laske / päivitä esikatselu**.
7. Tarkista kuukausi, vuosi, ostajien maat ja ALV-tunnisteet sekä tavara-, palvelu- ja kolmikantamyynnit.
8. Paina **Vahvista ja lähetä** ja tarkista vastaanottokuitti historiasta.

Ilmoitus muodostetaan kirjatuista pääkirjariveistä, joilla on yhteyden asetuksissa valitut verottomien myyntiperusteiden tunnisteet. Hyvitykset vähentävät myyntiä kirjauksen etumerkin perusteella. Summat ryhmitellään ostajan maan ja ALV-tunnisteen mukaan.

Kolmen kuukauden ALV-kaudelta tehdään tarvittaessa kolme erillistä EU-kuukausi-ilmoitusta. Vuosikaudelta valitaan kukin tarvittava kuukausi erikseen. Avaa dialogi uudelleen toiselle kuukaudelle, jotta et jatka aiemmin luodun kuukauden ilmoituksen käsittelyä.

EU-ilmoitus ei edellytä ALV-kauden sulkemista. Se ei luo ALV-maksulaskua. Tyhjää ostajalistaa ei lähetetä, ja ohjelma ilmoittaa, jos ilmoitettavaa tai muuttuneita ostajia ei ole. Puuttuva tai virheellinen ostajan ALV-tunniste estää laskennan; virheilmoitus auttaa löytämään tositteen. Tunnisteen muodon tarkistus ei ole VIES-palvelusta tehty voimassaolon tarkistus.

**Vihreä EU-kuvake koskee vain Odoossa luotuja EU-ilmoituksia.** Se ei tarkista, että kaikki ALV-kauden kalenterikuukaudet on käsitelty. Tarkista kuukaudet ilmoituslistasta.

## 12. Tilat, vastaukset ja tilakysely

### Ilmoituksen tila

Ilmoituksen yhteinen tila perustuu sen uusimpaan lähetysyritykseen. Jos aiempi versio vastaanotettiin mutta uusin korjaus epäonnistui, listalla voi näkyä virhe, vaikka historiassa on vanha vastaanotettu versio.

| Tila | Merkitys ja seuraava toimenpide |
|---|---|
| Ei lähetetty | Esikatselu tai ilmoitustietue on olemassa, mutta lähetysyritystä ei ole. |
| Jonossa | Vahvistettu sisältö odottaa ajastettua käsittelyä. Päivitä näkymä myöhemmin. |
| Lähetys kesken / tarkistettava | Käsittely on alkanut. Älä tee rinnakkaista lähetystä. |
| Vastaanotettu | Lähetyksellä on tallennettu kuittitunniste ja vastaanottoaika, tai vastaanotto on varmistettu erillisellä selvityksellä. Tarkista ympäristö ja laskuvaihe. |
| Virhe | Esitarkistus tai lähetys epäonnistui. Lue virhe ja vastaus, korjaa syy ja tee tarvittaessa uusi tarkistettu lähetys. |
| Tulos epäselvä | Vastaanottoa ei voida päätellä varmasti. Selvitä tulos ennen uutta lähetystä. |
| Selvitetty: ei vastaanotettu | Verohallinnosta varmennettu vastaanottamattomuus on kirjattu. Uusi lähetys on mahdollinen esikatselun kautta. |

### Vastauksen ja lähetyssisällön avaaminen

1. Avaa kausirivin tilan mukainen painike tai yhteinen **Vero API -ilmoitukset** -lista.
2. Valitse oikea ilmoitus, yritys, kausi ja ympäristö.
3. Avaa **Tila / Tila ja vastaukset**.
4. Siirry **Lähetyshistoria ja vastaukset** -välilehdelle ja avaa lähetysyritys.
5. Tarkista lähettäjä, käsittelyajat, HTTP-tila, vastaanottotunniste ja mahdolliset virhe- tai laskuviestit.
6. Katso **Lähetys**, **Vastaus** ja **Kauden kokonaiskuva** -välilehdet.

Lähetys näyttää kyseisellä kerralla lähetetyn sisällön. Kauden kokonaiskuva säilyttää laskennan kokonaisuuden; EU-korjauksessa se voi olla laajempi kuin lähetettyjen muuttuneiden ostajien lista. Lähetyshistoriaa ei muokata tai poisteta normaalikäytössä. Uusi korjaus muodostaa uuden version.

### ALV:n tilakysely

Paina ALV-dialogissa **Hae tiedot Verohallinnosta**. Tarkastele **Tilakysely**-välilehteä sekä ilmoituksen viimeisen kyselyn aikaa ja etätilaa.

Kysely hakee Veron palauttaman ilmoitustiedon; se ei lähetä uutta ilmoitusta. **Se ei muuta epäselvää lähetysyritystä automaattisesti vastaanotetuksi**, koska palvelussa näkyvä ilmoitus voi olla aikaisempi versio. Myöskään samansuuruinen vero ei yksin todista uuden version vastaanottoa.

EU-yhteenvetoilmoitukselle tässä toteutuksessa ei ole vastaavaa erillistä tilakyselyä. Käytä tallennettua vastausta ja tarvittaessa erillistä vastaanoton selvitystä.

## 13. ALV-ilmoituksen korjaaminen

ALV-korjaus lähettää kauden **kaikki korjatut ilmoitustiedot**. Syötettävä tai lähetettävä määrä ei ole pelkkä erotus aiempaan ilmoitukseen.

### Kirjanpidon valmistelu lukitulle kaudelle

Jos korjaus edellyttää kirjauksen lisäämistä tai muuttamista suljetulle kaudelle, käsittele kirjanpidon korjaus ensin. Tämän version kauden avaaminen ei automatisoi sulkukirjauksen ja lukituksen oikaisua.

1. Kirjaa talteen aiempi sulkukirjaus ja vastaanotetun ilmoituksen tunniste.
2. Sovi kirjanpidosta vastaavan kanssa, mitä tositteita ja päivämääriä korjataan ja miten olemassa oleva sulkukirjaus huomioidaan.
3. Tarvittavat lukituspäivän muutokset tekee käyttäjä, jolla on niihin oikeus. Kausirivin **Suljettu**-painike ei poista lukitusta.
4. Tee ja kirjaa korjaavat tositteet hyväksytyn menettelyn mukaisesti. Varmista tositteiden lopulliset kirjanpitopäivät: lukitus voi vaikuttaa päivämäärään.
5. Tarkista sulkutilien ja vastatilien saldot. Jos kausi avattiin, hoida aiempi sulkukirjaus ja uusi sulku hallitusti sekä palauta asianmukainen lukitus.
6. Tarkista MIS-luvut uudelleen. ALV-ilmoitusta vahvistettaessa kauden on oltava suljettu.

Tarkoitus on saada kirjanpito ja uusi ilmoitus vastaamaan toisiaan ilman kaksinkertaista sulkua. Tämä versio ei tarjoa yhdellä painikkeella tehtävää koko sulkukierroksen peruutusta.

Testattu esimerkki kokonaan uudelleen suljettavasta kaudesta: ota vanha sulkukirjaus talteen, siirrä verolukitus tarvittaessa kauden alkua edeltävään päivään, avaa kausi ja tee vanhalle sulkukirjaukselle vastakirjaus alkuperäisen sulun päivälle. Kirjaa korjaavat tositteet ja sulje kausi uudelleen. Tarkista uusi MIS-esikatselu ja lähetä korvaava ilmoitus. Jos vanha ALV-lasku on jo kirjattu tai maksettu, käsittele lisäksi luvun 15 laskuoikaisu. Pelkkä uusi sulku ilman vanhan sulun huomiointia voi jättää selvittelytilille virheellisen saldon.

### Odoosta aiemmin lähetetyn ilmoituksen korjaus

1. Avaa saman kauden ja saman ympäristön **Näytä ALV-ilmoitus** ja valitse **Tee korjaus**.
2. Valitse **Korjauksen syy**: Lasku- tai täyttövirhe, Oikeuskäytännön muutos, Verotarkastuksen ohjaus tai Laintulkintavirhe sen mukaan, mikä vastaa korjausta.
3. Tarkista **Ei toimintaa** -valinta uuden tilanteen mukaan.
4. Paina **Laske / päivitä esikatselu**.
5. Tarkista koko sisältö sekä kenttäkohtaiset vanhat ja uudet arvot. Sisällössä näkyy `ReplacementReturn: true`.
6. Vahvista ja seuraa uuden version vastaanottoa.
7. Tarkista erikseen ALV-laskun korjaustarve luvun 15 mukaan.

Edellinen Odoossa vastaanotettu ilmoitus tunnistetaan automaattisesti. **Korvaa aiemmin muualla annettu ALV-ilmoitus** -valintaa ei tarvita tähän. Jos tiedot eivät ole muuttuneet viimeisestä vastaanotetusta versiosta, moduuli estää tarpeettoman uuden lähetyksen. Esikatselu tai korjausdialogin avaaminen ei vielä muuta Verolla olevaa ilmoitusta.

### Aiemmin muualla annettu ilmoitus

Jos kauden aiempi ilmoitus on annettu esimerkiksi toisessa ohjelmistossa:

1. Varmista aiemman ilmoituksen kausi ja sisältö ulkoisesta lähteestä tai ALV-tilakyselyllä.
2. Valitse **Korvaa aiemmin muualla annettu ALV-ilmoitus** ja korjauksen syy.
3. Laske esikatselu uudelleen ja tarkista **kaikki** luvut aiempaa ilmoitusta vasten.
4. Vahvista ja seuraa vastaanottoa.

Muualla annettua ilmoitusta ei tuoda automaattisesti Odoon vertailuhistorian lähtöversioksi. Dialogin muutosvertailu perustuu Odoon omaan vastaanotettuun historiaan, joten ulkoisen lähtöversion vertailu pitää tehdä erikseen.

## 14. EU-yhteenvetoilmoituksen korjaaminen

1. Korjaa kyseisen kuukauden kirjanpito, ostajan tunniste tai veroruudukot tarpeen mukaan.
2. Avaa saman kuukauden ja ympäristön EU-ilmoitus.
3. Laske esikatselu uudelleen.
4. Tarkista muuttuneiden ostajien tiedot ja muutosvertailu.
5. Vahvista ja tarkista uuden lähetyksen vastaanotto.

EU-korjaus sisältää vain muuttuneet ostajat. Jokaiselle mukaan tulevalle ostajalle lähetetään kaikki kolme myyntilajisummaa. Kokonaan poistunut ostaja nollataan. Jos ostajan ALV-tunniste muuttuu, vanha tunniste nollataan ja uudelle tunnisteelle ilmoitetaan oikeat summat.

Esimerkiksi aiemmin vastaanotettu tavaramyynti 1 000 euroa muuttuu 200 euron hyvityksen jälkeen 800 euroksi. Korjaukseen tulee kyseiselle ostajalle tavaramyynniksi 800 euroa sekä hänen palvelu- ja kolmikantamyyntinsä kokonaismäärät; tavaramyynniksi ei lähetetä pelkkää −200 euron erotusta.

Toteutuksen automaattinen EU-korjausvertailu edellyttää aiempaa Odoossa vastaanotettua kokonaiskuvaa. Muualla annetun EU-ilmoituksen tuontia tai erillistä ulkoisen lähtöversion korjausvalintaa ei ole. Sellainen tilanne on selvitettävä erikseen ennen lähettämistä.

## 15. ALV-lasku, maksaminen ja laskun oikaisu

### Vastaanotetun ilmoituksen lasku

Kun vastaanotetun ALV-ilmoituksen laskettu nettomäärä on positiivinen, moduuli muodostaa ALV-ostolaskun **luonnokseksi**. Lasku tehdään yrityksen asetusten kumppanille ja ALV-tilille. Maksuviite tulee yrityksen asetuksesta, eräpäivä Veron kausikyselystä ja laskupäivä muodostamispäivästä. Laskun ALV-riville ei lisätä uutta veroa.

1. Avaa kausirivin **Ostolasku** tai lähetyksen **Avaa lasku / oikaisu**.
2. Tarkista yritys, kumppani, euromäärä, tilinumero, päiväkirja, kirjanpitotili, viite ja eräpäivä.
3. Kirjaa lasku Odoon normaalilla laskun vahvistustoiminnolla.
4. Maksa lasku yrityksen käytössä olevan maksuprosessin kautta.
5. Kohdista pankkitapahtuma ja tarkista avoin saldo sekä maksun tila.

Moduuli ei lähetä pankkimaksua eikä automaattisesti kirjaa luonnoslaskua. Kausirivin maksutila koskee liitettyä tositetta, joten korjausten jälkeen myös vanhat laskut ja hyvitykset on tarkistettava historiasta.

**Testi- ja sandbox-vastaanotto voivat myös käynnistää laskun muodostamisen.** Tee lähetyskokeet testitietokannassa keinotekoisella aineistolla.

### Luonnoslaskun korjaus

Kun korvaava ALV-ilmoitus vastaanotetaan ja kauteen liitetty lasku on vielä luonnos, moduuli voi perua vanhan luonnoksen ja muodostaa korjatun määrän uuden luonnoksen. Jos uusi määrä on nolla tai palautettava, uutta maksettavaa laskua ei synny. Jos määrä ei muutu ja aiempi lasku muuten vastaa ilmoitusta, sama lasku voidaan säilyttää.

Tarkista lopputulos lähetyksen laskuviestistä ja kauden laskulinkistä. Älä tee toista samansisältöistä laskua käsin, jos automaattisesti muodostettu luonnos on jo olemassa.

### Kirjatun tai maksetun laskun korjaus

Kirjattua laskua ei peruta automaattisesti. Vastaanotetulle korjaukselle tulee viesti erillisen laskuoikaisun tarpeesta.

1. Avaa kauden **uusin vastaanotettu ALV-lähetys** historiasta.
2. Valitse **Valmistele laskun oikaisu**.
3. Hyväksy vahvistus, kun olet tarkistanut alkuperäisen laskun ja korjatun määrän.
4. Toiminto luo alkuperäisen laskun koko määrän hyvitysluonnoksen ja, jos korjattu määrä on positiivinen, uuden laskuluonnoksen korjatulle kokonaismäärälle.
5. Tarkista luonnokset, päivämäärät ja tiliöinnit sekä kirjaa ne.
6. Kohdista hyvitys ja huomioi aiempi maksu kirjanpidon normaaleilla toiminnoilla.
7. Tarkista jäljelle jäävä velka tai saatava kaikkien tositteiden ja maksujen yhteisvaikutuksesta.

Alkuperäistä maksua tai maksukohdistusta ei pureta automaattisesti. Jos alkuperäinen 1 000 euron lasku oli jo maksettu ja korjattu ALV on 800 euroa, oikaisu tuottaa 1 000 euron hyvitysluonnoksen ja 800 euron laskuluonnoksen. Kirjanpitäjän pitää huomioida aiempi 1 000 euron maksu; uutta 800 euron laskua ei pidä maksaa tarkistamatta kokonaisuutta.

Toiminnon toistaminen avaa jo valmistellut oikaisuluonnokset. Jos alkuperäisellä laskulla on ennestään käsin tehty hyvitys, automaattinen oikaisu estetään päällekkäisen hyvityksen välttämiseksi. Tarkista silloin olemassa olevat tositteet erikseen.

Jos korjattu ALV on nolla tai palautettava, toiminto voi luoda alkuperäisen laskun hyvityksen ilman uutta maksettavaa laskua. Palautussaatavan muut kirjaukset on edelleen tarkistettava.

### Ilmoitus vastaanotettiin, mutta lasku ei syntynyt

Vastaanottokuittaus säilyy, vaikka laskuvaihe epäonnistuisi. Lue lähetyksen **Bill Message / laskuviesti**, korjaa esimerkiksi puuttuva toimittaja-, tili- tai eräpäivätieto ja käytä **Muodosta / tarkista lasku** -painiketta. Tämä toiminto ei lähetä veroilmoitusta uudelleen. Kirjatun laskun muuttunut määrä tarvitsee edelleen erillisen oikaisutoiminnon.

## 16. Aikakatkaisu ja epäselvän lähetyksen selvitys

Verkkoyhteyden katkeaminen voi tapahtua myös sen jälkeen, kun Vero on vastaanottanut ilmoituksen. Siksi moduuli ei lähetä epäselvää versiota automaattisesti uudelleen. Uusi lähetys samalle ilmoitukselle estetään, kun aiempi on jonossa, käsittelyssä tai epäselvä.

1. Avaa kyseinen lähetysyritys ja tarkista yritys, kausi, ympäristö, lähetysaika ja sisältö.
2. Lue virhe ja mahdollinen vastaus.
3. ALV-ilmoitukselle voit tehdä tilakyselyn. Selvitä silti juuri tämän version vastaanotto; aiempi ilmoitus voi jo näkyä palvelussa.
4. Varmista vastaanotto tai vastaanottamattomuus Verohallinnosta käytettävissä olevalla luotettavalla selvityksellä.
5. Kun lähetyksen tila on **Tulos epäselvä**, avaa **Kirjaa selvityksen tulos**.
6. Valitse joko **Vastaanotto varmistettu Verohallinnosta** tai **Verohallinto varmisti, ettei lähetystä vastaanotettu**.
7. Kirjoita **Selvityksen lähde ja perustelu**. Vastaanotetulle ilmoitukselle täytä lisäksi Verohallinnon vastaanottotunniste ja vastaanottoaika.
8. Paina **Tallenna varmistettu tulos**.

Toiminto ei tee uutta lähetystä. Alkuperäinen sisältö, vastaus ja verkkovirhe säilyvät historiassa, ja selvittäjä sekä selvitysaika tallennetaan.

Vastaanotetuksi käsin vahvistetun ALV-ilmoituksen jälkeen käytä tarvittaessa **Muodosta / tarkista lasku**. Jos Vero varmisti, ettei ilmoitusta vastaanotettu, palaa esikatseluun, laske ja tarkista tiedot ja tee uusi lähetys.

Jos prosessi keskeytyi ja tila jäi lähettäväksi, ajastus merkitsee yli 15 minuuttia vanhan keskeneräisen yrityksen epäselväksi seuraavalla soveltuvalla ajolla. Jos ajastus ei toimi, ylläpitäjän pitää selvittää se. Älä muuta tietokannan tilaa käsin lähetyksen vapauttamiseksi.

## 17. Tavallisimmat ongelmat

| Tilanne | Mitä tarkistetaan? |
|---|---|
| ALV-kaudet puuttuvat listalta | Poista Nykyinen tilikausi -suodatin. Tarkista yritys ja tilikauden kausien olemassaolo ennen uuden kausiston luontia. |
| Sulje ilmoittaa aiemmista avoimista kausista | Sulje kaudet aikajärjestyksessä. Jos edellinen kausi näyttää väärän yrityksen tiedolta, pyydä ylläpitäjää tarkistamaan alkuperäisen moduulin yritysrajaukset. |
| Sulkeminen epäonnistuu myös nollakaudella | Tarkista sulkupohja, päiväkirja, lukitukset ja virheen sisältö. API:n nollailmoitustuki ei yksin takaa alkuperäisen sulkumoottorin tyhjän kauden toimintaa kaikilla asetuksilla. |
| Avaa Raportti näyttää eri summan kuin API | Tarkista jakso, yritys, kirjattujen/luonnosten valinta ja suodattimet. Tarkista erityisesti suhteellisten MIS-sarakkeiden ajanjaksot. |
| MIS näyttää nollaa, vaikka laskuilla on veroa | Tarkista kirjattujen verorivien tunnisteet ja MIS-kaavat. Älä päättele oikeellisuutta pelkän veroprosentin perusteella. |
| Puuttuva MIS-rivi / Missing MIS report row | Yrityksen raporttipohjasta puuttuu vaadittu tekninen rivi. Ylläpitäjä tarkistaa liitteen kartoituksen. |
| Esikatselu ilmoittaa virheellisestä Y-tunnuksesta | Tarkista yrityksen VAT-kenttä ja tunnisteen oikeellisuus. |
| Yhteenveto ilmoittaa ostajan virheellisestä ALV-tunnisteesta | Tarkista virheessä mainittu tosite ja kaupallinen pääkumppani. Korjaa tunniste ja laske uudelleen. |
| Lähetys pyytää päivittämään esikatselun | Aineisto tai valinnat muuttuivat. Laske uudelleen ja tarkista uusi sisältö ennen vahvistusta. |
| Ei muutoksia viimeiseen vastaanotettuun ilmoitukseen | Sama sisältö on jo vastaanotettu. Uutta lähetystä ei muodosteta. |
| Verolla on jo ilmoitus | Tarkista historia ja kausi. Jos aiempi ilmoitus tehtiin muualla, käytä sitä varten olevaa korvausvalintaa ja valitse korjauksen syy. |
| Kausi ei vastaa Veron kautta | Tarkista alku/loppupäivä, yrityksen ilmoitusjakso ja ympäristö. Sandboxin mallipäivämäärät voivat aiheuttaa tämän virheen. |
| Avaintiedostoa ei voi lukea / yhteysasetukset puuttuvat | Ylläpitäjä tarkistaa palvelinpolun, tiedoston sisällön olemassaolon, oikeudet ja ympäristön. Älä liitä avainta virheilmoitukseen. |
| Ilmoitus jää Jonossa-tilaan | Ylläpitäjä tarkistaa ajastuksen Vero API: process confirmed submissions, palvelun lokin ja käyttäjän oikeudet. |
| Tulos epäselvä / lähetys on jo kesken | Noudata luvun 16 selvitysmenettelyä. Uusi napsautus ei ratkaise vastaanoton epävarmuutta. |
| Kuitti on tallessa, mutta lasku puuttuu | Tarkista laskuviesti sekä yrityksen tili ja toimittaja. Käytä Muodosta / tarkista lasku; älä lähetä ilmoitusta uudelleen tämän vuoksi. |
| Vihreä kuvake puuttuu korjauksen jälkeen | Katso uusimman yrityksen tila. Aiempi vastaanotettu versio säilyy historiassa, vaikka uusin korjaus olisi virheessä. |

Ylläpidolle toimitettavat tiedot: yritys, kausi, testi/tuotanto, ilmoituksen ja lähetysyrityksen tunniste, tapahtuma-aika, virheteksti, HTTP-tila sekä tarvittaessa kuittitunniste. Käyttöavaimia, yksityisiä avaimia tai tokenien sisältöä ei tarvita vikailmoitukseen.

## 18. Tarkistuslista ja nykyiset rajaukset

### Ennen lähettämistä

- Oikea yritys, kausi ja ympäristö on valittu.
- Kauden aineisto on kirjattu ja veroruudukot on tarkistettu.
- API-esikatselun summat täsmäävät tarkistettuun kirjanpitoon.
- ALV-kausi on suljettu; EU-ilmoitukselle on valittu oikea kuukausi.
- Ensimmäisen ilmoituksen, korjauksen ja Ei toimintaa -valinnat vastaavat tilannetta.
- Aikaisempaa epäselvää lähetystä ei ole selvittämättä.

### Lähettämisen jälkeen

- Vastaanottotunniste ja vastaanottoaika on tarkistettu oikeassa ympäristössä.
- Virhe- ja laskuviestit on luettu.
- ALV-lasku tai tarvittavat oikaisuluonnokset on tarkistettu.
- Laskun kirjaaminen, maksaminen ja kohdistukset on hoidettu erikseen.
- EU-ilmoituksista on tarkistettu tarvittavat kuukaudet, ei pelkkää vihreää kuvaketta.

### Rajaukset, jotka vaikuttavat käyttöön

- API-kartoitus on toteutettu vuodesta 2026 alkaville kausille ja EUR-kirjanpidolle. Tätä vanhemmat kaudet estetään.
- Tulevaisuudessa alkavan kauden lähetys estetään. Tarkista silti kauden aineiston valmistuminen itse; ohjelma ei takaa, että kauden kaikki tositteet on vastaanotettu ja kirjattu.
- Sandboxin mallivastaukset eivät tällä hetkellä mahdollista koko tavallisen ALV-ketjun hyväksymistestausta. Vastaanottokuitti sandboxista ei ole tuotannon veroilmoitus.
- Varmenteellinen päästä päähän -testaus ja tuotantohyväksyntä ovat vielä tekemättä. Ohjelmistotestit kattavat 46 moduulitestiä ja yhdeksän erillistä commit-/rinnakkaisuusskenaariota; ne eivät korvaa näitä hyväksymisiä.
- Tässä ohjeessa kuvatut alkuperäisen kausimoduulin tilikausigeneraattori, moniyritystoiminnot, suhteelliset MIS-jaksot ja sulun avaaminen tarvitsevat omat tarkistuksensa. Niitä ei pidä tulkita kokonaan uudistetuksi Vero API -toteutuksen yhteydessä.
- Vihreä kuvake tarkoittaa vastaanottokuittausta, ei lopullista verotuspäätöstä. Tilakysely ja vastaanoton selvitys ovat erillisiä toimintoja.
- Muualla annettua ilmoitusta ei tuoda automaattisesti Odoon muutosvertailun lähtöversioksi. EU-ilmoitukselle ei ole tässä versiossa ulkoisen lähtöversion korjaustoimintoa.
- Laskujen maksaminen, pankkikohdistus ja palautusten kirjaaminen eivät tapahdu automaattisesti.
- Tunnistetiedostojen uusiminen sekä mahdollisen valtuutustokenin ylläpito ovat ylläpidon tehtäviä.

## 19. Liite: ilmoituskentät ja tiedon lähteet

### ALV-esikatselun perustiedot

| JSON-kenttä | Selitys |
|---|---|
| `BusinessId` | Ilmoituksen yrityksen Y-tunnus |
| `FilingPeriod` | ALV-kauden loppupäivä |
| `ContactDetails` | Yhteyshenkilön nimi ja puhelin Vero-yhteyden asetuksista |
| `NoActivity` | Ei toimintaa -valinta |
| `ReplacementReturn` | Onko kyse korvaavasta ALV-ilmoituksesta |
| `ReplacementReason` | Valittu korjauksen syy |
| `VATDetails` | Ilmoitettavat verot ja myynti-/ostoperusteet; jätetään pois Ei toimintaa -ilmoituksesta |

### MIS-rivien vastaavuus ALV-ilmoitukseen

API käyttää rivien teknisiä nimiä. Näkyvän otsikon muuttaminen ei välttämättä muuta teknistä nimeä. Rivin puuttuminen estää laskennan; puuttuvaa lukua ei arvata. Tavallinen tyhjä MIS-laskentatulos voidaan tulkita nollaksi.

| MIS-rivin tekninen nimi | Ilmoitettava tieto |
|---|---|
| `vero_25_5` | Kotimaan myyntien ylemmän verokannan vero / `HighVATRate` |
| `vero_13_5` | Kotimaan myyntien keskimmäisen verokannan vero / `MediumVATRate` |
| `vero_10` | Kotimaan myyntien alimman verokannan vero / `LowVATRate` |
| `vero_tavaraostoista_muista_eu_maista` | EU-tavaraostojen vero |
| `vero_palveluostoista_muista_eu_maista` | EU-palveluostojen vero |
| `vero_tavaroiden_maahantuonneista_eu_ulkopuolelta` | EU:n ulkopuolisen maahantuonnin vero |
| `vero_rakentamispalvelun_ja_metalliromun_ostoista_kaannetty_verovelvollisuus` | Rakentamispalvelun ja metalliromun ostojen vero |
| `verokauden_vahennettava_vero` | Vähennettävä vero / `DeductibleVAT` |
| `verokannan_0_alainen_liikevaihto` | Nollaverokannan alainen liikevaihto |
| `tavaroiden_myynnit_muihin_eu_maihin` | Tavaramyynnit muihin EU-maihin |
| `palvelujen_myynnit_muihin_eu_maihin` | Palvelumyynnit muihin EU-maihin |
| `tavaraostot_muista_eu_maista` | Tavaraostot muista EU-maista |
| `palveluostot_muista_eu_maista` | Palveluostot muista EU-maista |
| `tavaroiden_maahantuonnit_eu_ulkopuolelta` | Maahantuonnit EU:n ulkopuolelta |
| `rakentamispalvelun_ja_metalliromun_myynnit_kaannetty_verovelvollisuus` | Käännetyn verovelvollisuuden rakentamis- ja metalliromumyynnit |
| `rakentamispalvelun_ja_metalliromun_ostot_kaannetty_verovelvollisuus` | Käännetyn verovelvollisuuden rakentamis- ja metalliromuostot |

Vanhan raporttipohjan `vero_14` hyväksytään keskimmäisen kannan rivin vaihtoehtoisena nimenä, jos `vero_13_5` puuttuu. Nimen yhteensopivuus ei muuta kirjauksilla käytettyjä veroprosentteja tai tunnisteita.

Moduulin ALV-laskua varten laskema maksettava määrä on kotimaan myynnin verojen ja ostojen/maahantuonnin verojen summa, josta vähennetään vähennettävä vero. Myynnin ja ostojen verottomia perusteita ei lisätä maksettavaan veroon. Ilmoitusarvot pyöristetään kahteen desimaaliin.

### EU-esikatselu

| JSON-kenttä | Selitys |
|---|---|
| `FilingPeriod.Month` ja `FilingPeriod.Year` | Ilmoitettava kuukausi ja vuosi |
| `Buyers` | Ilmoitettavat ostajat; korjauksessa muuttuneet ostajat |
| `CountryCode` | Ostajan ALV-tunnisteen maatunnus |
| `VATIdentifier` | Ostajan ALV-tunniste ilman maatunnusta |
| `SalesOfGoods` | Ostajan tavaramyynnin veroton määrä |
| `SalesOfServices` | Ostajan palvelumyynnin veroton määrä |
| `TriangulationSales` | Ostajan kolmikantamyynnin veroton määrä |

### Ohjeen perusteet

Ohje on tarkistettu tämän version malleista, dialogeista, näkymistä ja käännöksistä: `models/account_vat_period.py`, `models/account_fiscal_year.py`, `wizards/date_range_generator.py`, yritys- ja MIS-laajennukset, `models/vero_*.py`, `wizards/vero_wizard.py`, `vero_payload.py`, `views/` ja `i18n/fi.po`. Sulkukirjauksen toiminta on tarkistettu riippuvuuden `account_period_close` lähteestä. Testitulokset ja `commu`-asetusten korjaus perustuvat 17.9.2026 tehtyihin tarkistuksiin.

Tekninen käyttöönotto- ja testauskuvaus: [README_VERO_API.md](README_VERO_API.md).
