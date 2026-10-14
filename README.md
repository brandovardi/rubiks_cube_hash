# RubikSponge4x4

**Prototipo sperimentale di funzione hash ispirata al gruppo di permutazioni del cubo di Rubik 4×4×4**

## 1. Obiettivo e idea

L'obiettivo del progetto è esplorare come le permutazioni associate alle mosse di un cubo di Rubik 4×4×4 possano essere utilizzate per costruire una funzione hash sperimentale.

L'idea non è cifrare il messaggio con una sequenza di mosse reversibili. Il cubo fornisce invece una rappresentazione degli elementi dello stato interno: ogni stato è una permutazione dei 96 sticker superficiali. Su questa rappresentazione sono costruite una funzione di assorbimento, una trasformazione interna a round e una fase di estrazione del digest.

La funzione accetta messaggi di lunghezza arbitraria e restituisce un digest di 256 bit, rappresentato da 64 caratteri esadecimali. La costruzione prende ispirazione dal modello *sponge*, ma è personalizzata: lo stato è formato da tre permutazioni di sticker e l'output è prodotto da una funzione di proiezione ad hoc. **Non è quindi una sponge standard e non eredita automaticamente le garanzie teoriche di SHA-3/Keccak.**

Il progetto è pensato per studiare proprietà matematiche e sperimentali, per esempio l'invertibilità dei round, la propagazione delle differenze e il comportamento statistico dell'output.

## 2. Struttura del progetto

Il file principale è `rubik_sponge.py`, che contiene la primitiva geometrica e la funzione hash:

- `Rubik4x4Primitive`: rappresentazione del cubo e costruzione delle mosse;
- `FixedRNG`: generatore deterministico usato per ottenere parametri riproducibili;
- `RubikSponge4x4`: token dei blocchi, parametri della permutazione, assorbimento e squeeze;
- test incorporati: correttezza delle mosse, orientamento, token, invertibilità e alcuni test dell'hash.

Le suite ausiliarie citate in questo README sono script separati. Devono essere presenti nella stessa cartella (o richiamati tramif (!((a + ~b + 1) & (1 << ((sizeof(a) << 3) - 1))) && (a ^ b))ite il loro percorso) per poter eseguire i comandi riportati.

## 3. Rappresentazione del cubo e mosse

### 3.1 I 96 sticker

Un cubo 4×4×4 ha 6 facce con 16 sticker ciascuna, per un totale di 96 sticker. Ogni sticker è rappresentato da una coppia:

- posizione tridimensionale `(x, y, z)`;
- normale tridimensionale `(nx, ny, nz)`.

La posizione identifica dove si trova lo sticker; la normale identifica la direzione verso cui è rivolto. La coppia permette di identificare in modo univoco uno sticker della superficie.

Le coordinate utilizzate sono `(-3, -1, 1, 3)`. Le definizioni delle sei facce specificano la normale uscente e gli assi locali `right` e `down`, così l'orientamento delle rotazioni è definito geometricamente.

### 3.2 Tabelle di permutazione

Una mossa è rappresentata da una permutazione degli indici da 0 a 95. Il codice usa la convenzione `new[i] = old[p[i]]`. Le tabelle vengono generate ruotando di 90 gradi le coordinate degli sticker interessati, invece di codificare manualmente gli scambi fra sticker.

Per ciascuna faccia (`U`, `R`, `F`, `D`, `L`, `B`) sono create sei varianti:

- mossa esterna;
- inversa;
- rotazione di 180°;
- *wide move* (strato esterno e strato interno adiacente);
- inversa della wide move;
- wide move di 180°.

Sono quindi disponibili 36 voci di mosse. Le rotazioni, le inverse e le potenze sono testate per verificare che siano permutazioni valide e che le relazioni elementari previste siano rispettate. La convenzione `clockwise` viene verificata rispetto alla vista dall'esterno della faccia.

## 4. Generazione deterministica dei parametri

Il progetto genera token, costanti, parole di round e stato iniziale (IV) in modo riproducibile. `FixedRNG` è un generatore deterministico a 64 bit ispirato a SplitMix64; non è un generatore crittografico e non viene usato per creare segreti.

I parametri sono pubblici e deterministici. La riproducibilità è utile per poter ricreare gli stessi esperimenti su macchine diverse, ma non costituisce una proprietà di sicurezza.

### 4.1 Token dei blocchi

Il messaggio, dopo la codifica e il padding, è diviso in blocchi da 12 bit. Esistono quindi `2^12 = 4096` valori possibili. Ogni valore viene associato a un elemento del gruppo del cubo, ottenuto componendo mosse generate deterministicamente.

Durante la costruzione viene mantenuto un insieme degli elementi già usati: i duplicati e l'identità vengono esclusi. I test hanno verificato che tutti i 4096 token siano distinti.

Questa unicità riguarda la tabella di codifica dei blocchi. **Non implica che messaggi diversi debbano necessariamente produrre digest diversi**, né dimostra la resistenza alle collisioni della funzione hash.

## 5. Stato interno e funzione di round

Lo stato è composto da tre registri:

- `A`, che viene usato per assorbire i blocchi e per produrre l'output;
- `B` e `C`, che contribuiscono all'evoluzione dello stato interno.

Ogni registro contiene una permutazione di 96 elementi. Nel codice la costruzione è descritta intuitivamente come `A = rate` e `B,C = capacity`, ma questa terminologia non corrisponde alla partizione in bit `rate/capacity` di una sponge standard: qui i registri sono elementi del gruppo di permutazioni.

Per ciascuno dei 24 round sono generati:

- tre costanti di registro, `round_A`, `round_B` e `round_C`;
- 13 costanti di gruppo per la parola di round;
- una parola di 12 operazioni costruita con `X`, `Y`, `X^-1` e `Y^-1`.

La funzione `_round_function(X, Y, r)` compone in ordine le operazioni della parola e le costanti associate al round. La funzione non deve essere invertibile: l'invertibilità del round completo deriva dalla struttura a tre registri.

Il round è definito dalle relazioni:

```text
A' = B * K_A
B' = C * K_B
C' = A * F(B, C) * K_C
```

La routine `_permute_inverse()` ricostruisce i registri nel verso opposto e percorre i round in ordine inverso. I test hanno verificato il round trip su diversi stati generati deterministicamente. Questo verifica la correttezza dell'inversa nei casi provati, non la sicurezza crittografica della trasformazione.

## 6. Padding, assorbimento e output

### 6.1 Codifica e padding

Le stringhe Python vengono codificate in UTF-8; sono accettati anche `bytes` e `bytearray` (convertito in `bytes`). Il messaggio viene trasformato in una sequenza di bit. Al contenuto viene aggiunto il suffisso di dominio personalizzato `01`, seguito dal padding con bit `1`, zeri e bit finale `1`, fino a ottenere una lunghezza multipla di 12 bit.

Il padding è una scelta specifica di questo prototipo e non è il padding di SHA-256 o SHA-3. Le prove ausiliarie hanno verificato la validità del formato e l'unicità delle codifiche su un insieme di lunghezze e, in modo esaustivo, su tutti i messaggi da due byte.

### 6.2 Assorbimento

Per ogni blocco da 12 bit:

1. il blocco viene convertito in un intero tra 0 e 4095;
2. l'intero seleziona il token corrispondente;
3. il token viene composto con lo stato `A`;
4. viene applicata la permutazione interna di 24 round.

### 6.3 Squeeze e digest

La funzione `_read_rate128()` comprime la permutazione contenuta in `A` in un valore di 128 bit, mediante una funzione di mixing a 64 bit applicata ai 96 indici della permutazione. La prima metà del digest è letta da `A`; in seguito viene applicata un'altra permutazione interna e viene estratta la seconda metà.

Le due metà vengono concatenate per ottenere 256 bit, formattati come 64 cifre esadecimali.

La proiezione `_read_rate128()` è una componente personalizzata e non ha una dimostrazione nota di resistenza alle collisioni. Anche una buona distribuzione statistica osservata nei campioni non ne prova la sicurezza.

## 7. Come usare il prototipo

È richiesta una versione di Python compatibile con le annotazioni di tipo moderne usate dal codice (Python 3.10 o successivo consigliato). Non sono necessarie librerie esterne per l'implementazione principale.

Esempio minimale:

```python
from rubik_sponge import RubikSponge4x4

hasher = RubikSponge4x4()
digest = hasher.hash("ciao")
print(digest)                 # 64 caratteri esadecimali
print(len(digest) * 4)        # 256 bit
```

La funzione `hash()` resetta lo stato all'inizio di ogni chiamata, così la stessa istanza può essere riutilizzata senza che una chiamata precedente influisca sul risultato successivo. I test hanno controllato anche la coerenza tra `str`, `bytes` e `bytearray` per contenuti equivalenti.
