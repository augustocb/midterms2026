#!/usr/bin/env python3
"""Atualiza data.json com as projeções de Senado e Governador (EUA 2026).

Pede ao Gemini (API do Google, com busca do Google) a lista de disputas já
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
import time
import urllib.error
import urllib.request

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
API_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
DATA = os.path.join(os.path.dirname(__file__), "..", "data.json")
OUTLETS = ("AP", "NBC", "CBS", "CNN", "ABC", "Fox", "DDHQ", "Decision Desk HQ", "NYT", "New York Times")


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def call_api(prompt, key):
    body = {"model": MODEL, "input": prompt, "tools": [{"type": "google_search"}]}
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode(),
        headers={"x-goog-api-key": key, "content-type": "application/json"},
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:1500]
            print(f"::warning::Gemini HTTP {e.code}: {detail}")
            if e.code in (429, 500, 503) and attempt < 2:
                time.sleep(20 * (attempt + 1))
                continue
            raise SystemExit(f"Gemini falhou com HTTP {e.code}")


def build_prompt(data, only=None):
    open_races = []
    called = []
    for office, label in (("senate", "Senado"), ("governor", "Governador")):
        for st, r in sorted(data[office].items()):
            name = data["states"][st]
            if only is not None and (office, st) not in only and not r.get("called"):
                continue
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
- Busque CADA disputa em aberto listada acima individualmente (ex.: \"<estado> senate race called\", \"<estado> governor projected winner\").
- Inclua uma disputa só se uma fonte que você encontrou disser explicitamente que um veículo projetou/declarou o vencedor. Liderança na contagem NÃO é projeção.
- Não use conhecimento de memória.
- Para independentes, use em "party" o partido com que se alinham e acrescente " (I)" ao nome.

Responda no final com UM bloco ```json e nada depois dele, neste formato:
{{"calls":[{{"office":"senate"|"governor","state":"XX","winner":"Nome","party":"D"|"R","calledBy":"AP","source":"https://..."}}],
 "retracted":[{{"office":"senate"|"governor","state":"XX","source":"https://..."}}],
 "checkedThroughET":"21:40"}}
Liste em \"calls\" todas as projeções novas que encontrou (pode repetir as já marcadas). Cada item precisa do link (\"source\") da notícia que encontrou na busca; sem link, não inclua."""


def walk(node):
    """Percorre a resposta (formato antigo "outputs" ou novo "steps")."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


CHUNK = int(os.environ.get("CHUNK_SIZE", "8"))


def run_model(data, key):
    """Confere as disputas em aberto em grupos, cada grupo com buscas próprias."""
    open_races = [(o, st) for o in ("senate", "governor") for st, r in sorted(data[o].items()) if not r.get("called")]
    calls, retracted, et, ok = [], [], None, 0
    for i in range(0, len(open_races), CHUNK):
        group = set(open_races[i:i + CHUNK])
        print(f"Grupo {i // CHUNK + 1}: {', '.join(f'{o[:3]}-{st}' for o, st in sorted(group))}")
        try:
            res = run_group(data, key, group)
        except SystemExit as e:
            print(f"::warning::grupo ignorado: {e}")
            continue
        ok += 1
        calls += res.get("calls", [])
        retracted += res.get("retracted", [])
        et = res.get("checkedThroughET") or et
    if not ok:
        raise SystemExit("Nenhum grupo com busca válida; nenhuma mudança aplicada.")
    return {"calls": calls, "retracted": retracted, "checkedThroughET": et}


def run_group(data, key, group):
    resp = call_api(build_prompt(data, group), key)
    queries, results, texts = [], 0, []
    for n in walk(resp):
        t = n.get("type")
        if t == "google_search_call":
            queries += (n.get("arguments") or {}).get("queries") or ["?"]
        elif t == "google_search_result":
            results += 1
        elif t == "text" and isinstance(n.get("text"), str):
            texts.append(n["text"])
    text = resp.get("output_text") if isinstance(resp.get("output_text"), str) else "\n".join(texts)
    print(f"Buscas feitas: {len(queries)} · resultados: {results}")
    for q in queries[:15]:
        print("  busca:", q)
    if not queries and not results:
        print("Chaves da resposta:", sorted(resp.keys()))
        raise SystemExit("Gemini respondeu sem pesquisar; nenhuma mudança aplicada.")
    m = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S) or re.findall(r"(\{\s*\"calls\".*\})", text, re.S)
    if not m:
        raise SystemExit("Resposta sem bloco JSON:\n" + text[-2000:])
    return json.loads(m[-1])


def merge(data, result):
    changes = []
    for c in result.get("calls", []):
        office, st = c.get("office"), (c.get("state") or "").upper()
        race = data.get(office, {}).get(st)
        party, winner, by = c.get("party"), (c.get("winner") or "").strip(), (c.get("calledBy") or "").strip()
        src = (c.get("source") or "").strip()
        if not race or party not in ("D", "R") or not winner or not src.startswith("http") or not any(o.lower() in by.lower() for o in OUTLETS):
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
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("::warning::Segredo GEMINI_API_KEY não configurado; nada a fazer.")
        return 0
    sys.path.insert(0, os.path.dirname(__file__))
    import interval
    if not interval.active(dt.datetime.now(dt.timezone.utc)):
        print("Fora do horário da agenda (pausa); nada a fazer.")
        return 0
    data = json.load(open(DATA, encoding="utf-8"))
    if all(r.get("called") for o in ("senate", "governor") for r in data[o].values()):
        print("Todas as disputas já projetadas.")
        return 0
    # evita rodadas em dobro (loop + agendamento de reserva)
    min_gap = int(os.environ.get("MIN_GAP_SECONDS", "200"))
    last = data.get("checked")
    if last and min_gap > 0:
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds()
        if age < min_gap:
            print(f"Conferido há {int(age)}s; pulando esta rodada.")
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
