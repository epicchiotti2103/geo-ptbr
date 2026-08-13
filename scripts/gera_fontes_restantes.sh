#!/bin/bash
# Driver autônomo: gera fontes das queries faltantes via grok CLI, 3 em paralelo.
# Raiz do repositório, derivada da localização DESTE arquivo — não do caminho
# da máquina do autor. A versão anterior tinha `cd /Volumes/SSD1/Projects/paper`
# fixo, o que quebrava para qualquer pessoa que clonasse o repositório.
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for p in .tmp_fontes/*.prompt; do
  qid=$(basename "$p" .prompt)
  [ -f "data/sources/$qid.jsonl" ] && continue
  (
    grok --prompt-file "$p" -m grok-4.5 --always-approve > ".tmp_fontes/$qid.log" 2>&1
    echo "$(date +%H:%M:%S) $qid exit=$?" >> .tmp_fontes/driver.log
  ) &
  while [ "$(jobs -r | wc -l)" -ge 3 ]; do wait -n; done
done
wait
echo "DRIVER CONCLUÍDO" >> .tmp_fontes/driver.log
