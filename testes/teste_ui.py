# -*- coding: utf-8 -*-
r"""Exercita a interface de verdade (widgets, session_state, botoes) sem navegador.

Uso:  py testes/teste_ui.py [pasta_com_xmls]
Sem argumento, usa a variavel EXTRATOR_MASSA ou exemplos/massa_demo.
Criterio de sucesso: 0 exceptions em todas as etapas e "OK" no final.
"""
import io, os, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(P); sys.path.insert(0, P)

from streamlit.testing.v1 import AppTest

PASTA = (sys.argv[1] if len(sys.argv) > 1 else
         os.environ.get("EXTRATOR_MASSA",
                        os.path.join(P, "exemplos", "massa_demo")))


def exceptions(at, etapa):
    print("%s — exceptions: %d" % (etapa, len(at.exception)))
    for e in at.exception:
        print("   !!", e.value)
    return len(at.exception) == 0


at = AppTest.from_file(os.path.join(P, "app.py"), default_timeout=900)
at.run()
exceptions(at, "1) carga inicial")
print("   titulo:", at.title[0].value if at.title else "(sem titulo)")

# ---- origem sem extracao: so o De/Para ----
at.selectbox[0].set_value("Base Datasul").run()
exceptions(at, "\n2) Datasul")
alvo = [b for b in at.button if "De/Para" in b.label]
if alvo:
    alvo[0].click().run()
    exceptions(at, "   apos gerar De/Para")
    print("   downloads:", [d.label for d in at.get("download_button")])

# ---- origem eSocial: fluxo completo ----
at = AppTest.from_file(os.path.join(P, "app.py"), default_timeout=900)
at.run()
at.selectbox[0].set_value("XML do eSocial").run()
exceptions(at, "\n3) eSocial")

at.text_input[0].set_value(PASTA).run()
exceptions(at, "\n4) pasta informada: " + PASTA)

alvo = [b for b in at.button if "Ler a pasta" in b.label]
if not alvo:
    print("   !! botao 'Ler a pasta' nao apareceu"); sys.exit(1)
alvo[0].click().run()
exceptions(at, "\n5) pasta lida")
print("   metricas:", [(m.label, m.value) for m in at.metric][:4])

alvo = [b for b in at.button if "Gerar layouts" in b.label]
if not alvo:
    print("   !! botao 'Gerar layouts' nao apareceu"); sys.exit(1)
alvo[0].click().run()
ok = exceptions(at, "\n6) layouts gerados")
metricas_pasta = [(m.label, m.value) for m in at.metric][-6:]
print("   metricas:", metricas_pasta)
print("   downloads:", len(at.get("download_button")))

# ---- salvar a leitura e reabrir sem ler os XMLs ----
import tempfile
arquivo = os.path.join(tempfile.mkdtemp(), "teste_ui.leitura")
destino = [t for t in at.text_input if t.label == "Gravar em"]
salvar = [b for b in at.button if b.label == "Salvar esta leitura"]
if not (destino and salvar):
    print("   !! opcao de salvar a leitura nao apareceu"); sys.exit(1)
destino[0].set_value(arquivo).run()
[b for b in at.button if b.label == "Salvar esta leitura"][0].click().run()
ok = exceptions(at, "\n7) leitura salva") and ok

at = AppTest.from_file(os.path.join(P, "app.py"), default_timeout=900)
at.run()
at.selectbox[0].set_value("XML do eSocial").run()
at.radio[0].set_value("Leitura salva").run()
at.text_input[0].set_value(arquivo).run()
[b for b in at.button if "Carregar a leitura" in b.label][0].click().run()
ok = exceptions(at, "\n8) leitura carregada") and ok
[b for b in at.button if "Gerar layouts" in b.label][0].click().run()
ok = exceptions(at, "   layouts gerados da leitura salva") and ok
metricas_leitura = [(m.label, m.value) for m in at.metric][-6:]
print("   metricas:", metricas_leitura)
if metricas_leitura != metricas_pasta:
    print("   !! resultado diferente do da pasta"); ok = False
os.remove(arquivo)

print("\nOK" if ok else "\nFALHOU")
sys.exit(0 if ok else 1)
