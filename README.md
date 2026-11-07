# AltRouter

AltRouter превращает обычный ПК с ОС Debian 13 в полноценный домашний роутер.
Панель управляет сетевыми интерфейсами, маршрутизацией и файрволом.
Дизайн и логика вдохновлены Keenetic.
Backend — FastAPI (uvicorn, HTTPS), frontend — Vue 3 + Vite. Без поддержки Wi-Fi.

Возможности: настройка физических интерфейсов (WAN/LAN), LAN-сегменты с мостами и DHCP,
PPPoE, multi-WAN с приоритетами и Ping Check, статические маршруты, файрвол «из зоны» с
переадресацией портов, локальный DNS, WireGuard, мониторинг (снапшоты, графики),
диагностика (ping/traceroute/tcpdump/журнал), пользователи панели, резервные копии,
обновления системы и питание.

Все изменения сети применяются транзакционно: после применения есть интервал
подтверждения, при истечении — автоматический откат (защита от потери доступа).

## Структура

```
backend/   FastAPI-приложение (app/), тесты pytest (tests/)
frontend/  Vue 3 + Vite (исходники; dist/ собирается при установке)
deploy/    install.sh, deploy.ps1, root-хелперы, sudoers, sysctl
docs/      руководство по развёртыванию, руководство пользователя, формат конфигурации
```

## Требования

- Чистый Debian 13 и root-доступ (sudo).
- Порт веб-панели — от 1024 (панель работает от непривилегированного пользователя `altrouter`).
- Для установки с Windows-машины: OpenSSH-доступ к серверу по ключу, PowerShell, npm.

## Установка на Debian 13

Скопируйте проект на сервер (например, через `scp -r` или git clone) и выполните:

```bash
sudo bash deploy/install.sh /путь/к/копии/проекта
```

Установщик сам:

- поставит нужные apt-пакеты (sudo, python3-venv, python3-pip, openssl, curl, nftables,
  dnsmasq, wireguard-tools, ppp, traceroute, tcpdump) — только недостающие;
- создаст пользователя `altrouter` и каталоги `/opt/altrouter`, `/etc/altrouter`;
- развернёт backend (venv + pip-зависимости) и frontend (статика из `frontend/dist`);
- создаст администратора панели (argon2-хеш в `/etc/altrouter/config.json`, chmod 600);
- сгенерирует самоподписанный HTTPS-сертификат;
- поставит root-хелперы (`/usr/local/sbin/altrouter-netapply`, `altrouter-ssh`),
  sudoers-правило и sysctl-профиль (IP-форвардинг);
- сгенерирует и запустит systemd-юнит `altrouter.service`, проверит health.

Повторный запуск безопасен: `config.json`, сертификат и сетевые настройки не перезаписываются.

### Вопросы интерактивной установки

| Вопрос | По умолчанию |
|---|---|
| Порт веб-интерфейса (HTTPS) | 9000 (допустимо 1024–65535) |
| Адрес привязки панели | 0.0.0.0 |
| Логин администратора | admin |
| Пароль администратора | генерируется (Enter = 16 символов, показан в конце установки) |
| IP/домен для HTTPS-сертификата (SAN) | IP сервера по default route |

Управляющий интерфейс (защищён от изменения в панели) определяется автоматически —
это интерфейс с default route. Переопределить: `ALTROUTER_MGMT_IFACE`.

### Неинтерактивная установка

Если stdin не терминал (например, при запуске из скрипта), вопросы не задаются —
значения берутся из переменных окружения:

```bash
sudo ALTROUTER_PORT=9000 \
     ALTROUTER_ADMIN_USER=admin \
     ALTROUTER_ADMIN_PASSWORD='секрет' \
     ALTROUTER_CERT_SAN=192.168.1.10 \
     bash deploy/install.sh /путь/к/проекту
```

Доступны: `ALTROUTER_PORT`, `ALTROUTER_BIND`, `ALTROUTER_MGMT_IFACE`,
`ALTROUTER_ADMIN_USER`, `ALTROUTER_ADMIN_PASSWORD`, `ALTROUTER_CERT_SAN`.

### Установка с Windows (deploy.ps1)

`deploy/deploy.ps1` собирает фронтенд, упаковывает проект, передаёт на сервер по SSH
и запускает установщик:

```powershell
.\deploy\deploy.ps1 -Server 192.168.1.10 -User linadmin -SudoPassword 'секрет' -Port 9000
```

Параметры: `-Server`, `-User`, `-Key` (путь к приватному ключу, по умолчанию
`~\.ssh\id_ed25519`), `-SudoPassword` (или env `ALTROUTER_SUDO_PW`), `-Port`,
`-SkipBuild`. Доступ к sudo по ключу должен работать без пароля (NOPASSWD).

### Сборка фронтенда вручную

install.sh публикует статику из `frontend/dist`. Если вы изменили исходники фронта
или скопировали проект без `dist`:

```bash
cd frontend
npm ci
npm run build   # результат в frontend/dist
```

## После установки

- Панель: `https://<ip-сервера>:9000` (обязательно **https**; сертификат самоподписанный —
  примите предупреждение браузера).
- Health-check: `https://<ip-сервера>:9000/api/health`.
- Логин/пароль — заданы при установке (сгенерированный пароль показывается в итогах).
- Логи: `journalctl -u altrouter`.

## Документация

- [Руководство по развёртыванию](docs/руководство-по-развёртыванию.md)
- [Руководство пользователя](docs/руководство-пользователя.md)
- [Формат конфигурации](docs/формат-конфигурации.md)

## Тесты

```bash
cd backend
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 -m pytest tests -q
```

## Лицензия

Проект распространяется свободно по лицензии [MIT](LICENSE).
Автор: **Explorerr10**. Разрешены использование, копирование, изменение и
распространение, в том числе в коммерческих проектах, при сохранении
уведомления об авторских правах и текста лицензии.

## Удаление

```bash
sudo systemctl disable --now altrouter
sudo rm -rf /opt/altrouter /etc/altrouter /etc/systemd/system/altrouter.service \
            /etc/sudoers.d/altrouter /usr/local/sbin/altrouter-netapply \
            /usr/local/sbin/altrouter-ssh /etc/sysctl.d/90-altrouter.conf
sudo userdel -r altrouter
```
