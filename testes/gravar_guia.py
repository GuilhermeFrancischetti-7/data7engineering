# -*- coding: utf-8 -*-
"""Grava os GIFs do Guia do App, percorrendo a tela de verdade.

Uso:  py testes/gravar_guia.py [passo ...]

Sobe o Streamlit numa porta propria, abre no Chromium (Playwright), faz o
caminho inteiro com a massa FICTICIA de demo/xmls e salva um GIF por passo em
demo/guia/. Nada de cliente aparece nas imagens.

Regrave quando a tela mudar -- os GIFs sao o app real, nao desenho.
"""
import os
import shutil
import socket
import subprocess
import sys
import time

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTINO = os.path.join(PASTA, "demo", "guia")
DEMO = os.path.join(PASTA, "demo", "xmls")
# A massa e copiada para ca antes de gravar: o caminho aparece no GIF, e o da
# pasta do projeto entregaria o nome da maquina e do usuario. Ficticio e neutro.
DEMO_NA_TELA = r"C:\Migracao\XMLs_eSocial"
PORTA = 8599
LARGURA, ALTURA = 1280, 860
LARGO_GIF = 760               # largura final do GIF, em pixels
QUADROS_POR_PASSO = 6          # cada quadro = uma foto da tela durante a acao


def porta_livre(porta):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", porta)) != 0


def subir_app():
    """Streamlit proprio da gravacao: nao mexe no servidor que voce usa."""
    if not porta_livre(PORTA):
        print("porta %d ja ocupada; reaproveitando" % PORTA)
        return None
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", os.path.join(PASTA, "app.py"),
         "--server.port", str(PORTA), "--server.headless", "true",
         "--browser.gatherUsageStats", "false"],
        cwd=PASTA, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=dict(os.environ, EXTRATOR_SEM_GUIA="1"))
    for _ in range(60):
        if not porta_livre(PORTA):
            time.sleep(2)
            return proc
        time.sleep(1)
    proc.terminate()
    raise RuntimeError("Streamlit nao subiu na porta %d" % PORTA)


class Gravador:
    """Junta as fotos de um passo e grava o GIF."""

    def __init__(self, pagina):
        self.pagina = pagina
        self.quadros = []
        self.recorte = None

    def mirar(self, titulo, altura=520):
        """Enquadra a etapa: rola ate o titulo e recorta dali para baixo.

        Sem isso o GIF sai com o topo da pagina, e nao com a etapa que o passo
        explica -- o Streamlit rola dentro de um container proprio.
        """
        alvo = self.pagina.get_by_text(titulo).first
        # 'block: start' leva o titulo para o TOPO da janela; o
        # scroll_into_view_if_needed costuma deixa-lo rente ao rodape, e ai o
        # recorte pegava uma faixa de 30 pixels.
        alvo.evaluate("e => e.scrollIntoView({block: 'start'})")
        self.pagina.wait_for_timeout(800)
        caixa = alvo.bounding_box()
        if not caixa:
            self.recorte = None
            return
        topo = max(caixa["y"] - 30, 0)
        sobra = ALTURA - topo
        if sobra < 200:                  # nao deu para rolar (fim da pagina)
            topo = max(ALTURA - altura, 0)
            sobra = ALTURA - topo
        self.recorte = {"x": 0, "y": topo, "width": LARGURA,
                        "height": min(altura, sobra)}

    def foto(self, espera=0.9):
        from PIL import Image
        import io as _io
        time.sleep(espera)
        img = Image.open(_io.BytesIO(self.pagina.screenshot(
            type="png", clip=getattr(self, "recorte", None))))
        # reduz para caber na janela do guia sem o usuario rolar a imagem
        img = img.resize((LARGO_GIF, round(img.height * LARGO_GIF / img.width)),
                         Image.LANCZOS)
        self.quadros.append(img.convert("P", palette=1))

    def salvar(self, nome, duracao=1400):
        if not self.quadros:
            return
        os.makedirs(DESTINO, exist_ok=True)
        caminho = os.path.join(DESTINO, nome + ".gif")
        primeiro, resto = self.quadros[0], self.quadros[1:]
        # o ultimo quadro fica mais tempo: e o resultado da acao
        tempos = [duracao] * len(self.quadros)
        tempos[-1] = duracao * 2
        primeiro.save(caminho, save_all=True, append_images=resto,
                      duration=tempos, loop=0, optimize=True)
        self.quadros = []
        print("  %s (%d quadros, %.1f KB)"
              % (nome, len(tempos), os.path.getsize(caminho) / 1024))


def _clicar_texto(p, texto, exato=False):
    alvo = p.get_by_role("button", name=texto, exact=exato).first
    alvo.scroll_into_view_if_needed()
    alvo.click()
    p.wait_for_timeout(1200)


def gravar(passos=None):
    from playwright.sync_api import sync_playwright

    if not os.path.isdir(DEMO):
        raise SystemExit("Sem massa de demonstracao. Rode antes: py testes/gerar_demo.py")
    # A janela do guia nao pode atrapalhar a gravacao. Nesta versao publica o
    # app nao grava marca em disco (o guia abre a cada sessao), entao quem
    # silencia o guia e a variavel de ambiente lida pelo proprio app.
    os.environ["EXTRATOR_SEM_GUIA"] = "1"

    # copia a massa para o caminho neutro que vai aparecer na tela
    if os.path.isdir(DEMO_NA_TELA):
        shutil.rmtree(DEMO_NA_TELA)
    shutil.copytree(DEMO, DEMO_NA_TELA)

    proc = subir_app()
    try:
        with sync_playwright() as pw:
            nav = pw.chromium.launch()
            pagina = nav.new_page(viewport={"width": LARGURA, "height": ALTURA},
                                  device_scale_factor=1)
            pagina.goto("http://localhost:%d" % PORTA, wait_until="networkidle")
            pagina.wait_for_timeout(3000)
            g = Gravador(pagina)
            quer = (lambda nome: not passos or nome in passos)

            # --- 1. tipo de migracao
            if quer("01-tipo"):
                g.mirar("1. Tipo de migração", 420)
                g.foto()
                pagina.get_by_role("combobox").first.click()
                g.foto()
                pagina.get_by_role("option", name="XML do eSocial").click()
                g.foto(2.0)
                g.salvar("01-tipo")
            else:
                pagina.get_by_role("combobox").first.click()
                pagina.get_by_role("option", name="XML do eSocial").click()
                pagina.wait_for_timeout(2000)

            # a etapa 3 agora comeca vazia; o guia mostra a tela com tudo marcado
            pagina.get_by_text("3. Layouts a gerar").first.scroll_into_view_if_needed()
            pagina.get_by_test_id("stCheckbox").get_by_text(
                "Selecionar todos").click()
            pagina.wait_for_timeout(3000)

            # --- 2. layouts preenchidos pelo cliente (o caminho de volta)
            if quer("02-preenchidos"):
                g.mirar("2. Layouts preenchidos pelo cliente", 340)
                g.foto()
                pagina.get_by_text("Abrir — enviar o Excel preenchido").first.click()
                g.foto(1.4)
                g.salvar("02-preenchidos")
                pagina.get_by_text("Abrir — enviar o Excel preenchido").first.click()

            # --- 3. layouts a gerar
            if quer("03-layouts"):
                g.mirar("3. Layouts a gerar", 460)
                g.foto()
                g.foto(0.5)
                g.salvar("03-layouts")

            # --- 4. ler a pasta de demonstracao
            campo = pagina.get_by_role("textbox", name="Caminho da pasta").first
            campo.scroll_into_view_if_needed()
            if quer("04-ler"):
                g.mirar("4. Arquivos XML", 560)
                g.foto()
                campo.click()
                campo.type(DEMO_NA_TELA, delay=25)
                g.foto(0.4)
            else:
                campo.fill(DEMO_NA_TELA)
            campo.press("Enter")
            pagina.wait_for_timeout(2500)
            if quer("04-ler"):
                g.foto()
                _clicar_texto(pagina, "Ler a pasta")
                pagina.wait_for_timeout(2500)
                g.foto(1.5)
                g.salvar("04-ler")
            else:
                _clicar_texto(pagina, "Ler a pasta")
                pagina.wait_for_timeout(3000)

            # --- 5. De/Para do cliente
            if quer("05-depara"):
                g.mirar("5. De/Para preenchido pelo cliente", 560)
                g.foto(2.0)
                g.foto(0.6)
                g.salvar("05-depara")

            # --- 6. gerar os layouts
            pagina.get_by_text("6. Gerar os layouts").first.scroll_into_view_if_needed()
            if quer("06-gerar"):
                g.mirar("6. Gerar os layouts", 520)
                g.foto()
                _clicar_texto(pagina, "Gerar layouts Senior")
                pagina.wait_for_timeout(3500)
                g.foto(1.5)
                g.foto(0.6)
                g.salvar("06-gerar")
            else:
                _clicar_texto(pagina, "Gerar layouts Senior")
                pagina.wait_for_timeout(4000)

            # --- 7. layouts complementares
            if quer("07-complementar"):
                g.mirar("Baixar todos os layouts", 460)
                g.foto()
                _clicar_texto(pagina, "Gerar layouts complementares")
                pagina.wait_for_timeout(3500)
                g.foto(1.5)
                g.foto(0.6)
                g.salvar("07-complementar")

            # --- 8. pendencias e diagnostico
            if quer("08-conferir"):
                pagina.get_by_role("tab", name="Pendencias").click()
                g.mirar("Pendencias", 520)
                g.foto(1.2)
                pagina.get_by_role("tab", name="Diagnostico").click()
                g.foto(1.2)
                g.salvar("08-conferir")

            nav.close()
    finally:
        if proc:
            proc.terminate()
        shutil.rmtree(DEMO_NA_TELA, ignore_errors=True)   # nao deixa copia no disco


if __name__ == "__main__":
    gravar(set(sys.argv[1:]) or None)
    print("GIFs em", DESTINO)
