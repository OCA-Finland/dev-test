# Vero API – Odoo 18 Community MVP

Tiivis, kuvitettu käyttöönotto-ohje (viranomaisasiat, avain ja varmenne):
[Vero API -käyttöönoton pikaohje (PDF)](docs/Vero_API_kayttoonotto_pikaohje.pdf).

Koko kausimoduulin vaiheittainen käyttäjäohje:
[ALV-kaudet ja Vero API – käyttöohje](KAYTTOOHJE_FI.md).

Toteutus täydentää `account_vat_periods`-moduulia. ALV- ja EU-yhteenvetoilmoitukset
lähetetään itsenäisesti. Yhteenvetoilmoituksen kohde on aina kalenterikuukausi.
Kaikki Vero-toiminnot edellyttävät ryhmää `account.group_account_user`;
`account.group_account_readonly` ei riitä.

## Ilmoitusten tila ja kaksoislähetyksen esto (18.0.1.3.0)

Kausilista näyttää ALV- ja EU-ilmoitukset erikseen ympäristöineen ja kuukausineen.
Rivin toiminto avaa olemassa olevan lähetyksen tilan. Vastaanotetun ilmoituksen
korjaus aloitetaan erikseen; jonossa, lähetyksessä tai epäselvänä oleva ilmoitus
estää uuden esikatselun ja lähetyksen. Yhteyden tai EU-kuukauden voi valita
listan erillisistä kuvakkeista. Useiden ilmoitusten tiloja ei yhdistetä yhdeksi
vihreäksi kuittaukseksi, jos jokin niistä on kesken.

ALV-esikatselu tekee GetVATPeriods/v1-kyselyn. Kausivirhe tai yhteyden epäonnistuminen
näkyy ennen vahvistamista ja estää jonoon lisäämisen. Ajastin tarkistaa kauden
edelleen uudelleen juuri ennen lähetystä. Pelkkä kausikysely ei vahvista yksittäisen
lähetysyrityksen vastaanottoa. Jonoon lisäämisestä näytetään selvä kuittaus.

Listat päivittyvät 10 sekunnin välein näkyvissä ollessaan. Dialogin, rivimuokkauksen
tai rivivalinnan aikana ei tehdä automaattista latausta; avoimen esikatselun valinnat
säilyvät. Tiladialogissa on erillinen paikallisen lähetyksen päivityspainike.

## Asennus ja asetukset

Tarvitaan nykyisten riippuvuuksien lisäksi OCA:n `connector`- ja `queue`-repositorion
18.0-haarat addons-polulle. Connectorin riippuvuudet asennetaan normaalisti.
Tämä MVP käyttää `connector.backend`-pohjaa yhteysasetuksiin ja omaa kerran
minuutissa ajettavaa Odoo-ajastusta lähettämiseen. `queue_job`-runneria ei tarvita.
Enterprise-moduuleja ei tarvita.

Versiosta 18.0.1.2.0 alkaen avaimet voi syöttää ja tilatun varmenteen noutaa
Odoon **Avaimet ja varmenne** -toiminnossa. Testi- ja tuotantoympäristöt on tuettu.
Käyttö edellyttää HTTPS:ää. Varmennetilaus ja ohjelmistorekisteröinti tehdään
edelleen Verohallinnon palveluissa; automaattinen varmenteen uusiminen ei kuulu versioon.

Palvelinriippuvuudet: Linux, OpenSSL 3, `signxml>=4.5.1,<5` ja sen kanssa
yhteensopivat `cryptography`/`pyOpenSSL`-versiot. Kehitysympäristössä testattu:
signxml 4.5.1, cryptography 46.0.7, pyOpenSSL 25.3.0, lxml 5.2.1.
Tarkista muun Odoo-asennuksen riippuvuudet ja aja `pip check` päivityksen yhteydessä.
Moduulin päivitys ja palvelun restart tarvitaan kerran; myöhemmät avainvaihdot
ja noudot eivät vaadi restartia.

Salaisuudet ovat `data_dir/vero_credentials`-hakemistossa, eivät tietokannassa
tai filestoressa. Hakemisto tulee ottaa mukaan suojattuun varmistukseen ja
palautussuunnitelmaan. Linux-palvelukäyttäjä tarvitsee kirjoitusoikeuden omaan
data_dir-hakemistoonsa. HTTP-reitti käyttää kirjautumista, CSRF-tarkistusta,
HTTPS-vaatimusta sekä palvelinpuolen yritys-/käyttöoikeustarkistuksia. Reitti
ei käytä RPC:tä salaisuuksille. Reverse proxyn tulee poistaa asiakkaan omat
Forwarded-otsakkeet, asettaa oikeat HTTPS-otsakkeet ja estää suora pääsy Odoon
taustaporttiin. Proxy/WAF/APM ei saa tallentaa avaintoimintojen POST-runkoja.

Normaalit avaintoiminnot käyttävät `account.group_account_user`-oikeutta.
Palvelinpolkujen käsin muuttaminen vaatii `base.group_system`-oikeuden;
pelkkä kirjanpito-oikeus ei saa osoittaa yhteyttä muiden yritysten tiedostoihin.
Tämä tarkistetaan sekä `create`- että `write`-kutsuissa, myös RPC-käytössä.

Vastauksen XML-allekirjoitus tarkistetaan SignXML:llä ja varmenneketjut
OpenSSL:llä. `data/vero_ca/` sisältää Verohallinnon julkiset testi- ja
tuotantoympäristön Data Providers / IR Services -CA-ketjut, ladattu 5.10.2026
[viralliselta dokumentaatiosivulta](https://www.vero.fi/tietoa-verohallinnosta/kehittaja/varmennepalvelu/dokumentaatio/).
Julkiset CA-varmenteet eivät ole asiakasvarmenteita tai yksityisiä avaimia.
Luottamuspakettien päivitys kuuluu moduulin ylläpitoon; paketteja ei haeta
ajon aikana käyttäjän syöttämistä osoitteista. Erillistä asiakasvarmenteen
CRL-/OCSP-tarkistusta ei tässä versiossa tehdä; API-yhteystesti näyttää
palvelun hyväksymän tai hylkäämän yhteyden.

Kirjanpito → Asetukset / Configuration → Vero API -yhteydet (Configuration-valikon nykyisillä kirjanpidon ylläpitäjän oikeuksilla; myös Connector-oikopolku säilyy):

1. Luo yritykselle yhteys ja valitse ympäristö. Yrityksellä on yksi yhteys per
   ympäristö. Ilmoitushistorian synnyttyä yritystä ja ympäristöä ei voi vaihtaa.
   API-perusosoitteen voi täydentää esikatselun jälkeen ja korjata, jos kaikki
   lähetysyritykset ovat varmasti epäonnistuneet. Jonossa oleva, epäselvä tai
   vastaanotettu lähetys lukitsee osoitteen. Jos yrityksellä on useita aktiivisia ympäristöjä,
   valitse yhteys itse esikatseluikkunassa.
2. Tarkista yrityksen suomalainen ALV-tunniste/Y-tunnus, EUR-kirjanpitovaluutta,
   ALV:n MIS-raportti, verovelkatili ja Verohallinnon toimittajakumppani.
3. Anna yhteyshenkilön nimi ja puhelinnumero.
4. Valitse EU-tavara-, palvelu- ja tarvittaessa kolmikantamyynnin **verottomien
   perusteiden** tax grid -tunnisteet. Tyhjät tai väärät tunnistevalinnat pitää
   korjata ennen yhteenvetoilmoituksen käyttöönottoa.
5. Hanki ohjelmistoavain ja tilaa varmenne. Tallenna yhteys, avaa **Avaimet ja
   varmenne**, tallenna ohjelmistoavain ja nouda varmenne saamillasi siirtotunnuksilla.
   Odoo luo tiedostot ja polut automaattisesti. Aiemmat palvelinpolut toimivat edelleen.
6. Kopioi ympäristön SAT API:n perusosoite Vero-portaalista. Sallittuja palvelimia
   ovat `apitest.vero.fi`, `api.vero.fi` ja sandboxissa `api-sandbox.vero.fi`.
   Sandbox käyttää tilausavainta ja ennalta määrättyjä esimerkkivastauksia.
   Se ei korvaa varmenteellisen testipalvelun hyväksymistestausta.

Sandboxiin riittää https://api-developer.vero.fi/ -palvelun tilausavain:
valitse `Sandbox`, tallenna tilausavain **Avaimet ja varmenne** -toiminnossa
ja jätä varmennetiedostot tyhjiksi. SAT-perusosoite on
`https://api-sandbox.vero.fi/Return/SAT`. Moduuli lisää myös sandboxin
vaatiman `Vero-SoftwareKey: sandbox` -otsakkeen. Rekisteröityä ohjelmistoavainta
ei tarvita sandboxiin; pääsynhallinta käyttää tilausavainta.

Käytä sandboxissa vain keinotekoisia yritys-, henkilö- ja kirjanpitotietoja.
17.9.2026 testatut lähetysrajapinnat palauttivat vastaanottokuitit, mutta vuoden
2026 kausihaku palautti päivämäärien ja tilan kohdalla vain `string`-malliarvot.
Siksi normaali ALV-työnkulku pysähtyy kausitarkistukseen. Sandboxin onnistunut
suora lähetyskutsu ei todenna koko Odoo-työnkulkua tai Veron käsittelyketjua.

Jos käytetään puolesta asioinnin tokenia, sille on erillinen tiedostopolku.
Tokenin automaattinen uusiminen ei sisälly tähän MVP:hen. Testaa testiyhteyksiä
testitietokannassa: hyväksytyn testilähetyksenkin laskuvaihe toimii normaalisti.

## Käyttö

Kausirivin ALV-painike avaa esikatselun. ALV-kausi pitää sulkea ennen lähettämistä.
EU-yhteenveto-painike avaa itsenäisen kuukausivalinnan; se ei vaadi ALV-kauden
sulkemista tai ALV-ilmoituksen lähettämistä. Laskenta ei tarvitse API-varmennetta.

Esikatselu näyttää varsinaisen lähetettävän JSON-sisällön ja kenttäkohtaiset
muutokset viimeiseen vastaanotettuun versioon. Lähetys laskee tiedot uudelleen
ja estyy, jos ne tai korjauksen valinnat poikkeavat esikatselusta.
Vahvistettu versio tallennetaan ja ajastettu työ lähettää sen aloittajan oikeuksilla.

ALV-korjaus korvaa koko ilmoituksen ja edellyttää korjauksen syytä. Muualla
annettu ALV-ilmoitus voidaan korvata valitsemalla tätä koskeva valinta; vertailun
lähtöversiota ei silloin ole Odoon omassa historiassa. EU-korjaus sisältää vain
muuttuneet ostajat täydellisin myyntilajiarvoin. Poistettu ostaja nollataan.

Vero API -tila avaa ilmoitukset ja niistä lähetysyritykset, alkuperäiset sisällöt,
vastaukset ja kuittaukset. ALV:lle voi tehdä `GetFiledVATReturn/v2`-tilakyselyn.
EU-yhteenvedolle julkisessa SAT-rajapinnassa ei ole vastaavaa hakutoimintoa.

Vihreä kuvake tarkoittaa tallennettua vastaanottokuittausta, ei lopullista
verotuspäätöstä. Testi/tuotanto näkyy erikseen. EU-kuvake koskee luotuja
kuukausi-ilmoituksia: se ei väitä, että kaikki vuosineljänneksen kuukaudet on annettu.
Vanhaa `sent`-merkintää ei tulkita Vero-kuittaukseksi.

## Aikakatkaisu ja kirjanpito

Lähetysyritys kirjataan tietokantaan ennen verkkokutsua. Epäselvää lähetystä ei
toisteta automaattisesti. Aikakatkaisu, palvelinvirhe, puuttuva kuittaus tai
keskeytynyt prosessi jättää näkyvän epäselvän tilan. Toinen lähetys estetään.

Selvitä juuri kyseisen yrityksen/kauden/version vastaanotto Verohallinnosta.
Lähetyksen **Kirjaa selvityksen tulos** -toimintoon merkitään varmistettu tulos
ja selvityksen lähde. Vastaanotetulle versiolle vaaditaan myös Verohallinnon
vastaanottotunniste ja vastaanottoaika. Selvittäjä ja ajankohta tallentuvat.
Vanha kyselyvastaus ei itsestään kuittaa uutta epäselvää lähetystä onnistuneeksi.

Vastaanotetusta maksettavasta ALV:sta syntyy luonnoslasku. Korjaus voi perua
vanhan **luonnoksen** ja luoda uuden. Nolla- tai palautusilmoitus ei luo uutta
maksettavaa laskua. Eräpäivä saadaan Vero-kausikyselystä.

**Kirjatun tai maksetun laskun oikaisu edellyttää erillistä toimintoa.**
Lähetyksen **Valmistele laskun oikaisu** muodostaa alkuperäisen laskun
hyvitysluonnoksen ja positiiviselle korjatulle määrälle uuden laskuluonnoksen.
Alkuperäinen lasku, hyvitys ja korvaava lasku säilyvät linkitettyinä historiassa.
Toiminnon toistaminen avaa samat luonnokset. Kirjanpitäjä tarkistaa ja kirjaa
luonnokset sekä kohdistaa hyvityksen Odoon normaaleilla toiminnoilla. Alkuperäistä
maksua tai maksukohdistusta ei pureta automaattisesti. Jos laskulle on jo tehty
hyvitys käsin, toiminto estää uuden päällekkäisen hyvityksen.

Laskuvaiheen virhe ei poista Vero-vastaanottokuittausta. Laskuvaiheen voi yrittää
uudelleen erillisellä painikkeella ilman uutta Vero-lähetystä.

## Rajaukset ja testaus

Kartoitus on tehty vuoden 2026 ja myöhempien kausien EUR-raportoinnille.
ALV-luvut luetaan Suomen MIS-pohjan teknisiltä KPI-riveiltä. Vanhan pohjan
`vero_14`-rivi hyväksytään `vero_13_5`-rivin aliaksena; varsinaisen verokannan
ja kirjanpidon veroruudukkojen oikeellisuus on tarkistettava raporttipohjasta.
EU-erittely lasketaan kirjatuista veroruudukollisista pääkirjariveistä
kaupallisen kumppanin ALV-tunnisteella. Hyvitysrivin etumerkki vähentää myyntiä.

17.9.2026 katselmoinnin jälkeen: 46 Odoo-moduulitestiä ja 9 erillisillä, oikeasti commitoivilla
tietokantayhteyksillä tehtyä skenaariota läpäisi. Testikopiosta poistettiin
Enterprise-moduulit ja Enterprise-polku. Mukana ovat MIS-laskenta, ALV- ja
EU-korjaukset, nolla/palautus, luonnoslaskun korvaaminen, maksetun laskun/maksun
säilyminen ja oikaisun nettovelka, oikeudet, yritysrajaus, aikakatkaisu,
prosessikatko ja todelliset rinnakkaiset lähetyspyynnöt. Oikeat Vero-testipalvelun
lähetykset ja käyttäjän käyttöliittymän hyväksymiskierros ovat vielä tekemättä.
Ajastuksen regressiotesti kattaa myös käynnistyksen ilman HTTP-istunnon
kielikontekstia. Selaimessa on tarkistettu kausipainikkeet, ALV/EU-dialogit,
tilanäkymä ja yhteysasetusten lomake.

Katselmoinnissa lisättiin 22 regressiotestiä. Mukana ovat oikea lasku ja hyvitys
MIS-laskennassa, yhteyden valmistelu ja korjaaminen virheen jälkeen, usean
ympäristön nimenomainen valinta, oikeuksien poistaminen jonotuksen jälkeen,
yritysrajauksen suorat palvelinkutsut sekä HTTP-virheet. Tilapäinen MIS-instanssi
luodaan ja poistetaan rajatuin korotetuin oikeuksin. Itse laskenta käyttää
aloittajan oikeuksia ja vain raportin yritystä; kutsujan oletusarvokontekstia
ei siirretä korotettuun luontiin.

### Asennuksen numeerinen tarkistus

Pelkkä moduulitestien läpäisy ei varmista yrityksen verojen ja MIS-pohjan
asetuksia. `tests/diagnose_installed_vat_mapping.py` tarkistaa asennetun
25,5 % myyntiveron aidolla 1 000 euron laskulla ja 200 euron hyvityksellä:
sekä kirjanpidon että MIS-rivin nettomuutoksen pitää olla 204 euroa.
Aja skripti vain hävitettävän `commu_veroapi_test...`- tai
`commu_veroapi_flow_test...`-kopion Odoo shellissä. Skripti ei tee API-kutsuja
ja peruu aina oman tietokantatapahtumansa.

17.9.2026 nykyisen asennuksen tarkistus **epäonnistui**: myyntiverolla oli
±fi_301-ruudukot, mutta `vero_25_5`-MIS-rivi haki ±fi_320-ruudukoita.
Kirjanpidon vero oli 204 euroa, MIS-rivin muutos 0 euroa. Sama ristiriita
todettiin `commu`-tietokannan asetuksissa vain lukemalla niitä.
Yrityksen verot ja MIS-kaavat on sovitettava yhteen ja tarkistus läpäistävä
ennen oikeita ilmoituksia. Myös alempien verokantojen kaavat on tarkistettava:
`commu`-kaavoissa oli ±302/±303, mutta asennetut tagit ovat ±fi_302/±fi_303.
Näitä olemassa olevia kirjanpitoasetuksia ei muutettu koodikatselmoinnissa.

Myöhemmin 17.9.2026 käyttäjän pyynnöstä MIS-kaavat korjattiin `commu`-ympäristön
käyttöliittymässä: `vero_25_5` → ±fi_301, `vero_13_5` → ±fi_302 ja
`vero_10` → ±fi_303. Tuoreessa `commu_veroapi_test_ui_20260917_172205`-kopiossa
asennetun 25,5 % veron diagnostiikka **läpäisi**: kirjanpito 204 euroa ja
MIS 204 euroa. Alempien kantojen kaavat varmistettiin asetustasolla.

Tavalliset testit: Odoo `--test-enable --test-tags /account_vat_periods`.
`tests/committed_scenarios.py` ajetaan Odoo shellissä tuoreella, hävitettävällä
`commu_veroapi_flow_test...`-tietokannalla: `run(env)`. Se korvaa verkkoliikenteen
testivastauksilla ja tekee tarkoituksellisesti tietokantacommitteja.

## Rajapinnan lähde

Vero Developer Portalin julkinen SAT OpenAPI -vienti, luettu 17.9.2026:
https://api-developer.vero.fi/mapi/apis/SAT?format=openapi%2Bjson&export=true&api-version=2023-03-01-preview

Käytetyt operaatiot: `FileVATReturn/v2`, `FileECSalesList/v1`,
`GetFiledVATReturn/v2`, `GetVATPeriods/v1`. Tarkka testipalvelun sopimus,
varmennevaltuudet ja vastaanotto pitää vielä varmistaa aidossa testipalvelussa.

## Testivarmenteen nouto rajapinnasta

Moduulin mukana on ylläpitäjälle tarkoitettu Linux-komentorivityökalu
[testivarmenteen noutamiseen](tools/README.md). Se luo yksityisen avaimen
palvelimella ja käyttää Verohallinnon SignNewCertificate- ja GetCertificate-
rajapintoja. Nouto ei vielä sisälly Odoon käyttöliittymään. Tuotantovarmenteiden
nouto ja automaattinen uusiminen eivät kuulu tähän työkaluun.
