# ============================================================
# RubikSponge4x4 - versione 3 rivista
# ============================================================
# Prototipo sperimentale di una funzione hash "sponge" costruita
# a partire dal gruppo di permutazioni del cubo di Rubik 4x4x4.
#
# OBIETTIVI DELLA REVISIONE
# -------------------------
# 1. Generazione geometrica delle mosse:
#    le mosse sono ottenute da coordinate 3D del cubo, invece di
#    usare manualmente tabelle di scambio per bordi/facce.
#
# 2. Convenzione geometrica coerente:
#    una rotazione "clockwise" significa davvero oraria quando
#    la faccia viene osservata dall'esterno.
#
# 3. Assorbimento senza collisioni locali:
#    ogni blocco da 12 bit (4096 valori) viene associato a un
#    elemento del gruppo distinto.
#
# 4. Stato interno più adatto a una sponge:
#       A = rate
#       B,C = capacity
#    quindi due cubi completi sono dedicati alla capacità.
#
# 5. Permutazione interna realmente invertibile:
#    usiamo un round a 3 registri in stile Feistel generalizzato.
#
# 6. Squeeze separato dall'absorb:
#    128 bit + permutazione + 128 bit = 256 bit.
#
# NOTA CRITTOGRAFICA
# -------------------
# Questa è una costruzione sperimentale/didattica.
# Non è SHA-3, non è standardizzata e non esiste una dimostrazione
# che abbia 128 bit di collision resistance o 256 bit di preimage
# resistance. Per uso reale bisogna usare SHA-256/SHA3-256 o altro
# standard analizzato pubblicamente.
# ============================================================

from __future__ import annotations

import random


# ============================================================
# PRNG DETERMINISTICO PER I PARAMETRI PUBBLICI
# ============================================================
# Qui NON serve casualità crittografica.
# Vogliamo solo generare in maniera riproducibile token,
# costanti di round e parole usate dalla funzione di round.
# ============================================================

# Un PRNG deterministico a 64 bit con periodo 2^64.
# Serve per generare in maniera riproducibile i parametri pubblici
# e le costanti di round.
# Per non usare il modulo random di Python, che non è deterministico tra versioni, e per non usare librerie esterne.
class FixedRNG:
    # creo un PRNG deterministico a 64 bit con periodo 2^64.
    # MASK = 0xFFFFFFFFFFFFFFFF, serve per limitare lo stato a 64 bit.
    # come se fosse un uint64_t in C
    MASK = (1 << 64) - 1

    def __init__(self, seed: int):
        # Lo stato interno è un intero a 64 bit.
        self.state = seed & self.MASK

    def next_u64(self) -> int:
        """Restituisce il prossimo valore deterministico a 64 bit."""
        # La funzione di generazione è una variante di SplitMix64 (https://rosettacode.org/wiki/Pseudo-random_numbers/Splitmix64)
        # https://prng.di.unimi.it/splitmix64.c
        self.state = (self.state + 0x9E3779B97F4A7C15) & self.MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & self.MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & self.MASK
        return (z ^ (z >> 31)) & self.MASK

    def randbelow(self, n: int) -> int:
        """Versione semplice e deterministica di randint(0, n-1)."""
        if n <= 0:
            raise ValueError("n must be positive")
        return self.next_u64() % n


# ============================================================
# LIVELLO PRIMITIVO: CUBO 4x4x4
# ============================================================
# Un cubo 4x4 ha 6 * 16 = 96 sticker.
# Ogni sticker e' descritto da una coppia:
#     (posizione 3D, normale 3D)
#
# Questa rappresentazione e' piu' robusta delle LUT costruite
# manualmente riga per riga: la rotazione di una faccia viene
# ottenuta applicando una vera rotazione 3D di 90 gradi.
# ============================================================

class Rubik4x4Primitive:
    SIZE = 4
    # Coordinate dei 4 sticker lungo un asse, centrati in 0.
    COORDS = (-3, -1, 1, 3)

    # Per ogni faccia:
    #   normal = normale uscente
    #   right  = destra vista dalla faccia
    #   down   = basso visto dalla faccia
    #
    # Con questa convenzione, -90 gradi attorno alla normale
    # uscente e' una rotazione oraria vista dall'esterno.
    FACE_DEFS = {
        "U": {"normal": (0, 1, 0), "right": (1, 0, 0),  "down": (0, 0, 1)},
        "D": {"normal": (0, -1, 0), "right": (1, 0, 0), "down": (0, 0, -1)},
        "F": {"normal": (0, 0, 1), "right": (1, 0, 0),  "down": (0, -1, 0)},
        "B": {"normal": (0, 0, -1), "right": (-1, 0, 0), "down": (0, -1, 0)},
        "R": {"normal": (1, 0, 0), "right": (0, 0, -1), "down": (0, -1, 0)},
        "L": {"normal": (-1, 0, 0), "right": (0, 0, 1), "down": (0, -1, 0)},
    }

    # Convenzione per l'ordine delle facce da usare nelle mosse e nella costruzione dei token.
    FACE_ORDER = ("U", "R", "F", "D", "L", "B")

    @staticmethod
    def _compose(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[int, ...]:
        # Con la convenzione new[i] = old[p[i]],
        # compose(a, b) rappresenta a seguito da b.
        return tuple(a[b[i]] for i in range(96))

    @staticmethod
    def _inverse(p: tuple[int, ...]) -> tuple[int, ...]:
        inv = [0] * 96
        for i, x in enumerate(p):
            inv[x] = i
        return tuple(inv)

    @staticmethod
    def _rotate_vector(v: tuple[int, int, int], axis: int, quarter_turns: int) -> tuple[int, int, int]:
        # Rotazione di un vettore di multipli di 90 gradi.
        x, y, z = v
        q = quarter_turns % 4
        if q == 0:
            return x, y, z
        if axis == 0:
            if q == 1:
                return x, -z, y
            if q == 2:
                return x, -y, -z
            return x, z, -y
        if axis == 1:
            if q == 1:
                return z, y, -x
            if q == 2:
                return -x, y, -z
            return -z, y, x
        if axis == 2:
            if q == 1:
                return -y, x, z
            if q == 2:
                return -x, -y, z
            return y, -x, z
        raise ValueError("axis must be 0, 1 or 2")

    def __init__(self):
        # Il cubo risolto e' la permutazione identita'.
        self.identity = tuple(range(96))

        # (posizione, normale) -> indice sticker
        self._sticker_to_index = {}

        # indice sticker -> (posizione, normale)
        self._index_to_sticker = []

        self._build_sticker_geometry()
        self.moves = self._build_moves()

    def _build_sticker_geometry(self) -> None:
        # Costruisce i 96 sticker della superficie del cubo.
        index = 0

        for face in self.FACE_ORDER:
            definition = self.FACE_DEFS[face]
            normal = definition["normal"]
            right = definition["right"]
            down = definition["down"]

            # u: sinistra -> destra
            # v: alto -> basso
            for v in self.COORDS:
                for u in self.COORDS:
                    # Calcola la posizione 3D dello sticker.
                    position = (
                        3 * normal[0] + u * right[0] + v * down[0],
                        3 * normal[1] + u * right[1] + v * down[1],
                        3 * normal[2] + u * right[2] + v * down[2],
                    )
                    key = (position, normal)
                    if key in self._sticker_to_index:
                        raise RuntimeError("duplicate sticker geometry")
                    self._sticker_to_index[key] = index
                    self._index_to_sticker.append((position, normal))
                    index += 1

        if index != 96:
            raise RuntimeError("a 4x4 cube must contain exactly 96 stickers")

    def _build_layer_move(self, face: str, layers: int = 1) -> tuple[int, ...]:
        """
        Costruisce una rotazione della faccia indicata.

        layers=1: solo strato esterno.
        layers=2: wide move (esterno + strato adiacente).
        """
        if layers not in (1, 2):
            raise ValueError("only 1 or 2 layers are supported")

        definition = self.FACE_DEFS[face]
        normal = definition["normal"]
        # Determina l'asse di rotazione e il verso della rotazione. Può essere 0, 1 o 2 per x, y, z.
        axis = next(i for i, value in enumerate(normal) if value != 0)
        # Determina il verso della rotazione: -1 o +1. (orario o antiorario)
        sign = normal[axis]

        # Coordinate target per selezionare gli sticker da ruotare.
        target_coordinates = {3 * sign}
        # Se layers=2, includiamo anche lo strato adiacente.
        if layers == 2:
            target_coordinates.add(sign)

        # -90 gradi rispetto alla normale uscente = clockwise.
        quarter_turns = -sign

        # LUT: destinazione <- sorgente.
        lut = list(self.identity)

        for old_index, (position, sticker_normal) in enumerate(self._index_to_sticker):
            if position[axis] not in target_coordinates:
                continue

            new_position = self._rotate_vector(position, axis, quarter_turns)
            new_normal = self._rotate_vector(sticker_normal, axis, quarter_turns)
            key = (new_position, new_normal)

            try:
                new_index = self._sticker_to_index[key]
            except KeyError as exc:
                raise RuntimeError(f"invalid cube geometry after {face} rotation") from exc

            lut[new_index] = old_index

        return tuple(lut)

    def _build_moves(self) -> dict[str, tuple[int, ...]]:
        # Per la costruzione crittografica usiamo:
        #   - le sei mosse di faccia
        #   - le loro inverse
        #   - i 180 gradi
        #   - le corrispondenti wide moves
        #   - le inverse wide
        #   - i 180 gradi wide
        #
        # In questo modo la primitiva può sfruttare anche gli strati interni
        # del 4x4 e non è limitata al sottogruppo generato dalle sole mosse esterne.
        """
        Costruisce le mosse fondamentali del 4x4.

        Per ogni faccia costruiamo:

            X      = outer move
            X'     = inverse
            X2     = 180°

            Xw     = wide move
            Xw'    = inverse wide move
            Xw2    = 180° wide move

        Sul 4x4 una wide move coinvolge:
            - lo strato esterno
            - lo strato interno adiacente

        Esempio:
            R  -> x = +3
            Rw -> x = +3 e x = +1
        """
        moves = {}

        for face in self.FACE_ORDER:

            # --------------------------------------------------------
            # OUTER MOVE
            # --------------------------------------------------------

            base = self._build_layer_move(face, layers=1)

            moves[face] = base
            moves[face + "'"] = self._inverse(base)
            moves[face + "2"] = self._compose(base, base)

            # --------------------------------------------------------
            # WIDE MOVE
            # --------------------------------------------------------

            wide = self._build_layer_move(face, layers=2)

            moves[face + "w"] = wide
            moves[face + "w'"] = self._inverse(wide)
            moves[face + "w2"] = self._compose(wide, wide)

        return moves


# ============================================================
# RUBIK SPONGE
# ============================================================

class RubikSponge4x4:
    """
    Costruzione sponge sperimentale basata sul gruppo del 4x4.

    Stato interno:
        A = rate
        B,C = capacity

    Questa scelta separa la parte usata per input/output dalle due
    componenti che mantengono lo stato interno.
    """

    # Blocco da 12 bit = 4096 token distinti. Che rappresentano elementi distinti del gruppo.
    # Usiamo blocchi da 12 bit invece di 8 bit per evitare collisioni locali durante l'assorbimento.
    BLOCK_BITS = 12
    TOKEN_COUNT = 1 << BLOCK_BITS  # 4096

    # Output da 256 bit, con squeeze in due fasi da 128 bit.
    OUTPUT_BITS = 256
    # Output da 128 bit per fase di squeeze.
    RATE_OUTPUT_BITS = 128
    # Numero di round della permutazione interna.
    ROUNDS = 24
    # Lunghezza della word di gruppo usata nella funzione di round.
    ROUND_WORD_LENGTH = 12

    # Suffisso di domain separation per questa specifica variante.
    # Serve a distinguere questa costruzione da eventuali future varianti basate sulla stessa primitiva Rubik.
    DOMAIN_SUFFIX_BITS = "01"

    # Seed per la generazione dei token.
    TOKEN_SEED = 0x4D524B3453504F4E
    ROUND_SEED = 0x524F554E44344B34
    IV_SEED = 0x49564D524B4B3458

    def __init__(self):
        primitive = Rubik4x4Primitive()
        self.moves = primitive.moves
        self.move_values = tuple(self.moves.values())
        self.identity = primitive.identity

        # Un token distinto per ogni blocco possibile di 12 bit.
        self.tokens = self._build_tokens()

        # Costanti e word della permutazione interna.
        self._build_round_parameters()

        # IV pubblico.
        self._build_iv()
        # Stato interno iniziale = IV.
        self._reset_state()

    # --------------------------------------------------------
    # OPERAZIONI DI GRUPPO
    # --------------------------------------------------------

    @staticmethod
    def _compose(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[int, ...]:
        return tuple(a[b[i]] for i in range(96))

    @staticmethod
    def _inverse(p: tuple[int, ...]) -> tuple[int, ...]:
        inv = [0] * 96
        for i, x in enumerate(p):
            inv[x] = i
        return tuple(inv)

    @staticmethod
    def _assert_permutation(p: tuple[int, ...]) -> None:
        if len(p) != 96 or set(p) != set(range(96)):
            raise AssertionError("object is not a valid 96-element permutation")

    def _random_group_element(self, rng: FixedRNG, min_len: int, max_len: int) -> tuple[int, ...]:
        current = self.identity
        length = min_len + rng.randbelow(max_len - min_len + 1)
        for _ in range(length):
            move = self.move_values[rng.randbelow(len(self.move_values))]
            current = self._compose(current, move)
        return current

    # --------------------------------------------------------
    # TOKEN DA 12 BIT
    # --------------------------------------------------------

    def _build_tokens(self) -> tuple[tuple[int, ...], ...]:
        """
        Costruisce 4096 elementi distinti del gruppo.

        Questo elimina il problema della versione originaria in cui
        64 ingressi possibili venivano ridotti a 45 mosse con modulo.
        """
        rng = FixedRNG(self.TOKEN_SEED)
        tokens = []
        seen = {self.identity}

        while len(tokens) < self.TOKEN_COUNT:
            candidate = self._random_group_element(rng, 4, 12)
            # Evita duplicati: ogni token deve essere unico.
            if candidate in seen:
                continue
            seen.add(candidate)
            tokens.append(candidate)

        return tuple(tokens)

    # --------------------------------------------------------
    # COSTANTI E WORD DELLA PERMUTAZIONE
    # --------------------------------------------------------

    def _build_round_parameters(self) -> None:
        rng = FixedRNG(self.ROUND_SEED)

        self.round_A = []
        self.round_B = []
        self.round_C = []
        self.round_word_constants = []
        self.round_words = []

        for _ in range(self.ROUNDS):
            # Genera un elemento casuale del gruppo per ogni registro A, B, C.
            # La lunghezza minima e massima della composizione di mosse è scelta per garantire una buona mescolanza.
            self.round_A.append(self._random_group_element(rng, 6, 12))
            self.round_B.append(self._random_group_element(rng, 6, 12))
            self.round_C.append(self._random_group_element(rng, 6, 12))

            # Genera costanti di round per la funzione di round.
            constants = tuple(
                self._random_group_element(rng, 4, 10)
                for _ in range(self.ROUND_WORD_LENGTH + 1)
            )
            self.round_word_constants.append(constants)

            # 0=X, 1=Y, 2=X^-1, 3=Y^-1
            while True:
                # Genera una word di gruppo casuale di lunghezza ROUND_WORD_LENGTH.
                word = [rng.randbelow(4) for _ in range(self.ROUND_WORD_LENGTH)]

                # Evita sequenze di soli X o soli Y, che non mescolano entrambi i registri.
                if not any(op in (0, 2) for op in word):
                    continue
                if not any(op in (1, 3) for op in word):
                    continue

                bad = False
                for a, b in zip(word, word[1:]):
                    # Evita sequenze come X X^-1 o Y Y^-1 che si annullano localmente.
                    if {a, b} == {0, 2} or {a, b} == {1, 3}:
                        bad = True
                        break

                if not bad:
                    break

            self.round_words.append(tuple(word))

        # Precomputiamo le inverse delle costanti di round per la permutazione inversa.
        self.round_A_inv = [self._inverse(x) for x in self.round_A]
        self.round_B_inv = [self._inverse(x) for x in self.round_B]
        self.round_C_inv = [self._inverse(x) for x in self.round_C]

    # --------------------------------------------------------
    # IV
    # --------------------------------------------------------

    def _build_iv(self) -> None:
        rng = FixedRNG(self.IV_SEED)
        # 16-24 mosse per ogni cubo A, B, C. Questo garantisce un IV pubblico e riproducibile.
        self.iv_A = self._random_group_element(rng, 16, 24)
        self.iv_B = self._random_group_element(rng, 16, 24)
        self.iv_C = self._random_group_element(rng, 16, 24)

    def _reset_state(self) -> None:
        self.A = self.iv_A
        self.B = self.iv_B
        self.C = self.iv_C

    # --------------------------------------------------------
    # F_r(X,Y)
    # --------------------------------------------------------

    def _round_function(self, x: tuple[int, ...], y: tuple[int, ...], round_index: int) -> tuple[int, ...]:
        """
        Word di gruppo pubblica costruita con X,Y,X^-1,Y^-1.
        """
        word = self.round_words[round_index]
        constants = self.round_word_constants[round_index]
        x_inv = self._inverse(x)
        y_inv = self._inverse(y)

        value = constants[0]
        for i, op in enumerate(word):
            if op == 0:
                term = x
            elif op == 1:
                term = y
            elif op == 2:
                term = x_inv
            else:
                term = y_inv

            value = self._compose(value, term)
            value = self._compose(value, constants[i + 1])

        return value

    # --------------------------------------------------------
    # PERMUTAZIONE INTERNA
    # --------------------------------------------------------

    # Permutazione invertibile per evitare collisioni locali e garantire una buona mescolanza dello stato interno.
    def _permute(self) -> None:
        """
        Round reversibile:

            A' = B * K_A
            B' = C * K_B
            C' = A * F(B,C) * K_C

        In forma inversa:

            B = A' * K_A^-1
            C = B' * K_B^-1
            A = C' * K_C^-1 * F(B,C)^-1
        """
        for r in range(self.ROUNDS):
            old_A, old_B, old_C = self.A, self.B, self.C
            f = self._round_function(old_B, old_C, r)

            self.A = self._compose(old_B, self.round_A[r])
            self.B = self._compose(old_C, self.round_B[r])
            self.C = self._compose(
                self._compose(old_A, f),
                self.round_C[r],
            )

    def _permute_inverse(self) -> None:
        """Inversa usata nei test di correttezza della permutazione."""
        for r in range(self.ROUNDS - 1, -1, -1):
            current_A, current_B, current_C = self.A, self.B, self.C

            old_B = self._compose(current_A, self.round_A_inv[r])
            old_C = self._compose(current_B, self.round_B_inv[r])

            temp = self._compose(current_C, self.round_C_inv[r])
            f = self._round_function(old_B, old_C, r)
            old_A = self._compose(temp, self._inverse(f))

            self.A, self.B, self.C = old_A, old_B, old_C

    # --------------------------------------------------------
    # PADDING
    # --------------------------------------------------------

    def _pad_message(self, message: bytes) -> str:
        """Padding 10*1 su blocchi da 12 bit."""
        bits = "".join(f"{byte:08b}" for byte in message)

        # Domain separation: distingue questa variante da eventuali
        # future costruzioni basate sulla stessa primitiva Rubik.
        bits += self.DOMAIN_SUFFIX_BITS
        # Aggiunge un "1" per il padding 10*1.
        bits += "1"
        # Aggiunge zeri fino a raggiungere un multiplo di BLOCK_BITS.
        zeros = (self.BLOCK_BITS - ((len(bits) + 1) % self.BLOCK_BITS)) % self.BLOCK_BITS
        bits += "0" * zeros
        # Aggiunge un "1" finale per completare il padding 10*1.
        bits += "1"

        if len(bits) % self.BLOCK_BITS != 0:
            raise AssertionError("padding failure")
        return bits

    # --------------------------------------------------------
    # ABSORB
    # --------------------------------------------------------

    def _absorb_block(self, block_bits: str) -> None:
        value = int(block_bits, 2)

        # Ogni 12-bit value ha un token distinto.
        self.A = self._compose(self.A, self.tokens[value])

        # Permutazione dopo ogni blocco.
        self._permute()

    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    @staticmethod
    def _mix64(x: int) -> int:
        """Mixer 64-bit usato solo come proiezione dello stato."""
        mask = (1 << 64) - 1
        x = (x + 0x9E3779B97F4A7C15) & mask
        x ^= x >> 30
        x = (x * 0xBF58476D1CE4E5B9) & mask
        x ^= x >> 27
        x = (x * 0x94D049BB133111EB) & mask
        x ^= x >> 31
        return x & mask

    def _read_rate128(self) -> int:
        """
        Proiezione del cubo A in 128 bit usando tutti i 96 sticker.

        E' una funzione di output, non una sostituzione della permutazione.
        """
        # Usiamo un mixer 64-bit per comprimere lo stato del cubo in 128 bit.
        # La funzione di output non deve essere invertibile, quindi possiamo usare un mixer semplice.
        # a, b sono due registri a 64 bit che accumulano lo stato del cubo A.
        # Questi due valori derivano dalle cifre esadecimali del pi greco e della costante di Eulero.
        a = 0x243F6A8885A308D3
        b = 0x13198A2E03707344
        # Mask per limitare a 64 bit le operazioni intermedie.
        mask = (1 << 64) - 1

        for i, value in enumerate(self.A):
            # Ogni sticker contribuisce a mescolare i due registri a e b.
            t = (value + 0x9E3779B9 * (i + 1)) & mask
            # Mescola i due registri a e b con XOR e una funzione di mixing a 64 bit.
            a ^= self._mix64(t ^ b)
            b ^= self._mix64((t + a + i) & mask)
            # Rotazioni a 64 bit verso sinistra per mescolare ulteriormente i due registri.
            a = ((a << 13) | (a >> 51)) & mask
            b = ((b << 17) | (b >> 47)) & mask

        # Combina i due registri a e b in un unico intero a 128 bit.
        return (a << 64) | b

    # --------------------------------------------------------
    # HASH
    # --------------------------------------------------------

    def hash(self, message: str | bytes | bytearray) -> str:
        """
        Pipeline:
            message -> padding -> absorb -> squeeze -> 256 bit digest
        """
        if isinstance(message, str):
            message = message.encode("utf-8")
        elif isinstance(message, bytearray):
            message = bytes(message)
        elif not isinstance(message, bytes):
            raise TypeError("message must be str, bytes, or bytearray")

        self._reset_state()
        padded = self._pad_message(message)

        for i in range(0, len(padded), self.BLOCK_BITS):
            self._absorb_block(padded[i:i + self.BLOCK_BITS])

        # Creiamo un digest da 256 bit in due fasi da 128 bit.
        out1 = self._read_rate128()
        self._permute()
        out2 = self._read_rate128()

        digest = (out1 << 128) | out2
        return f"{digest:064x}"


# ============================================================
# TEST DELLA PRIMITIVA RUBIK
# ============================================================

def primitive_tests() -> None:
    primitive = Rubik4x4Primitive()

    for name, move in primitive.moves.items():
        if len(move) != 96 or set(move) != set(range(96)):
            raise AssertionError(f"{name} is not a permutation")

    for face in primitive.FACE_ORDER:
        move = primitive.moves[face]
        inverse = primitive.moves[face + "'"]
        move2 = primitive._compose(move, move)
        move4 = primitive._compose(move2, move2)

        if move4 != primitive.identity:
            raise AssertionError(f"{face}^4 != identity")
        if primitive._compose(move, inverse) != primitive.identity:
            raise AssertionError(f"{face} * {face}' != identity")
        if primitive._compose(inverse, move) != primitive.identity:
            raise AssertionError(f"{face}' * {face} != identity")

    print("[OK] primitive move tests")
    
def wide_move_tests() -> None:
    primitive = Rubik4x4Primitive()

    for face in primitive.FACE_ORDER:
        wide = primitive.moves[face + "w"]
        wide_inv = primitive.moves[face + "w'"]
        wide2 = primitive.moves[face + "w2"]

        # Devono essere vere permutazioni di 96 sticker.
        if len(wide) != 96 or set(wide) != set(range(96)):
            raise AssertionError(f"{face}w is not a permutation")

        # X * X' = I
        if primitive._compose(wide, wide_inv) != primitive.identity:
            raise AssertionError(f"{face}w * {face}w' != identity")

        # X^4 = I
        if primitive._compose(wide2, wide2) != primitive.identity:
            raise AssertionError(f"{face}w^4 != identity")

        # Wide move deve essere diversa dall'outer move.
        if wide == primitive.moves[face]:
            raise AssertionError(
                f"{face}w is identical to {face}"
            )

    print("[OK] wide move tests")


# ============================================================
# TEST DELLA PERMUTAZIONE INTERNA
# ============================================================

def face_orientation_tests() -> None:
    """Verifica esplicitamente che CW significhi davvero orario."""
    primitive = Rubik4x4Primitive()

    for face in primitive.FACE_ORDER:
        definition = primitive.FACE_DEFS[face]
        normal = definition["normal"]
        right = definition["right"]
        down = definition["down"]

        def position(u: int, v: int):
            return (
                3 * normal[0] + u * right[0] + v * down[0],
                3 * normal[1] + u * right[1] + v * down[1],
                3 * normal[2] + u * right[2] + v * down[2],
            )

        # Sticker in alto a sinistra della faccia.
        top_left_key = (position(-3, -3), normal)
        # Dopo una rotazione oraria deve finire in alto a destra.
        top_right_key = (position(3, -3), normal)

        old_index = primitive._sticker_to_index[top_left_key]
        expected_index = primitive._sticker_to_index[top_right_key]
        new_index = primitive.moves[face].index(old_index)

        if new_index != expected_index:
            raise AssertionError(
                f"{face} clockwise orientation is inconsistent"
            )

    print("[OK] face rotations are clockwise in the declared geometry")


def permutation_tests() -> None:
    """Verifica che la permutazione interna sia invertibile."""
    h = RubikSponge4x4()
    rng = FixedRNG(0xCAFEBABE12345678)

    for _ in range(8):
        A = h.identity
        B = h.identity
        C = h.identity

        for _ in range(12):
            A = h._compose(A, h.move_values[rng.randbelow(len(h.move_values))])
            B = h._compose(B, h.move_values[rng.randbelow(len(h.move_values))])
            C = h._compose(C, h.move_values[rng.randbelow(len(h.move_values))])

        h.A, h.B, h.C = A, B, C
        original = (h.A, h.B, h.C)

        h._permute()
        h._permute_inverse()

        if (h.A, h.B, h.C) != original:
            raise AssertionError("internal permutation inverse failed")

    print("[OK] internal permutation invertibility")


# ============================================================
# TEST DEI TOKEN
# ============================================================

def token_tests() -> None:
    h = RubikSponge4x4()
    unique = len(set(h.tokens))

    if unique != h.TOKEN_COUNT:
        raise AssertionError(
            f"expected {h.TOKEN_COUNT} unique tokens, got {unique}"
        )
    if h.identity in h.tokens:
        raise AssertionError("identity must not be used as a token")

    print("[OK] 4096 block tokens are unique")


# ============================================================
# TEST ESAUSTIVO SU 1 BYTE
# ============================================================

def exhaustive_one_byte_test() -> None:
    h = RubikSponge4x4()
    seen = {}

    for value in range(256):
        message = bytes([value])
        digest = h.hash(message)
        if digest in seen:
            raise AssertionError(
                f"collision for {seen[digest]!r} and {message!r}"
            )
        seen[digest] = message

    print("[OK] no collision among all 256 one-byte messages")


# ============================================================
# AVALANCHE TEST
# ============================================================

def avalanche_test(iterations: int = 1000) -> None:
    h = RubikSponge4x4()
    rng = random.Random(0x1234ABCD)
    total_changed = 0

    for _ in range(iterations):
        length = rng.randint(1, 64)
        message = bytearray(rng.getrandbits(8) for _ in range(length))
        modified = bytearray(message)

        byte_index = rng.randrange(length)
        bit_index = rng.randrange(8)
        modified[byte_index] ^= 1 << bit_index

        digest_a = int(h.hash(message), 16)
        digest_b = int(h.hash(modified), 16)
        total_changed += (digest_a ^ digest_b).bit_count()

    percentage = total_changed / (iterations * 256) * 100
    print(f"Avalanche: {percentage:.3f}% (ideale statistico ≈ 50%)")


# ============================================================
# TEST DI ESEMPIO
# ============================================================

def example_test() -> None:
    h = RubikSponge4x4()

    samples = [
        b"",
        b"a",
        b"ciao",
        b"ciao.",
        b"hello",
        bytes(range(32)),
    ]

    for message in samples:
        print(f"{message!r} -> {h.hash(message)}")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    primitive_tests()
    wide_move_tests()
    face_orientation_tests()
    token_tests()
    permutation_tests()
    exhaustive_one_byte_test()
    example_test()
    avalanche_test(100)
