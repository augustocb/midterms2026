#!/usr/bin/env python3
"""Atualiza data.json com as projeções de Senado e Governador (EUA 2026).

Pede ao Claude (API da Anthropic, com busca na web) a lista de disputas já
projetadas por veículos nomeados e mescla o resultado em data.json.
Regras de segurança:
  - só marca uma disputa como projetada quando o modelo cita um veículo;
  - nunca desmarca uma projeção, a não ser que ela venha listada em "retracted";
  - não altera a previsão de antes da apuração (party/chance).
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
DATA = os.path.join(os.path.dirname(__file__), "..", "data.json")
OUTLETS = ("AP", "NBC", "CBS", "CNN", "ABC", "Fox", "DDHQ", "Decision Desk HQ", "NYT", "New York Times")


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def call_api(messages, key):
    body = {
        "model": MODEL,
        "max_tokens": 8000,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 12}],
        "messages": messages,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode(),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def build_prompt(data):
    open_races = []
    called = []
    for office, label in (("senate", "Senado"), ("governor", "Governador")):
        for st, r in sorted(data[office].items()):
            name = data["states"][st]
            if r.get("called"):
                called.append(f"{label} {st} ({name}): {r['winner']} ({r['winnerParty']}), {r['calledBy']}")
            else:
                open_races.append(f"{label} {st} ({name})")
    return f"""Hoje é a apuração das eleições gerais dos EUA de 3 de novembro de 2026. Horário atual (UTC): {now_iso()}.

Tarefa: descubra, pesquisando na web agora, quais disputas para o Senado dos EUA e para governador estadual em 2026 já foram PROJETADAS (race call) por um veículo nomeado: AP, NBC, CBS, CNN, ABC, Fox, Decision Desk HQ ou NYT.

Disputas ainda sem projeção no nosso arquivo:
{chr(10).join(open_races) or "(nenhuma)"}

Já marcadas como projetadas (confira só se viu notícia de projeção retirada):
{chr(10).join(called) or "(nenhuma)"}

Regras:
- Faça buscas separadas para Senado e governador, e busque especificamente as disputas em aberto mais relevantes.
- Inclua uma disputa só se uma fonte que você encontrou disser explicitamente que um veículo projetou/declarou o vencedor. Liderança na contagem NÃO é projeção.
- Não use conhecimento de memória.
- Para independentes, use em "party" o partido com que se alinham e acrescente " (I)" ao nome.

Responda no final com UM bloco ```json e nada depois dele, neste formato:
{{"calls":[{{"office":"senate"|"governor","state":"XX","winner":"Nome","party":"D"|"R","calledBy":"AP","source":"https://..."}}],
 "retracted":[{{"office":"senate"|"governor","state":"XX","source":"https://..."}}],
 "checkedThroughET":"21:40"}}
Liste em "calls" todas as projeções novas que encontrou (pode repetir as já marcadas)."""


def run_model(data, key):
    messages = [{"role": "user", "content": build_prompt(data)}]
    for _ in range(6):
        resp = call_api(messages, key)
        if resp.get("stop_reason") == "pause_turn":
            messages.append({"role": "assistant", "content": resp["content"]})
            continue
        break
    text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    m = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S)
    if not m:
        raise SystemExit("Resposta sem bloco JSON:\n" + text[-2000:])
    return json.loads(m[-1])


def merge(data, result):
    changes = []
    for c in result.get("calls", []):
        office, st = c.get("office"), (c.get("state") or "").upper()
        race = data.get(office, {}).get(st)
        party, winner, by = c.get("party"), (c.get("winner") or "").strip(), (c.get("calledBy") or "").strip()
        if not race or party not in ("D", "R") or not winner or not any(o.lower() in by.lower() for o in OUTLETS):
            continue
        if race.get("called") and race.get("winnerParty") == party and race.get("winner") == winner:
            continue
        race.update(called=True, winner=winner, winnerParty=party, calledBy=by)
        changes.append(f"{office} {st}: {winner} ({party}) – {by}")
    for r in result.get("retracted", []):
        office, st = r.get("office"), (r.get("state") or "").upper()
        race = data.get(office, {}).get(st)
        if race and race.get("called") and r.get("source"):
            for k in ("winner", "winnerParty", "calledBy"):
                race.pop(k, None)
            race["called"] = False
            changes.append(f"{office} {st}: projeção retirada")
    return changes


def main():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("::warning::Segredo ANTHROPIC_API_KEY não configurado; nada a fazer.")
        return 0
    data = json.load(open(DATA, encoding="utf-8"))
    if all(r.get("called") for o in ("senate", "governor") for r in data[o].values()):
        print("Todas as disputas já projetadas.")
        return 0
    result = run_model(data, key)
    changes = merge(data, result)
    ts = now_iso()
    data["checked"] = ts
    if changes:
        data["updated"] = ts
    et = result.get("checkedThroughET")
    data["statusNote"] = (
        f"Projeções conferidas até {et} (horário do leste dos EUA). " if et else "Projeções conferidas automaticamente. "
    ) + "Disputas sem projeção mostram a previsão do Decision Desk HQ de antes da apuração."
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("Mudanças:" if changes else "Nenhuma mudança.")
    for c in changes:
        print(" -", c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
