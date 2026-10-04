import os
import sys

# Ensure the project root is in the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from tradingbot.core.bot import TradingBot
from tradingbot.core.orchestrator import OrchestratorBot
from tradingbot.interfaces.telegram.telegram_listener import TelegramListener
from tradingbot.utils.logger import log

import argparse

def main():
    parser = argparse.ArgumentParser(description="Tredding Bot - Automated Crypto Trading Agent")
    parser.add_argument("--test", action="store_true", help="Run in test mode (no trading)")
    parser.add_argument("--legacy", action="store_true", help="Run legacy single-bot mode instead of multi-agent")
    args = parser.parse_args()

    log.info("Initializing TradingBot Application...")
    try:
        if args.legacy:
            log.info("Starting in LEGACY single-bot mode...")
            bot = TradingBot()
            bot.start()
            listener = TelegramListener(bot)
            listener.start_polling()
        else:
            log.info("Starting in MULTI-AGENT Orchestrator mode (Architecture v1)...")
            orchestrator = OrchestratorBot()
            orchestrator.start_all()
            listener = TelegramListener(orchestrator)
            listener.start_polling()
    except Exception as e:
        log.error(f"Failed to start TradingBot: {e}")

if __name__ == "__main__":
    main()
