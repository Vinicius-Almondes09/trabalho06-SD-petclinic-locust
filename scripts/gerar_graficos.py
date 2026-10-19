from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / 'results' / 'tabelas' / 'resumo_por_cenario.csv'
SAIDA = RAIZ / 'results' / 'graficos'
CENARIOS = [('A', 30), ('B', 80), ('C', 150)]
PERFIS = [('leitura', 'Leitura'), ('escrita', 'Escrita')]

METRICAS = [
    ('01_tempo_medio.png', 'tempo_medio_ms', 'Tempo médio de resposta', 'Tempo médio (ms)'),
    ('02_p95.png', 'p95_ms', 'Tempo de resposta P95', 'P95 (ms)'),
    ('03_vazao.png', 'requisicoes_s', 'Vazão', 'Requisições por segundo'),
    ('04_taxa_falhas.png', 'falhas_percentual', 'Taxa de falhas', 'Falhas (%)'),
    ('05_total_requisicoes.png', 'requisicoes', 'Total médio de requisições por repetição', 'Requisições'),
    ('06_cpu_customers.png', 'cpu_customers', 'Uso de CPU — customers-service', 'CPU Docker (%)'),
    ('07_cpu_vets.png', 'cpu_vets', 'Uso de CPU — vets-service', 'CPU Docker (%)'),
    ('08_cpu_gateway.png', 'cpu_gateway', 'Uso de CPU — api-gateway', 'CPU Docker (%)'),
]


def ler_dados():
    if not ENTRADA.is_file():
        raise FileNotFoundError(f'Tabela não encontrada: {ENTRADA}. Execute analisar_resultados.py primeiro.')
    with ENTRADA.open(encoding='utf-8-sig', newline='') as arquivo:
        linhas = list(csv.DictReader(arquivo))
    if not linhas:
        raise ValueError('A tabela consolidada está vazia.')
    dados = {}
    for linha in linhas:
        chave = (linha['perfil'].strip().lower(), linha['cenario'].strip().upper())
        if chave in dados:
            raise ValueError(f'Configuração duplicada: {chave}')
        if int(linha['repeticoes']) != 10:
            raise ValueError(f'Esperadas 10 repetições para {chave}, encontradas {linha["repeticoes"]}.')
        dados[chave] = linha
    for perfil, _ in PERFIS:
        for cenario, _ in CENARIOS:
            if (perfil, cenario) not in dados:
                raise ValueError(f'Configuração ausente: {(perfil, cenario)}')
    return dados


def criar_grafico(dados, nome, campo, titulo, eixo_y):
    fig, ax = plt.subplots(figsize=(9, 5.3))
    posicoes = list(range(len(CENARIOS)))
    largura = 0.36
    barras = []
    for indice, (perfil, rotulo) in enumerate(PERFIS):
        valores = [float(dados[(perfil, cenario)][campo]) for cenario, _ in CENARIOS]
        xs = [p + (indice - 0.5) * largura for p in posicoes]
        barras.append(ax.bar(xs, valores, width=largura, label=rotulo))
    ax.set_title(titulo, fontsize=14, fontweight='bold')
    ax.set_ylabel(eixo_y)
    ax.set_xlabel('Cenário (usuários simultâneos)')
    ax.set_xticks(posicoes, [f'{cenario} ({usuarios})' for cenario, usuarios in CENARIOS])
    ax.set_ylim(bottom=0)
    ax.grid(axis='y', alpha=0.25)
    ax.set_axisbelow(True)
    ax.legend()
    for conjunto in barras:
        ax.bar_label(conjunto, padding=3, fmt='%.1f', fontsize=8)
    fig.tight_layout()
    destino = SAIDA / nome
    fig.savefig(destino, dpi=180, bbox_inches='tight')
    plt.close(fig)
    print(f'Gerado: {destino.relative_to(RAIZ)}')


def main():
    dados = ler_dados()
    SAIDA.mkdir(parents=True, exist_ok=True)
    for metrica in METRICAS:
        criar_grafico(dados, *metrica)
    print(f'Concluído: {len(METRICAS)} gráficos PNG criados.')


if __name__ == '__main__':
    main()
