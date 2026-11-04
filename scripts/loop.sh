#!/usr/bin/env bash
# Roda uma atualização, espera até o próximo horário da agenda (scripts/interval.py)
# e repete, por até ~5h45. Sai com 0 e grava STOP em /tmp/stop quando a agenda acabar.
set -u
git config user.name "github-actions[bot]"
git config user.email "41898208+github-actions[bot]@users.noreply.github.com"
end=$((SECONDS + 345*60))
first=1
while [ $SECONDS -lt $end ]; do
  git fetch -q origin main && git reset -q --hard origin/main
  w=$(python3 scripts/interval.py)
  if [ "$w" = "STOP" ]; then echo "Agenda encerrada."; echo STOP > /tmp/stop; exit 0; fi
  if [ $first -eq 0 ]; then
    [ $((SECONDS + w)) -ge $end ] && break
    echo "Próxima rodada em ${w}s"; sleep "$w"
    git fetch -q origin main && git reset -q --hard origin/main
    [ "$(python3 scripts/interval.py)" = "STOP" ] && { echo STOP > /tmp/stop; exit 0; }
  fi
  first=0
  if python3 -c "import json,sys;d=json.load(open('data.json'));sys.exit(0 if all(r.get('called') for o in ('senate','governor') for r in d[o].values()) else 1)"; then
    echo "Todas as disputas projetadas."; echo STOP > /tmp/stop; exit 0
  fi
  echo "::group::Rodada $(date -u +%H:%MZ)"
  MIN_GAP_SECONDS=240 python3 scripts/update.py || echo "::warning::rodada falhou"
  if ! git diff --quiet data.json; then
    git add data.json
    git commit -q -m "Atualiza projeções $(date -u +%H:%MZ)"
    for i in 1 2 3; do
      git push -q origin HEAD:main && break
      git pull -q --rebase origin main || { git rebase --abort; git reset -q --hard origin/main; break; }
    done
  fi
  echo "::endgroup::"
done
