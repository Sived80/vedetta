# Vedetta

Vedetta trova i dispositivi della rete locale, li riconosce (nome, marca, categoria), ne segue presenza e
latenza e li mostra in una pagina nella barra laterale di Home Assistant (ingress: nessuna porta da aprire).
Tutto resta in casa: nessun dato viene inviato fuori dalla rete.

## Come si usa

- **Ricerca** (lente): trova gli indirizzi IP e MAC presenti. Si scelgono i dispositivi da aggiungere alla plancia.
- **Scheda del dispositivo**: IP, MAC, tempo di risposta e porte sono sempre visibili; "Altri attributi" apre il
  resto (marca, tipo, area...). Marca e tipo si possono scegliere a mano e non vengono più cambiati. Il
  pulsante **Condividi con HA** mostra il dispositivo in Home Assistant (vedi sotto).
- **Flussi di ricerca** (menu): quali metodi usano le tre ricerche (iniziale, associativa, approfondita). Il
  pallino indica il rischio: verde non invasivo, arancione invasivo, rosso rischioso.
- **Esporta per l'analisi** (menu, voce discreta): crea un file zip con configurazione, storico e il motivo di
  nome, marca e categoria di ogni dispositivo. Le password sono escluse e il file non viene inviato da nessuna parte.
- **Modalità debug**: 3 tocchi consecutivi sul titolo della card in alto (o Ctrl+Maiusc+D). Un distintivo
  arancione DEBUG resta visibile finché è attiva; la scheda mostra indizi, punteggi e fonti di nome e marca.

## Opzioni

- `language`: lingua predefinita (`en` o `it`); ogni browser può sceglierne un'altra.
- `log_level`: `debug`, `info`, `warning`, `error`.
- `interface`: interfaccia di rete da scansionare (vuoto = automatica, es. `enp0s18`).
- `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password`: broker MQTT manuale. Se vuoti si usa il servizio
  MQTT di Home Assistant (app Mosquitto), se presente.

## Permessi e cosa fa con ciascuno

| Permesso | A cosa serve |
|---|---|
| Rete dell'host (`host_network`) e `NET_ADMIN`/`NET_RAW` | `arp-scan`, `nmap`, ping, SSDP/mDNS e ascolto DHCP passivo (porta UDP 67). Solo richieste locali, mai verso Internet (salvo l'aggiornamento periodico dei prefissi MAC e il controllo dell'IP pubblico dal pannello della rete). |
| `homeassistant_api` | **Sola lettura** dei registri di Home Assistant (dispositivi, entità, aree, integrazioni) per dare nome, marca, modello, area e categoria ai dispositivi. Non scrive e non chiama servizi. Si può spegnere dai flussi di ricerca (passo "Dati di Home Assistant"). |
| Servizio MQTT (`mqtt:want`) | Pubblica verso HA solo ciò che si sceglie di condividere. |
| Ingress | L'interfaccia accetta connessioni solo dal Supervisor. |

## Condivisione con Home Assistant (MQTT)

Per impostazione predefinita Home Assistant vede un solo dispositivo, **Vedetta**, con i contatori (online,
offline, mobili, nuovi, latenza media) e il pulsante "Scansiona ora". Ogni dispositivo di rete compare in HA
solo se premi **Condividi con HA** nella sua scheda: diventa un sotto-dispositivo di Vedetta con tracker,
connettività e latenza, senza unirsi al dispositivo vero eventualmente già presente in HA. **Rimuovi da HA** lo
toglie. Disponibilità su `vedetta/status`.

## Come riconosce i dispositivi

Ogni fonte propone un nome o un indizio e vince la più affidabile; un nome scelto a mano non si cambia mai.
Le fonti sono: HA (nome scelto in HA), API del dispositivo, mDNS/Bonjour (con memoria e ascolto continuo),
UPnP, DHCP (nome e classe), NetBIOS, certificato TLS, pagina web, ruolo di rete. La categoria somma indizi
per famiglia (lo stesso fatto non conta due volte) e usa un catalogo di firme dei prodotti
(`app/data/signatures.json`) dove i segnali generici sono ambigui. Se due categorie sono alla pari con indizi
deboli il dispositivo resta in "Altri dispositivi".

## Dati e backup

I dati stanno in `/data` (dispositivi, impostazioni, memoria DHCP e mDNS, storico, registro) ed entrano nei
backup di Home Assistant. **Disinstallare l'app cancella `/data`**: prima si può usare "Esporta per l'analisi".

## Limiti noti

- I dispositivi con indirizzo MAC privato (iPhone/iPad) non annunciano sempre il nome: restano "marca mobile"
  finché un nome non arriva da Bonjour, DHCP, HA o dalla scelta a mano.
- Un dispositivo lento (es. console) viene analizzato con le porte mirate e, in seconda battuta, in background.
- Le scansioni approfondite usano CPU: sulle macchine piccole conviene evitarle in contemporanea con carichi pesanti.
