# Eleições EUA 2026 – Senado e Governador

Página: https://augustocb.github.io/midterms2026/

- `index.html` – a página (GitHub Pages). Recarrega `data.json` a cada minuto.
- `data.json` – previsões do Decision Desk HQ (antes da apuração) + projeções de vencedores.
- `scripts/update.py` – pede ao Gemini (`gemini-3.8-flash`, com busca do Google) as projeções novas e atualiza `data.json`.
- `.github/workflows/update.yml` – roda o script a cada 5 minutos, de 4 a 6/11 (UTC). Também pode ser disparado em Actions → "Atualizar projeções" → Run workflow.

Configuração: adicione o segredo `GEMINI_API_KEY` em Settings → Secrets and variables → Actions (chave criada em aistudio.google.com).

"Projetado" é a projeção de um veículo de imprensa (AP, NBC, CBS…), não o resultado oficial certificado.
