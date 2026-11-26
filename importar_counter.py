"""Importa relatórios COUNTER da Perlego (ou de outra plataforma) para a base de dados.

    python importar_counter.py TR_B1_2026.xlsx
    python importar_counter.py relatorios/*.csv --bd outro.db

Aceita o formato tabular COUNTER 5 / 5.1 em XLSX, CSV ou TSV. Pode importar o mesmo
mês mais de uma vez: os valores são substituídos, não somados.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import analytics


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ficheiros", nargs="+", type=Path)
    ap.add_argument("--bd", default=None)
    a = ap.parse_args()
    conn = analytics.ligar(a.bd)
    erros = 0
    for f in a.ficheiros:
        try:
            r = analytics.importar_counter(conn, f.read_bytes())
        except Exception as erro:  # noqa: BLE001 — mostrar e continuar com os outros ficheiros
            print(f"✗ {f}: {erro}")
            erros += 1
            continue
        meses = " a ".join(r["meses"]) if r["meses"] else "sem meses"
        print(f"✓ {f}: {r['relatorio']}, {r['titulos']} títulos, {r['registos']} valores ({meses})")
    sys.exit(1 if erros else 0)


if __name__ == "__main__":
    main()
