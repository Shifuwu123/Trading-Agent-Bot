import pytest
from tradingbot.utils.logger import sanitize_sensitive_data

def test_sanitize_telegram_token():
    raw = "Error sending to https://api.telegram.org/bot123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ12345678/sendMessage"
    sanitized = sanitize_sensitive_data(raw)
    assert "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ12345678" not in sanitized
    assert "bot***REDACTED_TELEGRAM_TOKEN***/sendMessage" in sanitized

def test_sanitize_standalone_token():
    raw = "Connected with token 987654321:AAEk92mfkLSmqP01234567890123456789a"
    sanitized = sanitize_sensitive_data(raw)
    assert "987654321:AAEk92mfkLSmqP01234567890123456789a" not in sanitized
    assert "***REDACTED_TELEGRAM_TOKEN***" in sanitized

def test_sanitize_github_token():
    raw = "Git remote origin: https://ghp_1234567890abcdefghijklmnopqrstuvwxyz@github.com/repo.git"
    sanitized = sanitize_sensitive_data(raw)
    assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz" not in sanitized
    assert "***REDACTED_GITHUB_TOKEN***" in sanitized

def test_sanitize_safe_text():
    raw = "Normal log message: BTC/USDT price is 84000.5"
    assert sanitize_sensitive_data(raw) == raw
