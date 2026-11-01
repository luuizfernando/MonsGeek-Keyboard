# MonsGeek Keyboard — Monitor de bateria

Monitor de bateria para o **MonsGeek 2.4G Wireless Keyboard** no Windows.

O software oficial do teclado não mostra o nível da bateria de forma prática no modo 2.4 GHz. Este app fica na bandeja do sistema, mostra a porcentagem atual, avisa quando a bateria está acabando e guarda um histórico para acompanhar a descarga ao longo dos dias.

## Funcionalidades

- **Ícone na bandeja com a porcentagem atual**, colorido conforme o nível:

  | Cor | Situação |
  |---|---|
  | Azul | Carregando |
  | Verde | Acima de 30% |
  | Laranja | De 10% a 30% |
  | Vermelho | Abaixo de 10% |
  | Cinza `?` | Sem leitura (receptor ausente ou teclado ainda não reportou) |

  Quando a última leitura falha, o ícone fica mais escuro, indicando que o valor pode estar desatualizado.
- **Notificação de bateria baixa** quando o nível cai abaixo de 10%. Ela aparece uma vez só e volta a valer depois que a bateria passa de 15% ou o teclado é carregado.
- **Histórico em SQLite**: uma gravação a cada 10 minutos ou sempre que o nível muda.
- **Página de histórico** (menu *Abrir histórico*): gráfico de descarga com filtros de 24 h, 7 dias, 30 dias e tudo, além da taxa de descarga atual (%/dia) e uma estimativa de quantos dias faltam.
- **Menu da bandeja**: *Atualizar agora*, *Abrir histórico* e *Sair*.

## Como funciona

O app conversa com o **receptor USB 2.4G** (VID `0x3151`, PID `0x5026`) pela interface HID de comandos do fabricante (usage page `0xFFFF`, usage `0x02`).

A cada 60 segundos ele envia o comando `GET_DONGLE_STATUS` (`0xF7`). Esse comando é respondido pelo próprio receptor, com o último nível que o teclado informou. Nada é transmitido pelo rádio até o teclado, então consultar com frequência **não gasta a bateria do teclado**.

Na resposta, o byte 3 traz o nível (0 a 100) e o byte 4 indica se está carregando. Logo depois de o receptor ser conectado, o nível vem como 0 até o teclado mandar o primeiro valor. Nesse caso o app mostra "sem leitura".

O protocolo foi baseado na documentação do projeto [monsgeek-akko-linux](https://github.com/echtzeit-solutions/monsgeek-akko-linux) (`docs/PROTOCOL.md`).

## Requisitos

- Windows 10 ou 11
- Python 3.10 ou mais recente
- Teclado no modo 2.4 GHz, com o receptor USB conectado

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

O `requirements.txt` instala as dependências do app (`hidapi`, `pystray`, `Pillow`), os pacotes WinRT usados pelo `probe.py` (instalados somente no Windows) e o `pytest`.

## Uso

### Iniciar o app

Na pasta do projeto, rode:

```powershell
.venv\Scripts\pythonw.exe battery_monitor.py
```

O app abre **sem nenhuma janela**: ele aparece só como um ícone com a porcentagem na bandeja do sistema, perto do relógio. Se o ícone não aparecer, clique na setinha `^` da barra de tarefas, onde o Windows esconde os ícones extras. Arraste o ícone para a barra para deixá-lo sempre visível.

Para fechar o app, clique com o botão direito no ícone e escolha **Sair**.

> Use o `pythonw.exe` do `.venv`. O `pythonw` (com **w**) roda sem abrir a janela do terminal, e o do `.venv` é o que tem as dependências instaladas.

### Testar a leitura no terminal

Faz uma única leitura e mostra o resultado, sem abrir a bandeja:

```powershell
.venv\Scripts\python.exe battery_monitor.py --once
```

A saída esperada é algo como `Reading(level=85, charging=False)`.

### Iniciar junto com o Windows

1. Pressione `Win + R`, digite `shell:startup` e confirme. Isso abre a pasta de inicialização.
2. Clique com o botão direito na pasta e escolha **Novo > Atalho**.
3. No local do item, informe os caminhos completos do `pythonw.exe` e do script, por exemplo:
   ```
   "C:\caminho\do\projeto\.venv\Scripts\pythonw.exe" "C:\caminho\do\projeto\battery_monitor.py"
   ```
4. Dê um nome ao atalho, por exemplo *Bateria MonsGeek*, e conclua.

### Onde ficam os dados

Em `%LOCALAPPDATA%\KeyboardBattery\`:

- `history_24g.db`: histórico das leituras (SQLite)
- `historico.html`: página do gráfico, gerada ao abrir o histórico

### Configurações

As constantes ficam no início de `battery_monitor.py`:

| Constante | Padrão | Descrição |
|---|---|---|
| `POLL_SECONDS` | `60` | Intervalo entre as leituras |
| `RECORD_EVERY_SECONDS` | `600` | Intervalo mínimo entre gravações quando o nível não muda |
| `LOW_THRESHOLD` | `10` | Nível (%) abaixo do qual a notificação aparece |
| `RESET_THRESHOLD` | `15` | Nível (%) a partir do qual a notificação volta a valer |

## Scripts de diagnóstico

Foram usados para descobrir como ler a bateria e continuam úteis para investigar problemas:

- **`hid_probe.py`**: lista os dispositivos HID e, nas interfaces do receptor, mostra os feature reports e os input reports recebidos. Só lê, não envia comandos.
  ```bash
  python hid_probe.py              # testa os receptores conhecidos
  python hid_probe.py 3151 5026    # testa um VID/PID específico
  ```
- **`probe.py`**: lista os dispositivos Bluetooth pareados e verifica se eles oferecem o Battery Service padrão (GATT `0x180F`). Serve para o modo Bluetooth.

## Testes

```bash
python -m pytest
```

Os testes não precisam do teclado conectado: o acesso ao HID, à bandeja e ao relógio é simulado. Eles cobrem o protocolo do receptor, o histórico, o cálculo da taxa de descarga, a página do gráfico, as cores do ícone, o texto da bandeja e a lógica de notificação.

## Solução de problemas

**As luzes do teclado acendem, mas as teclas não digitam.** O teclado perdeu o pareamento com o receptor. Segure **Fn + Y** por 3 a 5 segundos, com o receptor conectado, até a luz parar de piscar.

**O ícone mostra `?` (sem leitura).**
- Confira se o receptor está conectado e se o teclado está no modo 2.4 GHz.
- Depois de reconectar o receptor, pressione alguma tecla: o nível só aparece quando o teclado manda o primeiro valor.
- Rode `.venv\Scripts\python.exe battery_monitor.py --once` para ver a leitura direto no terminal.

## Licença

[MIT](LICENSE)
