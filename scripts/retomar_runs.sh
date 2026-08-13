#!/bin/bash
# Retoma as runs dos engines 2 e 3 de onde pararam (resumível pelos traces).
# Sobrevive ao fechamento do terminal (nohup). Uso: ./scripts/retomar_runs.sh
# Raiz do repositório, derivada da localização DESTE arquivo — não do caminho
# da máquina do autor. A versão anterior tinha `cd /Volumes/SSD1/Projects/paper`
# fixo, o que quebrava para qualquer pessoa que clonasse o repositório.
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
nohup caffeinate -i .venv/bin/python src/run_engine_batch.py \
  --engine claude-haiku-4-5 --all --poll-interval 120 >> eval/haiku_run.log 2>&1 &
echo "haiku PID $!"
nohup caffeinate -i .venv/bin/python src/run_engine_batch.py \
  --all --chunk-size 20 --poll-interval 60 >> eval/luna_run.log 2>&1 &
echo "luna PID $!"
echo "Acompanhe: tail -f eval/haiku_run.log  |  ls eval/traces_*/ | wc -l"
