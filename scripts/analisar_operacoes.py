from pathlib import Path
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
CSV_DIR = RAIZ / "results" / "csv"
TABELAS = RAIZ / "results" / "tabelas"
GRAFICOS = RAIZ / "results" / "graficos"
PADRAO = re.compile(r"^(leitura|escrita)_cenario_([ABC])_(30|80|150)u_rep_(\d{2})_stats\.csv$")
OPERACOES = ["GET /owners", "GET /owners/{id}", "GET /vets", "POST /owners"]
METRICAS = {
    "tempo_medio_ms": ("09_tempo_medio_por_operacao.png", "Tempo médio por operação", "Tempo médio (ms)"),
    "p95_ms_media": ("10_p95_por_operacao.png", "Média dos P95 por operação", "P95 médio entre repetições (ms)"),
    "falhas_percentual": ("11_falhas_por_operacao.png", "Taxa de falhas por operação", "Falhas (%)"),
}


def numero(valor):
    return pd.to_numeric(valor, errors="coerce")


def carregar():
    registros = []
    arquivos = sorted(CSV_DIR.glob("*_stats.csv"))
    for caminho in arquivos:
        m = PADRAO.fullmatch(caminho.name)
        if not m:
            continue
        perfil, cenario, usuarios, repeticao = m.groups()
        dados = pd.read_csv(caminho, encoding="utf-8-sig")
        for coluna in ["Name", "Request Count", "Failure Count", "Average Response Time", "95%"]:
            if coluna not in dados.columns:
                raise ValueError(f"{caminho.name}: coluna ausente: {coluna}")
        dados = dados[dados["Name"].isin(OPERACOES)]
        if len(dados) != len(OPERACOES) or dados["Name"].duplicated().any():
            raise ValueError(f"{caminho.name}: esperado exatamente um registro por operação")
        for _, linha in dados.iterrows():
            requisicoes = numero(linha["Request Count"])
            falhas = numero(linha["Failure Count"])
            media = numero(linha["Average Response Time"])
            p95 = numero(linha["95%"])
            if pd.isna(requisicoes) or pd.isna(falhas) or pd.isna(media) or pd.isna(p95):
                raise ValueError(f"{caminho.name}: métrica inválida em {linha['Name']}")
            if requisicoes < 1 or falhas < 0 or falhas > requisicoes:
                raise ValueError(f"{caminho.name}: contagem inválida em {linha['Name']}")
            registros.append({
                "perfil": perfil, "cenario": cenario, "usuarios": int(usuarios),
                "repeticao": int(repeticao), "operacao": linha["Name"],
                "requisicoes": int(requisicoes), "falhas": int(falhas),
                "tempo_medio_ms": float(media), "p95_ms": float(p95),
            })
    base = pd.DataFrame(registros)
    if len(base) != 240:
        raise ValueError(f"Esperados 240 registros (60 repetições × 4 operações); encontrados {len(base)}")
    checagem = base.groupby(["perfil", "cenario", "usuarios"])["repeticao"].nunique()
    if len(checagem) != 6 or not (checagem == 10).all():
        raise ValueError(f"Repetições incompletas por configuração: {checagem.to_dict()}")
    return base


def consolidar(base):
    saida = []
    for (perfil, cenario, usuarios, operacao), grupo in base.groupby(
        ["perfil", "cenario", "usuarios", "operacao"], sort=True
    ):
        req = int(grupo["requisicoes"].sum())
        falhas = int(grupo["falhas"].sum())
        # Média global ponderada por volume de requisições; P95 não é agregável
        # dessa forma, então apresentamos a média dos dez P95 individuais.
        tempo = float(np.average(grupo["tempo_medio_ms"], weights=grupo["requisicoes"]))
        saida.append({
            "perfil": perfil, "cenario": cenario, "usuarios": usuarios,
            "operacao": operacao, "repeticoes": len(grupo),
            "requisicoes_total": req, "falhas_total": falhas,
            "tempo_medio_ms": round(tempo, 4),
            "p95_ms_media": round(float(grupo["p95_ms"].mean()), 4),
            "falhas_percentual": round(100 * falhas / req, 4),
        })
    return pd.DataFrame(saida)


def grafico(resumo, metrica, nome, titulo, rotulo):
    fig, eixos = plt.subplots(1, 2, figsize=(15, 6), sharey=True)
    for eixo, perfil in zip(eixos, ["leitura", "escrita"]):
        parte = resumo[resumo["perfil"] == perfil]
        xs = np.arange(3)
        largura = 0.19
        for idx, operacao in enumerate(OPERACOES):
            valores = []
            for cenario in "ABC":
                linha = parte[(parte["cenario"] == cenario) & (parte["operacao"] == operacao)]
                valores.append(float(linha.iloc[0][metrica]))
            eixo.bar(xs + (idx - 1.5) * largura, valores, largura, label=operacao)
        eixo.set_title(f"Perfil {perfil.capitalize()}")
        eixo.set_xticks(xs, ["A — 30", "B — 80", "C — 150"])
        eixo.set_xlabel("Cenário — usuários")
        eixo.grid(axis="y", alpha=.25)
    eixos[0].set_ylabel(rotulo)
    handles, labels = eixos[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, bbox_to_anchor=(0.5, 0.015))
    fig.suptitle(titulo, fontsize=14, fontweight="bold")
    fig.tight_layout(rect=(0, .075, 1, .94))
    caminho = GRAFICOS / nome
    fig.savefig(caminho, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Gerado: {caminho.relative_to(RAIZ)}")


def main():
    if not CSV_DIR.is_dir():
        raise SystemExit(f"Pasta não encontrada: {CSV_DIR}")
    TABELAS.mkdir(parents=True, exist_ok=True)
    GRAFICOS.mkdir(parents=True, exist_ok=True)
    base = carregar()
    resumo = consolidar(base)
    destino = TABELAS / "resumo_por_operacao.csv"
    resumo.to_csv(destino, index=False, encoding="utf-8-sig")
    print(f"Tabela gerada: {destino.relative_to(RAIZ)}")
    for metrica, (nome, titulo, rotulo) in METRICAS.items():
        grafico(resumo, metrica, nome, titulo, rotulo)
    print("Concluído: 60 execuções, 24 combinações operação/cenário e 3 gráficos.")
    print("Nota: P95 = média dos P95 das dez repetições, não P95 agrupado de todas as requisições.")


if __name__ == "__main__":
    main()
