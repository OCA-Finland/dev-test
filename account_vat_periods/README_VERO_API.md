# Vero API – Odoo 18 Community MVP

Tiivis, kuvitettu käyttöönotto-ohje (viranomaisasiat, avain ja varmenne):
[Vero API -käyttöönoton pikaohje (PDF)](docs/Vero_API_kayttoonotto_pikaohje.pdf).

Koko kausimoduulin tiivis, kuvitettu käyttöohje:
[ALV-kaudet ja Vero API – käyttäjän pikaohje (PDF)](docs/ALV_kaudet_ja_Vero_API_kayttoohje.pdf).

Yksityiskohtainen käyttäjäohje:
[ALV-kaudet ja Vero API – käyttöohje](KAYTTOOHJE_FI.md).

Toteutus täydentää `account_vat_periods`-moduulia. ALV- ja EU-yhteenvetoilmoitukset
lähetetään itsenäisesti. Yhteenvetoilmoituksen kohde on aina kalenterikuukausi.
Kaikki Vero-toiminnot edellyttävät ryhmää `account.group_account_user`;
`account.group_account_readonly` ei riitä.

## Tilakyselyjen tulkinta (18.0.1.8.5)

Sekä sandbox että testivarmenteellinen Vero-testipalvelu palauttavat mallivastauksia.
Niiden `Processed`-tila ei todista käyttäjän lähettäneen kyseisen kauden ilmoitusta,
eikä pakota testi-ilmoitusta korvaavaksi ilmoitukseksi. Myös testissä tarkistetaan
vastauksen rakenne, kauden päivämäärät ja kauden vanhentuminen. Odoon oma
lähetyshistoria määrää, onko kyseessä aiemman testilähetyksen korjaus.

Tuotannossa `Processed` ja `Being Processed` edellyttävät edelleen korvaavaa
ilmoitusta. `Estimated` tarkoittaa arvioverotusta: puuttuva ilmoitus voidaan antaa
alkuperäisenä. Arvioverotus yksin ei oikeuta valitsemaan aiemmin muualla annetun
ilmoituksen korvaamista. Odoossa tallennettu aiemman ilmoituksen vastaanottokuitti
säilyy erillisenä todisteena, vaikka kysely palauttaisi vanhempaa tilatietoa.

Tilakysely-välilehdellä ilmoituskyselyllä ja kauden tarkistuksella on omat tilansa,
aikaleimansa, pyyntönsä ja vastauksensa. Virheellinen vastaus näytetään selkeänä
virheenä. Kysely ei koskaan kuittaa lähetysyritystä vastaanotetuksi eikä lähetä sitä
uudelleen. Pelkkä testipalvelun kysely ei varmista tuotannon ilmoitushistoriaa.

Lähde: [Verohallinnon testausohje](https://www.vero.fi/tietoa-verohallinnosta/kehittaja/vero-api/testaus/).

## ALV- ja EU-dialogien yhtenäiset painikkeet (18.0.1.8.4)

Myös ALV-kausilta ja EU-kuukausilta avattava dialogi käyttää yhtä **Päivitä tila**
-painiketta. Vastaanotetun ilmoituksen toiminnot ovat **Tee korjaus**, **Päivitä tila**
ja **Sulje**. Jonossa, lähetyksessä tai epäselvässä tilassa korjausta ei tarjota.
Ilman lähetysyritystä tilanäkymässä on **Valmistele ilmoitus** ja **Sulje**.
ALV-kausi tai EU-kuukausi valitaan listalta ja uusi EU-kuukausi omalta näytöltään.
Versiossa 18.0.1.8.6 kausirivin yhteydenvaihtopainike ja sen erilliset toiminnot
on poistettu. Yrityksen ainoa käytettävissä oleva yhteys valitaan automaattisesti.
Aiempi ilmoitus avataan normaalista ilmoituspainikkeesta omine tietoineen.

ALV:n valmistelussa **Päivitä tila** voi hakea myös muualla annetun ilmoituksen,
vaikka Odoossa ei vielä ole lähetyshistoriaa. Kysely säilyttää esikatselun,
korjausvalinnat ja vahvistamisen ehdot; se ei korvaa esikatselun laskentaa.
Tyhjä Tilakysely-välilehti piilotetaan kaikissa avausreiteissä.

## Seurantadialogin toiminnot (18.0.1.8.3)

Yhteisen Vero API -ilmoitukset -raportin Tila ja vastaukset avaa seurantadialogin.
Jos lähetysyrityksiä ei ole, dialogi kertoo, ettei ilmoitusta ole vielä lähetetty,
ja siinä on vain Sulje-painike. Tyhjää lähetyshistoriaa ei näytetä.
Kun lähetysyritys on olemassa, dialogissa on Päivitä tila ja Sulje.
Jonossa olevien ja lähetettävien ilmoitusten sekä EU-ilmoitusten päivitys lukee
Odoon tallennetun tilan. Muiden ALV-lähetysten päivitys hakee lisäksi
Verohallinnon tiedot. Kysely ei vahvista epäselvän lähetyksen vastaanottoa
eikä lähetä ilmoitusta uudelleen. Valmistelu, korjaus ja yhteyden valinta
tehdään ALV-kausien tai EU-yhteenvetoilmoitusten omissa työnäkymissä.

## Ilmoitusten yhteinen seurantanäkymä (18.0.1.8.2)

Vero API -ilmoitukset sijaitsee kohdassa **Laskutus → Raportointi → Hallinta**.
Yhteinen lista käyttää omaa ALV- ja EU-ilmoitusten seurantanäkymää ja hakua.
Siinä näkyvät ilmoitustyyppi, kauden päivämäärät, yritys, ympäristö ja tila;
Tila ja vastaukset avaa ilmoituksen tiedot ja lähetyshistorian.
Valitse kuukausi on vain EU-yhteenvetoilmoitusten näytöllä. Ilmoitukset
valmistellaan ja korjataan edelleen ALV- tai EU-näkymän kautta.

## Katselmoinnin korjaukset (18.0.1.8.1)

- Kausien tietuetason yritysrajaus koskee myös suoria hakuja ja lukukäyttäjiä.
  Tilikauden kaudet luodaan kyseisen yrityksen tiedoilla sen alku- ja loppupäivien
  sisälle. Uusilla ALV-kausilla on oma yhteinen kausityyppi; olemassa olevia
  tilikausikuukausien tyyppejä ja niiden yritysasetuksia ei muuteta.
- Nykyinen tilikausi -suodatin lasketaan avattaessa. Avaa Raportti avaa erillisen
  tilapäisen MIS-raportin kauden yritykselle ja täsmälliselle päivämäärävälille.
  Yrityksen yhteistä raporttipohjaa ei muuteta.
  Moduulin muuttamattomat yleiset MIS-oletussarakkeet käyttävät jatkossa 1, 3 tai
  12 kalenterikuukautta; omia mukautettuja sarakemäärityksiä ei korvata.
- Sulkemistilan ja sulkutositteen voi kirjata vain Sulje kausi -toiminnolla.
  Lähetyksen vahvistus ja jonon käsittely tarkistavat myös tositteen kelvollisuuden.
  Kirjanpito- tai ilmoitushistorian sisältävää kautta ei voi poistaa tai siirtää
  toisiin päivämääriin tai toiseen yritykseen myöskään sen tilikauden kautta.
- Tee ALV-ilmoitus näkyy vasta suljetulla kaudella. Vahvista lähetys piilotetaan,
  jos lähettämisen ehto ei täyty; esikatselu kertoo esteen. Muuttumatonta korjausta
  ei tarjota lähetettäväksi. Korjauksen aloitus tyhjentää vanhan vertailun.
- Lähetyshistorian laskupainikkeet näkyvät vain soveltuvissa ALV-lähetyksissä.
  EU-lähetyksillä niitä ei näytetä. Vanhan lähetyksen laskulinkki avaa siihen
  liittyvän laskun, ei myöhemmän korjauksen erillistä laskua.
  Kirjatun hyvityksen jälkeen uusi maksettavan veron lasku voidaan luoda myös,
  kun epäselvän lähetyksen vastaanotto on ensin vahvistettu käsin.

Riippuvuuden sulkupohjien yrityssääntö päivitetään vain, jos se vastaa tunnettua
vanhaa oletussääntöä. Ylläpitäjän mukauttamia sääntöjä ei korvata päivityksessä.
Päivitetty [käyttöohje](KAYTTOOHJE_FI.md) korvaa PDF-ohjeen näitä kohtia koskevat tiedot.

## ALV-kauden sulkemistila (18.0.1.8.0)

Suljettava ja Suljettu ovat vain tilatägejä. Sulje kausi näkyy, kun päättynyt kausi,
saman yrityksen aiemmat kaudet, sulkuasetukset, lukitukset ja käyttäjän oikeudet
sallivat sulkemisen. Muussa tapauksessa Sulkemisen lisätieto kertoo esteen.
Vanha Suljettu-painike ja kauden sulkemisen peruminen on estetty myös palvelinpuolella.
Sulkeminen käyttää kauden yritystä, säilyttää muut lukituspäivät ja estää toistuvan
sulkukirjauksen. Vero-ilmoituksen korjaus on edelleen erillinen toiminto.
KAYTTOOHJE_FI.md:n sulkemisohje korvaa vanhan PDF-ohjeen tämän osuuden.

## Erilliset ALV- ja EU-näkymät (18.0.1.7.0)

**ALV-kaudet ja ilmoitukset** säilyttää kausien sulkemisen, ALV-ilmoitukset ja
maksulaskut. **EU-yhteenvetoilmoitukset** näyttää yhden rivin kalenterikuukaudelle
ja Vero-yhteydelle. Valitse kuukausi -painike avaa yrityksen, yhteyden ja kuukauden
valinnan ilman ALV-kautta. Kuukausilla on omat määräpäivät, laskentatilat ja
lähetyshistoriat. Ei ilmoitettavaa myyntiä tarkoittaa viimeisimmän tarkistuksen
tulosta, ei Verohallinnon kuittausta. Kirjanpidon muuttuessa tiedot lasketaan uudelleen.

Nykyiset EU-ilmoitukset näkyvät uudessa listassa. Niiden ALV-kausilinkit säilyvät
historiatietona. Saman yhteyden saman kuukauden ilmoitusta käytetään uudelleen;
korjaukset ja jonossa olevien lähetysten estot säilyvät. Uusia tyhjiä kuukausirivejä
ei generoida automaattisesti: listalla näkyvät valmistellut kuukaudet.
Katso [päivitetty EU-työnkulku](KAYTTOOHJE_FI.md#11-eu-yhteenvetoilmoitus).
Se korvaa vanhan PDF-käyttöohjeen EU-ilmoituksen aloituskohdan.

## Automaattinen avainhallinta (18.0.1.6.0)

Uusi asennus luo tietokantakohtaisen salausavaimen automaattisesti. Vero-yhteyden
käyttöönotto ei vaadi SSH-yhteyttä, avaintiedostoa, ympäristömuuttujaa tai conf-muutosta.
Moduulin ja Python-riippuvuuksien asennus kuuluu edelleen ylläpitäjälle.
Puhtaassa tietokannassa perusta ensin yrityksen suomalainen tilikartta
Kirjanpidon käyttöönotossa. Nykyinen kausimoduuli tarvitsee sen tilit ja päiväkirjat
jo asennusvaiheessa. Asenna `account_vat_periods` vasta sen jälkeen.

1. Tilaa yrityksen testivarmenne tai tuotantovarmenne Verohallinnon varmennepalvelussa.
   Hanki ohjelmiston API-avain ohjelmistotoimittajalta; Sandbox käyttää tilausavainta.
2. Luo Odoossa Vero API -yhteys oikealle yritykselle ja valitse ympäristö.
3. Avaa **Avaimet ja varmenne** ja tallenna ohjelmiston API-avain.
4. Syötä tilatun varmenteen siirtotunnus ja kertakäyttösalasana, aloita nouto,
   nouda ja tarkista varmenne sekä ota se käyttöön. Sandbox ei tarvitse varmennetta.
5. Paina **Testaa API-yhteys**. Tämä kysyy kausitietoja, eikä lähetä veroilmoitusta.

Avain, tunnukset ja noudon tila sisältyvät tietokannan varmuuskopioon. Koko
tietokantakopion haltija voi purkaa tunnukset: suojaa varmuuskopiot sen mukaisesti.
Tavalliset Odoo-haut, viennit ja käyttöliittymä eivät paljasta tallennettuja avaimia.

Vanha ulkoista salausavainta käyttävä yhteys jatkaa ennallaan. Tekninen ylläpitäjä,
jolla on myös täydet kirjanpito-oikeudet, voi vaihtaa sen automaattiseen hallintaan
**Avaimet ja varmenne → Ylläpitäjä: palautus ja avainhallinta** -kohdassa.
Kirjoita yhteyden nimi, hyväksy seuraukset ja valitse **Ota automaattinen avainhallinta
käyttöön / palauta**. Jos palvelimen avain on kadonnut mutta alkuperäinen avain on
tallessa, sen voi syöttää suojattuun palautuskenttään. Varmenteen noutoa ei toisteta.

Samassa kohdassa voi nollata vain tämän yhteyden tunnukset erillisellä vahvistuksella.
Nollaus menettää myös keskeneräisen varmennehaun yksityisen avaimen ja tilan. Se ei
peruuta varmennetta tai aiempaa pyyntöä Verohallinnossa. Älä käytä kulutettuja
siirtotunnuksia uudelleen. Jonossa oleva tai epäselvä ilmoitus estää toimenpiteen.

Eri nimelle kopioidun/palautetun tai Odoon neutraloiman tietokannan tuotantoyhteydet
estetään. Testiyhteydet toimivat edelleen. Ylläpitäjä voi sallia tuotantoyhteydet
erikseen samassa näkymässä vain oikeassa tuotantotietokannassa. Samanniminen käsin
palautettu kopio on neutraloitava ylläpidossa ennen Odoon käynnistystä.

Vanhoja tiedostopohjaisia tunnuksia voi edelleen tuoda **Tuo olemassa olevat
tunnukset** -painikkeella. Uudessa tyhjässä tietokannassa tätä ei tarvita.

[Tekninen tallennus- ja palautusohje](docs/ENCRYPTED_CREDENTIALS.md).
Tämä osio korvaa vanhojen PDF-ohjeiden salausavaimen ja varmuuskopioinnin ohjeet.

## Riippuvuuksien versiotarkistus (18.0.1.4.2)

Moduulin asennus ja päivitys tarkistavat Python-kirjastojen tuetut versiot.
Sama tarkistus tehdään ennen varmenteen noutopyyntöä, vastauksen tarkistusta
ja käyttöönottoa. Virhe kertoo löytyneet versiot ja vaaditut versiorajat.
Väärillä kirjastoilla kertakäyttötunnuksia ei lähetetä eikä uutta avainta luoda.
Jo käytössä olevan asennuksen avainnäkymä näyttää ohjeen tilassa
**Vaatii selvitystä**; nykyinen noutopyyntö ja tiedostot säilytetään.

Ylläpitäjä asentaa riippuvuudet Odoon käyttämään Python-ympäristöön:

```sh
/path/to/odoo-venv/bin/python -m pip install -r /path/to/account_vat_periods/requirements-vero.txt
/path/to/odoo-venv/bin/python -m pip check
```

Polut korvataan oman asennuksen poluilla. Selvitä mahdolliset muiden moduulien
riippuvuusristiriidat, käynnistä Odoo uudelleen ja jatka alkuperäistä noutoa
**Päivitä tila** -painikkeella. Kirjastoja ei asenneta tai päivitetä automaattisesti.
Tuetut versiorajat ovat `requirements-vero.txt`-tiedostossa; ne rajaavat
tuetut kirjastosukupolvet, eivät edellytä täsmälleen yhtä korjausversiota.

## Yhteyden käyttöönoton parannukset (18.0.1.4.1)

SAT API -perusosoite täyttyy automaattisesti uutta yhteyttä luotaessa ja
ympäristöä vaihdettaessa. Olemassa olevia osoitteita ei muuteta päivityksessä.

| Ympäristö | Perusosoite |
| --- | --- |
| Sandbox | `https://api-sandbox.vero.fi/Return/SAT` |
| Testivarmenne | `https://apitest.vero.fi/FIS/Return/SAT/Test` |
| Tuotanto | `https://api.vero.fi/Return/SAT` |

Varmenteen nouto käyttää erillistä automaattista osoitetta. Jos tallennetun
varmennepalveluvastauksen tarkistus epäonnistuu, **Avaimet ja varmenne** näyttää
tilan **Vaatii selvitystä**. Avaimen hallinta ja paluu yhteyden asetuksiin
toimivat edelleen. Säilytä yhteys ja noutotiedostot; älä aloita uutta pyyntöä
samoilla kertakäyttötunnuksilla. Ylläpitäjän selvitettyä virheen **Päivitä tila**
tarkistaa tallennetun vastauksen uudelleen lähettämättä alkuperäistä pyyntöä
uudestaan. Virheellistä allekirjoitusta ei hyväksytä eikä varmennetta aktivoida.

## Kielet ja kenttäohjeet (18.0.1.4.0)

Python-, JavaScript- ja XML-lähteiden käyttöliittymätekstit ovat englanniksi.
Suomenkielinen käyttöliittymä valitaan Odoo-käyttäjän kieliasetuksella;
`i18n/fi.po` kattaa moduulin kenttien nimet, ohjetekstit, valinnat, näkymät
ja ilmoitukset. Kaikilla 92 uudella Vero-kentällä on yksityiskohtainen
ohjeteksti. Avaimen ja varmenteen syöttönäkymässä on lisäksi kysymysmerkit.
Rajapinnan alkuperäisiä vastauksia ja historiallisia lähetyssisältöjä ei muuteta.
MIS-raportin olemassa olevat tekniset rivitunnisteet säilyvät yhteensopivina.

Käännöstestit tarkistavat kenttien nimet ja ohjeet, selainkäännökset,
virheilmoitukset sekä tilatekstien päivittymisen käyttäjän kielen mukaan.

## Ilmoitusten tila ja kaksoislähetyksen esto (18.0.1.3.0)

ALV-kausilista näyttää ALV-ilmoitukset; EU-kuukaudet näkyvät omassa EU-listassaan.
Rivin toiminto avaa olemassa olevan lähetyksen tilan. Vastaanotetun ilmoituksen
korjaus aloitetaan erikseen; jonossa, lähetyksessä tai epäselvänä oleva ilmoitus
estää uuden esikatselun ja lähetyksen. ALV-yhteyden voi valita kausilistan
vaihtonuolikuvakkeesta. EU-kuukausi valitaan EU-listan Valitse kuukausi -painikkeesta. Useiden ilmoitusten tiloja ei yhdistetä yhdeksi
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

Palvelinriippuvuudet: PostgreSQL, OpenSSL 3 -komentorivityökalu ja `requirements-vero.txt`-tiedoston
Python-riippuvuudet. Kehitysympäristössä testattu:
signxml 4.5.1, cryptography 46.0.7, pyOpenSSL 25.3.0, lxml 5.2.1.
Tarkista muun Odoo-asennuksen riippuvuudet ja aja `pip check` päivityksen yhteydessä.
Moduulin päivitys ja palvelun restart tarvitaan kerran; myöhemmät avainvaihdot
ja noudot eivät vaadi restartia.

Salaisuudet ovat salattuina tietokannassa. Varmuuskopioi tietokanta ja erikseen
mahdollinen ulkoinen pääsalausavain; säilytä vanhat avaintiedostot siirron tarkistukseen asti. HTTP-reitti käyttää kirjautumista, CSRF-tarkistusta,
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
   API-perusosoite täyttyy automaattisesti. Osoitteen voi korjata, jos kaikki
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
   Odoo tallentaa tunnukset salattuina tietokantaan. Vanhat palvelinpolut ovat vain tuontia varten.
6. Tarkista automaattisesti täyttyvä ympäristön SAT API:n perusosoite. Sallittuja palvelimia
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
EU-yhteenvetoilmoitukset-valikon Valitse kuukausi -painike avaa itsenäisen
kuukausivalinnan. Se ei vaadi ALV-kauden luomista, sulkemista tai ALV-ilmoituksen
lähettämistä. Laskenta ei tarvitse API-varmennetta.

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
verotuspäätöstä. Testi/tuotanto näkyy erikseen. EU-kuukauden tila koskee kyseistä
kuukautta: se ei väitä, että kaikki vuosineljänneksen kuukaudet on annettu.
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
