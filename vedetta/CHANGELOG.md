# Changelog

## 0.3.1
- Ricerca approfondita: nel menu accanto a "Scan network" c'e' una seconda voce, "solo mancanti", che analizza a fondo soltanto i dispositivi mai analizzati (quelli senza data di "Ultima ricerca approfondita"). Con tutti gia' analizzati la voce e' disattivata.

## 0.3.0
- Riconoscimento piu' solido: gli indizi si sommano per famiglia (lo stesso fatto, come Cast, conta una volta), le porte hanno un tetto, due categorie alla pari con indizi deboli restano "Altri dispositivi".
- Catalogo di firme dei prodotti (`app/data/signatures.json`): il modello dichiarato decide dove i segnali generici sono ambigui (Google Home e Chromecast, Fire TV, PlayStation, Proxmox...).
- Modalita' debug: elenco degli indizi con famiglia e punti; documentazione dell'app aggiornata.

## 0.2.1
- Memoria dei nomi Bonjour (mDNS) per MAC e ascolto continuo degli annunci: i telefoni che dormono (iPhone con indirizzo privato) non perdono il nome una volta visto.
- Titoli di pagina che sono il nome di un software con la versione non diventano il nome del dispositivo; la classe DHCP dichiarata (es. PS3) vale come indizio di tipo e marca; console tra i tipi.

## 0.2.0
- Dati di Home Assistant (registro dispositivi, sola lettura) come fonte di nome, marca, modello, area e categoria; passo "Dati di Home Assistant" nei flussi di ricerca. Richiede il permesso `homeassistant_api`.
- Condivisione con HA a scelta: nella scheda di ogni dispositivo "Condividi con HA" / "Rimuovi da HA". In HA compare il dispositivo "Vedetta" con i dispositivi condivisi come sotto-dispositivi, senza unirsi a quelli esistenti.
- Categorie ridotte a 9; nomi dal ruolo di rete (Server DNS, Ripetitore...), segnaposto riconosciuti, marca e tipo modificabili a mano.
- Scheda: attributi fissi e tendina "Altri attributi"; modalita' debug (3 tocchi sul titolo) ed esportazione per l'analisi.
- Rimossa la pagina classica: resta solo la dashboard `/ha` in ingress.

## 0.1.0
- Prima versione come app di Home Assistant: ingress, dati in /data, discovery MQTT.
