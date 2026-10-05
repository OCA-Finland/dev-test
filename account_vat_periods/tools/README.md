# Testivarmenteen noutotyökalu

`vero_test_certificate.py` on ylläpitäjän Linux-komentorivityökalu. Se noutaa
aiemmin tilatun Vero API -testivarmenteen PKI-rajapinnasta. Se ei tilaa varmennetta,
rekisteröi ohjelmistoa eikä tue tuotantovarmenteita tai automaattista uusimista.
Odoo käyttää noudettua PEM-varmennetta nykyisillä tiedostopolkuasetuksillaan.
Versiosta 18.0.1.2.0 alkaen moduulissa on myös **Avaimet ja varmenne** -näkymä,
joka on ensisijainen käyttäjän käyttöönottoon ja tukee testi- ja tuotantovarmenteita.
Se käyttää erillistä `vero_credentials.py`-palvelua, joka tarkistaa myös
XML-allekirjoituksen ja koko CA-ketjun. Alla kuvattu vanha komentorivityökalu
säilyy vain testivarmenteen ylläpitokäyttöön omine rajoituksineen.

Aja työkalu Odoo-palvelimella Odoon palvelukäyttäjänä käyttäen Python-ympäristöä,
jossa ovat `requests` ja `cryptography >= 42`. Hakemiston tulee olla palvelukäyttäjän
omistama, oikeuksilla 0700, ja lähdekoodihakemiston ulkopuolella.

1. `python vero_test_certificate.py prepare --directory /absolute/private/directory --customer-id TESTI-Y-TUNNUS --customer-name 'Testiorganisaation nimi'`
2. Tallenna samaan suojattuun hakemistoon `credentials.json`, jonka avaimet ovat
   `customer_id`, `transfer_id` ja `transfer_password`. Käytä saamiasi arvoja;
   älä anna salaisuuksia komentorivin argumentteina. Tiedoston oikeudet: 0600.
3. `python vero_test_certificate.py submit --directory /absolute/private/directory --credentials-file /absolute/private/directory/credentials.json`
4. Odota vähintään 30 sekuntia.
5. `python vero_test_certificate.py retrieve --directory /absolute/private/directory`
6. Tarkista myös varmenneketju Verohallinnon virallisella testivarmenteiden
   CA-paketilla ennen käyttöönottoa. Työkalu tarkistaa HTTPS-palvelimen,
   varmenteen ja yksityisen avaimen vastaavuuden, asiakkaan tunnisteen,
   voimassaolon sekä odotetun testijulkaisijan nimen. Se ei itse tarkista
   XML-vastauksen allekirjoitusta eikä asiakkaan varmenteen koko CA-ketjua.
7. Määritä Odoon Test certificate -yhteyteen `certificate.pem` ja
   `private-key.pem` sekä erillinen ohjelmistoavaimen tiedostopolku.
   Poista käytetty noutotunnustiedosto onnistuneen noudon jälkeen.

`status` näyttää noudon vaiheen paljastamatta salaisuuksia. Suojattu hakemisto
sisältää myös CSR:n ja vastaukset vikatilanteiden selvittämiseen. Varmuuskopioi
varmenne ja yksityinen avain turvallisesti. Avainta ei voi palauttaa
Verohallinnolta.

## Keskeytyminen

Työkalu estää rinnakkaisen ajon hakemistokohtaisella lukolla. `submit` merkitsee
kertakäyttöisten tunnusten käyttöyrityksen levylle ennen verkkokutsua. Samaa
pyyntöä ei lähetetä automaattisesti uudelleen. Aikakatkaisun jälkeen älä poista
`submit-started.json`-tiedostoa tai generoi korvaavaa avainta sokkona.

Jos `submit-response.xml` on tallessa, siitä voidaan tarkistaa onnistuminen ja
palauttaa noutotunnus. Jos onnistumisesta ei ole tietoa, tilanne on selvitettävä
ennen uutta yritystä. `retrieve` voidaan toistaa samalla noutotunnuksella;
onnistuneesti tallennettua varmennetta ei kuitenkaan kirjoiteta yli.

## Testit ja rajaukset

`python -m unittest discover -s tools -p test_vero_test_certificate.py -v`

Testit kattavat mm. avaimen säilymisen, aikakatkaisun jälkeisen
uudelleenlähetyksen eston, tunnisteiden ristiriidan ja väärän varmenteen hylkäyksen.
Julkinen PKI-testipenkki on eri palvelu kuin varsinaisen testivarmenteen nouto;
sen vakiona palautuva varmenne ei vastaa itse luotua avainta eikä kelpaa Vero APIin.

Viralliset ohjeet:
- https://www.vero.fi/tietoa-verohallinnosta/kehittaja/varmennepalvelu/varmenteen-noutaminen/
- https://www.vero.fi/tietoa-verohallinnosta/kehittaja/varmennepalvelu/dokumentaatio/
