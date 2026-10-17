# Alerta de props de basquetebol (Betano · Betclic · SpinHub)

O bot abre a página de cada liga, recolhe os jogos, abre cada jogo e procura sinais de
mercados de jogador (pontos, ressaltos, assistências…). Na primeira vez que aparecem
num jogo, recebes uma mensagem no Telegram com o link. Não repete o aviso para o mesmo jogo.

Custo: 0 €. Corre no GitHub Actions (grátis em repositórios públicos) de 10 em 10 minutos.

---

## 1. Criar o bot do Telegram (5 min)

1. No Telegram, abre **@BotFather** → `/newbot` → dá-lhe um nome. Guarda o **token**.
2. Abre o teu bot novo e manda-lhe uma mensagem qualquer ("olá").
3. No browser abre: `https://api.telegram.org/bot<TOKEN>/getUpdates`
   e procura `"chat":{"id":123456789` → esse número é o teu **chat id**.

## 2. Pôr os links das ligas no `config.yaml`

Para cada casa e liga: abre a página da liga no site (no PC), copia o link da barra de
endereço e cola no lugar de `COLA_AQUI_O_LINK`. Ligas que não queiras, deixa como estão
(são ignoradas) ou apaga.

## 3. Testar no teu PC (recomendado antes de tudo)

```bash
pip install -r requirements.txt
python -m playwright install chromium

# Windows (PowerShell):
$env:TELEGRAM_TOKEN="o_teu_token"; $env:TELEGRAM_CHAT_ID="o_teu_chat_id"
# Mac/Linux:
export TELEGRAM_TOKEN=o_teu_token TELEGRAM_CHAT_ID=o_teu_chat_id

python bot.py --teste       # deve chegar uma mensagem ao Telegram
python bot.py --descobrir   # mostra que jogos o bot encontra em cada liga
python bot.py               # verificação real
```

Se o `--descobrir` apanhar links que não são jogos (ou falhar jogos), preenche o
`padrao_jogo` dessa liga com um pedaço que só os links de jogo têm. Exemplo: se todos os
jogos forem `.../odds/lakers-celtics/12345678/`, usa `padrao_jogo: "/odds/.+/\d+"`.

Se receberes alertas falsos (ex.: a palavra "jogadores" aparece em todos os jogos),
tira essa palavra de `palavras_props`. Se não receberes nenhum quando sabes que há props,
abre um jogo, vê como o separador se chama e acrescenta esse texto.

## 4. Pôr a correr 24h no GitHub (grátis)

1. Cria conta em github.com → **New repository** → **Public** → cria.
2. **Add file → Upload files** e carrega tudo (incluindo a pasta `.github`).
   No telemóvel/browser pode ser mais fácil criar o ficheiro
   `.github/workflows/alerta.yml` à mão com **Add file → Create new file** e colar o conteúdo.
3. **Settings → Secrets and variables → Actions → New repository secret**:
   - `TELEGRAM_TOKEN` = o token
   - `TELEGRAM_CHAT_ID` = o chat id
4. Separador **Actions** → ativa os workflows → **alerta-props → Run workflow** para testar.

Depois disso corre sozinho de ~10 em 10 minutos.

Notas:
- O token fica nos Secrets, nunca aparece no código público.
- Repositório **público** porque os privados só têm 2000 minutos grátis/mês, que não chegam.
- O GitHub desliga workflows agendados se o repositório não tiver alterações durante
  60 dias. Se isso acontecer, recebes email; basta reativar no separador Actions.

## Plano B — se as casas bloquearem o GitHub

Os servidores do GitHub estão fora de Portugal e as casas portuguesas podem bloquear ou
pedir verificação anti-bot. O bot avisa-te no Telegram se isso acontecer (⛔).
Nesse caso a alternativa grátis é correr no teu PC, com IP português:

```bash
python bot.py --loop 10
```

Funciona enquanto o PC estiver ligado. Um portátil antigo ligado à corrente serve bem.

## Avisos

- Os sites mudam o layout de vez em quando; se deixares de receber alertas, corre
  `--descobrir` e ajusta o `config.yaml`.
- Ler os sites automaticamente pode ir contra os termos de uso das casas. O bot faz
  poucas visitas e com pausas, mas usa por tua conta.
