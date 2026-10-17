#!/usr/bin/env python3
"""
Alerta de mercados de jogador (player props) — basquetebol.

Abre a página de cada liga em cada casa de apostas, recolhe os links dos jogos,
abre cada jogo e verifica se já aparecem mercados de jogador (pontos, ressaltos,
assistências...). Quando aparecem pela primeira vez, envia um aviso no Telegram.

Uso:
  python bot.py                 # uma verificação (é o que o GitHub Actions corre)
  python bot.py --loop 10       # verifica de 10 em 10 minutos (para correr no PC)
  python bot.py --teste         # envia uma mensagem de teste para o Telegram
  python bot.py --descobrir     # mostra os links encontrados em cada liga (para afinar o config)
"""
import argparse
import asyncio
import html
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml
from playwright.async_api import async_playwright

BASE = Path(__file__).parent
STATE_FILE = BASE / "state.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
DIAS_MEMORIA = 7


# ---------------------------------------------------------------- utilitários
def load_config():
    return yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))


def load_state():
    try:
        s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        s = {}
    s.setdefault("alertados", {})
    s.setdefault("avisos", {})
    return s


def save_state(state):
    limite = time.time() - DIAS_MEMORIA * 86400
    state["alertados"] = {k: v for k, v in state["alertados"].items() if v["t"] > limite}
    state["avisos"] = {k: v for k, v in state["avisos"].items() if v > limite}
    STATE_FILE.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


def telegram(texto):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[Telegram não configurado]\n" + texto)
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": texto, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=20,
        )
        if not r.ok:
            print("Erro Telegram:", r.text)
    except Exception as e:
        print("Erro Telegram:", e)


def aviso_unico(state, chave, texto, horas=12):
    """Envia um aviso de problema no máximo uma vez a cada X horas."""
    ultimo = state["avisos"].get(chave, 0)
    if time.time() - ultimo > horas * 3600:
        telegram(texto)
        state["avisos"][chave] = time.time()
    print("AVISO:", re.sub("<[^>]+>", "", texto))


def liga_configurada(liga):
    return liga.get("ativo", True) and liga.get("url", "").startswith("http")


# ---------------------------------------------------------------- browser
async def aceitar_cookies(page):
    for txt in ("Aceitar todos", "Aceitar tudo", "Aceitar", "Aceito", "Accept all", "Accept", "OK"):
        try:
            btn = page.get_by_role("button", name=re.compile(rf"^\s*{txt}\s*$", re.I))
            if await btn.count():
                await btn.first.click(timeout=1500)
                await page.wait_for_timeout(500)
                return
        except Exception:
            pass


async def abrir(page, url, espera_ms):
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(espera_ms)
    await aceitar_cookies(page)
    # alguns sites só carregam o resto ao fazer scroll
    try:
        await page.mouse.wheel(0, 4000)
        await page.wait_for_timeout(800)
    except Exception:
        pass
    # espera extra se a página ainda estiver quase vazia (sites carregados por JavaScript)
    texto = await texto_da_pagina(page)
    if len(texto) < 500:
        await page.wait_for_timeout(espera_ms)
        texto = await texto_da_pagina(page)
    return texto


# Lê também o conteúdo dentro de iframes e de "shadow DOM" (muitas casas embutem
# o sportsbook de um fornecedor externo dessa forma).
JS_TEXTO = """() => {
  const partes = [document.body ? document.body.innerText : ''];
  const visitar = (raiz) => raiz.querySelectorAll('*').forEach(el => {
    if (el.shadowRoot) { partes.push(el.shadowRoot.textContent || ''); visitar(el.shadowRoot); }
  });
  visitar(document);
  return partes.join(' ');
}"""

JS_LINKS = """() => {
  const out = [];
  const visitar = (raiz) => {
    raiz.querySelectorAll('a[href]').forEach(a =>
      out.push([a.href, (a.innerText || a.textContent || '').replace(/\\s+/g, ' ').trim()]));
    raiz.querySelectorAll('*').forEach(el => { if (el.shadowRoot) visitar(el.shadowRoot); });
  };
  visitar(document);
  return out;
}"""


async def texto_da_pagina(page):
    partes = []
    for frame in page.frames:
        try:
            partes.append(await frame.evaluate(JS_TEXTO))
        except Exception:
            pass
    return " ".join(partes).lower()


async def links_da_pagina(page):
    links = []
    for frame in page.frames:
        try:
            links += await frame.evaluate(JS_LINKS)
        except Exception:
            pass
    return links


def filtrar_jogos(links, liga):
    url_liga = urlparse(liga["url"])
    caminho_liga = url_liga.path.rstrip("/")
    padrao = re.compile(liga["padrao_jogo"]) if liga.get("padrao_jogo") else None
    dentro_da_liga, com_id = {}, {}
    for href, texto in links:
        u = urlparse(href)
        limpo = f"{u.scheme}://{u.netloc}{u.path}"
        caminho = u.path.rstrip("/")
        if caminho == caminho_liga:
            continue
        if padrao:
            if padrao.search(limpo):
                destino = dentro_da_liga
            else:
                continue
        elif u.netloc != url_liga.netloc:
            continue
        elif caminho_liga and caminho.startswith(caminho_liga + "/"):
            destino = dentro_da_liga   # ex.: .../liga-acb-123/equipa-a-equipa-b-456
        elif re.search(r"\d{5,}", caminho):
            destino = com_id           # heurística: links de jogo costumam ter um ID numérico
        else:
            continue
        if limpo not in destino or len(texto) > len(destino[limpo]):
            destino[limpo] = texto[:90]
    # links "dentro" da página da liga são mais fiáveis; só usa a heurística se não houver nenhum
    return dentro_da_liga or com_id


def bloqueado(texto, cfg):
    return any(f.lower() in texto for f in cfg.get("frases_bloqueio", []))


# ---------------------------------------------------------------- execução
async def verificar(cfg, state, descobrir=False):
    palavras = [k.lower() for k in cfg["palavras_props"]]
    espera = cfg.get("espera_ms", 4000)
    max_jogos = cfg.get("max_jogos_por_liga", 15)
    pausa = cfg.get("pausa_segundos", 2)
    novos = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            locale="pt-PT", timezone_id="Europe/Lisbon", user_agent=UA,
            viewport={"width": 1366, "height": 900},
        )
        page = await ctx.new_page()

        for liga in cfg["ligas"]:
            if not liga_configurada(liga):
                continue
            nome = f"{liga['casa']} · {liga['liga']}"
            print(f"\n== {nome}")

            try:
                texto = await abrir(page, liga["url"], espera)
            except Exception as e:
                aviso_unico(state, f"erro:{nome}",
                            f"⚠️ <b>{html.escape(nome)}</b>: não consegui abrir a página da liga ({html.escape(str(e)[:120])}).")
                continue

            if bloqueado(texto, cfg):
                aviso_unico(state, f"bloq:{liga['casa']}",
                            f"⛔ <b>{html.escape(liga['casa'])}</b> parece estar a bloquear o acesso a partir deste servidor "
                            f"(região ou anti-bot). Vê o README, secção «Plano B».")
                continue

            links = await links_da_pagina(page)

            if descobrir:
                print(f"{len(links)} links na página. Candidatos a jogo:")
                for u, t in filtrar_jogos(links, liga).items():
                    print(f"  {t[:50]:50}  {u}")
                print("Todos os links (para criares o padrao_jogo):")
                for u, t in links:
                    print(f"    {t[:40]:40}  {u}")
                continue

            jogos = filtrar_jogos(links, liga)
            print(f"{len(jogos)} jogos encontrados")
            if not jogos:
                aviso_unico(state, f"vazio:{nome}",
                            f"⚠️ <b>{html.escape(nome)}</b>: não encontrei jogos na página. "
                            f"Ou não há jogos, ou o site mudou / bloqueou. Corre <code>python bot.py --descobrir</code>.",
                            horas=24)
                continue

            for url, titulo in list(jogos.items())[:max_jogos]:
                if url in state["alertados"]:
                    continue
                try:
                    texto_jogo = await abrir(page, url, espera)
                except Exception as e:
                    print("  erro a abrir jogo:", e)
                    continue
                encontrados = [k for k in palavras if k in texto_jogo]
                print(f"  {'✅' if encontrados else '…'} {titulo[:60]}  {encontrados or ''}")
                if encontrados:
                    telegram(
                        f"🏀 <b>Mercados de jogador disponíveis</b>\n"
                        f"<b>{html.escape(liga['casa'])}</b> · {html.escape(liga['liga'])}\n"
                        f"{html.escape(titulo or url)}\n"
                        f"Encontrado: {html.escape(', '.join(encontrados[:4]))}\n"
                        f"<a href=\"{html.escape(url)}\">Abrir jogo</a>"
                    )
                    state["alertados"][url] = {"t": time.time(), "casa": liga["casa"], "jogo": titulo}
                    novos += 1
                await asyncio.sleep(pausa)

        await browser.close()
    print(f"\nFeito. Novos alertas: {novos}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, metavar="MIN", help="repetir de X em X minutos")
    ap.add_argument("--teste", action="store_true", help="enviar mensagem de teste para o Telegram")
    ap.add_argument("--descobrir", action="store_true", help="listar links de cada liga")
    args = ap.parse_args()

    cfg = load_config()

    if args.teste:
        telegram("✅ Bot de props ligado e a funcionar.")
        ativas = [f"{l['casa']} · {l['liga']}" for l in cfg["ligas"] if liga_configurada(l)]
        print("Ligas configuradas:", ativas or "nenhuma — cola os links no config.yaml")
        return

    while True:
        state = load_state()
        try:
            asyncio.run(verificar(cfg, state, descobrir=args.descobrir))
        finally:
            save_state(state)
        if not args.loop or args.descobrir:
            break
        print(f"A dormir {args.loop} min...")
        time.sleep(args.loop * 60)


if __name__ == "__main__":
    sys.exit(main())
