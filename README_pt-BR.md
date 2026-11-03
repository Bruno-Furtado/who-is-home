<p align="center">
  🇺🇸 <a href="README.md">English</a> · 🇧🇷 <b>Português</b> · 🇨🇳 <a href="README_zh-CN.md">中文</a>
</p>

# who-is-home

**Quem está na rede de casa, quanto usa e o que acessa.** Roda no mesmo computador ligado 24h que já roda o [AdGuard Home](https://github.com/AdguardTeam/AdGuardHome) e, de preferência, o [down-again](https://github.com/Bruno-Furtado/down-again), e mostra tudo num painel no celular.

## Recursos

- 🟢 **Aparelhos ao vivo**: quem está ligado agora, desde quando e quando foi visto pela última vez.
- 🏷️ **Nomes de verdade**: descobre nomes por Bonjour (mDNS), NetBIOS e pelos clientes do AdGuard; você renomeia e escolhe o tipo (celular, TV, videogame…).
- ⏱️ **Tempo de uso estimado** por aparelho, por hora do dia e por categoria (redes sociais, vídeo, jogos, trabalho…).
- 🌐 **Sites mais acessados** e **bloqueados** (anúncios e rastreadores), por aparelho e no total.
- 🌙 **Uso de madrugada**: quem usou a internet entre 0h e 6h.
- 🔔 **Avisos no celular** (ntfy): aparelho novo na rede e resumo da semana no domingo à noite.
- 📶 **Internet**: status, quedas e velocidade vindos do down-again.
- 🪶 **Zero dependências**: só Python 3.8+. O painel funciona mesmo com a internet fora.

## Como funciona

1. **Varredura**: a cada minuto pinga a rede e lê a tabela ARP para saber quem está ligado.
2. **AdGuard Home**: lê o registro de consultas pela API e liga cada consulta ao aparelho (pelo MAC).
3. **Tempo de uso**: um minuto conta como "em uso" quando o aparelho consultou sites que não são tráfego automático do sistema (atualizações, iCloud, anúncios…).
4. **Painel**: `http://<nome-da-maquina>.local:8080`.

Só aparecem **nomes de sites**, nunca conteúdo, mensagens ou páginas (o HTTPS esconde o resto).

## Instalação

Pré-requisitos: AdGuard Home rodando nesta máquina e configurado como DNS da rede (no DHCP do roteador).

```bash
git clone https://github.com/Bruno-Furtado/who-is-home.git ~/who-is-home
cd ~/who-is-home
python3 who_is_home.py setup      # usuário e senha do AdGuard; oferece os mesmos avisos do down-again
python3 who_is_home.py check      # confere AdGuard, varredura e down-again
python3 who_is_home.py install    # inicia sozinho sempre que você entrar no Mac
```

<details>
<summary>Configuração (dados/config.json)</summary>

| Chave | Padrão | O que faz |
|---|---|---|
| `port` | `8080` | Porta do painel |
| `adguard_url` | `http://127.0.0.1:3000` | Endereço do AdGuard Home |
| `scan_seconds` | `60` | Intervalo da varredura da rede |
| `poll_seconds` | `15` | Intervalo de leitura do AdGuard |
| `offline_minutes` | `10` | Sem sinal por N minutos = desligado |
| `activity_min_queries` | `2` | Consultas num minuto para contar como uso |
| `keep_days` | `180` | Histórico guardado |
| `down_again_url` | `http://127.0.0.1:8000` | down-again (`""` esconde o cartão) |
| `ntfy_topic` | `""` | Tópico dos avisos (`""` desliga) |
| `notify_new_devices` | `true` | Aviso de aparelho novo |
| `weekly_summary`, `weekly_day`, `weekly_hour` | `true`, `6`, `20` | Resumo semanal (6 = domingo) |
| `night_from`, `night_to` | `0`, `6` | Janela de "madrugada" |
| `language` | `auto` | `pt`, `en`, `zh` (avisos e terminal) |

</details>

<details>
<summary>Limitações</summary>

- **Tempo de uso é estimado** pelas consultas de DNS. Apps que ficam conectados o tempo todo (WhatsApp, por exemplo) podem somar um pouco a mais.
- **DNS reserva**: se o roteador entrega um DNS secundário, parte das consultas passa por fora do AdGuard e não é contada.
- **MAC privado**: celulares podem trocar de endereço e aparecer como aparelho novo. Desative o "Endereço Wi-Fi privado" na rede de casa.
- **DNS próprio no aparelho** (DNS seguro do Chrome, Relay Privado do iCloud) foge do AdGuard.
- **IPv6**: se a rede entrega DNS por IPv6, os aparelhos podem usá-lo e escapar do registro.

</details>

## Privacidade

Os dados ficam só nesta máquina, em `dados/` (só o seu usuário lê). Se outras pessoas usam a rede, avise que os acessos ficam registrados.

O painel **não tem senha**: qualquer aparelho no seu Wi-Fi consegue abri-lo. Deixe visitas numa rede de convidados ou use `"bind": "127.0.0.1"` para abrir só na própria máquina. Nunca exponha a porta para a internet.

## Licença

MIT
