#!/usr/bin/env python3
"""Конфигурация секретов для пайплайна.

Значения секретов НИКОГДА не хранятся в репозитории. Источник — Azure Key Vault:
имя хранилища и имена секретов задаются переменными окружения, поэтому карта
инфраструктуры тоже не попадает в git. См. .env.example.

Порядок разрешения для ключа FOO:
  1. переменная окружения FOO — готовое значение (локальный прогон, CI);
  2. Key Vault: хранилище KEYVAULT_NAME, имя секрета из FOO_SECRET.
"""
import os
import subprocess

VAULT = os.environ.get("KEYVAULT_NAME")

# Реестр фактически выданных значений. Нужен, чтобы санитайзер логов и алёртов
# знал, что именно вычищать: в проде секреты приходят из Key Vault, и в
# os.environ их нет — маскировка «по окружению» там не сработала бы вовсе.
_issued = {}


def issued_secrets():
    """Значения секретов, выданные за время работы процесса."""
    return [v for v in _issued.values() if v]


def secret(key):
    """Вернуть значение секрета по логическому имени key."""
    direct = os.environ.get(key)
    if direct:
        _issued[key] = direct
        return direct

    name = os.environ.get(f"{key}_SECRET")
    if not name:
        raise RuntimeError(
            f"{key}: задайте переменную {key} со значением "
            f"или {key}_SECRET с именем секрета в Key Vault")
    if not VAULT:
        raise RuntimeError(
            f"{key}_SECRET задан, но нет KEYVAULT_NAME — неизвестно, из какого "
            f"хранилища читать")

    value = subprocess.check_output(
        ["az", "keyvault", "secret", "show", "--vault-name", VAULT,
         "--name", name, "--query", "value", "-o", "tsv"], text=True).strip()
    _issued[key] = value
    return value
