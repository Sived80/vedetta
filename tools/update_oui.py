"""Rigenera app/data/oui-ieee.txt dai registri pubblici dell'IEEE (MA-L 24 bit,
MA-M 28 bit, MA-S 36 bit e IAB). La logica sta in app/oui_update.py (la usa
anche l'aggiornamento dal web, che scrive pero' in config/).

Uso:  python tools/update_oui.py                 (scarica i registri aggiornati)
      python tools/update_oui.py a.csv b.csv...  (usa copie gia' scaricate)

Formato di uscita, una riga per blocco:  PREFISSO[/bit] Nome registrato
con il prefisso in esadecimale maiuscolo senza due punti (es. BC2411,
00155D4/28)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "vedetta"
sys.path.insert(0, str(ROOT))
from app import oui_update  # noqa: E402

OUT = ROOT / "app" / "data" / "oui-ieee.txt"


def main() -> None:
    if len(sys.argv) > 1:
        texts = [Path(a).read_text(encoding="utf-8", errors="replace") for a in sys.argv[1:]]
    else:
        texts = oui_update.download()
    content, blocks = oui_update.build(texts)
    oui_update.write_atomic(OUT, content)
    print(f"{blocks} blocchi scritti in {OUT}")


if __name__ == "__main__":
    main()
