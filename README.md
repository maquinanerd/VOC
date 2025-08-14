# RSS to WordPress Automation App

Este é um aplicativo Python que lê feeds RSS, reescreve o conteúdo usando uma IA generativa (Gemini) e o publica automaticamente em um site WordPress.

## Funcionalidades

- Leitura de múltiplos feeds RSS em uma ordem definida.
- Extração de conteúdo completo de artigos (título, texto, imagens, vídeos).
- Reescrita de conteúdo otimizada para SEO via IA.
- Publicação automática no WordPress (título, conteúdo, resumo, categorias, tags, imagem destacada).
- Agendamento de tarefas com `APScheduler`.
- Gerenciamento de chaves de API com failover e rate limiting.
- Armazenamento de dados em SQLite para evitar duplicatas.
- Limpeza periódica de dados antigos.

## Instalação

1.  **Clone o repositório:**
    ```bash
    git clone <url-do-repositorio>
    cd <nome-do-repositorio>
    ```

2.  **Crie e ative um ambiente virtual:**
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # No Windows: .venv\Scripts\activate
    ```

3.  **Instale as dependências:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure as variáveis de ambiente:**
    Copie o arquivo `.env.example` para `.env` e preencha com suas credenciais e chaves de API.
    ```bash
    cp .env.example .env
    ```
    Edite o arquivo `.env` com seus dados.

## Execução

### Execução contínua (agendada)
O aplicativo irá rodar continuamente, verificando os feeds em intervalos definidos.
```bash
python -m app.main
```

### Execução única (para teste)
Para rodar o ciclo de pipeline apenas uma vez e sair:
```bash
python -m app.main --once
```

### Executando os testes
Para rodar os testes unitários:
```bash
make test
# ou
pytest
```

## Makefile

Comandos úteis disponíveis no `Makefile`:

- `make run`: Inicia o aplicativo em modo agendado.
- `make once`: Roda o pipeline uma vez.
- `make test`: Roda os testes.
- `make clean`: Limpa o banco de dados e os logs.